"""Themed modal dialogs — flat, dark replacements for simpledialog/messagebox."""

import tkinter as tk
from core.theme import (BG, BG2, BORDER, DIM, ACCENT, GREEN, RED, TEXT,
                        apply_rounded_corners)


class ThemedModal:
    """A dark-themed modal dialog.

    Usage
    -----
    Input dialog (one or more fields)::

        result = ThemedModal.ask(parent, title="New Entry", fields=[
            {"label": "Name"},
            {"label": "URL", "placeholder": "https://..."},
        ])
        # result = ["my entry", "https://..."]  or  None if cancelled

    Single-field shortcut::

        value = ThemedModal.ask_string(parent, "Save Macro", "Macro name:")
        # value = "name"  or  None

    Confirmation dialog::

        ok = ThemedModal.confirm(parent, "Delete?", "Remove this entry?")
        # ok = True / False
    """

    def __init__(self, parent, *, title="", fields=None, message=None,
                 confirm_only=False, ok_text="OK", cancel_text="Cancel"):
        self.result = None
        self._entries = []

        # Toplevel
        win = tk.Toplevel(parent)
        win.overrideredirect(True)
        win.attributes('-topmost', True)
        win.configure(bg=BG)
        win.grab_set()
        win.focus_force()
        apply_rounded_corners(win)
        self._win = win

        # -- Title bar --
        titlebar = tk.Frame(win, bg=BG, height=28)
        titlebar.pack(fill='x')
        titlebar.pack_propagate(False)

        tk.Label(titlebar, text=title,
                 font=('Consolas', 9, 'bold'), fg=DIM, bg=BG
                 ).pack(side=tk.LEFT, padx=10)

        close_btn = tk.Label(
            titlebar, text='\u2715', font=('Consolas', 9),
            fg=DIM, bg=BG, padx=8, cursor='hand2')
        close_btn.pack(side=tk.RIGHT, fill='y')
        close_btn.bind('<Button-1>', lambda e: self._cancel())
        close_btn.bind('<Enter>',
                       lambda e: close_btn.config(fg=RED, bg='#1a0000'))
        close_btn.bind('<Leave>',
                       lambda e: close_btn.config(fg=DIM, bg=BG))

        # Dragging
        def _start_drag(event):
            self._dx = event.x
            self._dy = event.y

        def _on_drag(event):
            x = win.winfo_x() + event.x - self._dx
            y = win.winfo_y() + event.y - self._dy
            win.geometry(f"+{x}+{y}")

        for w in (titlebar,):
            w.bind('<Button-1>', _start_drag)
            w.bind('<B1-Motion>', _on_drag)

        # Separator
        tk.Frame(win, bg=BORDER, height=1).pack(fill='x')

        # -- Body --
        body = tk.Frame(win, bg=BG)
        body.pack(fill='both', expand=True, padx=16, pady=(12, 8))

        if message:
            tk.Label(body, text=message, font=('Consolas', 10),
                     fg=TEXT, bg=BG, wraplength=280, justify='left'
                     ).pack(anchor='w', pady=(0, 8))

        if fields:
            for i, field in enumerate(fields):
                label = field.get('label', '')
                placeholder = field.get('placeholder', '')
                initial = field.get('initial', '')

                tk.Label(body, text=label, font=('Consolas', 9),
                         fg=DIM, bg=BG).pack(anchor='w', pady=(4 if i else 0, 2))

                entry = tk.Entry(
                    body, font=('Consolas', 10), fg=TEXT, bg=BG2,
                    insertbackground=ACCENT, bd=0, relief='flat',
                    highlightthickness=1, highlightcolor=ACCENT,
                    highlightbackground=BORDER)
                entry.pack(fill='x', ipady=4)
                self._entries.append(entry)

                if initial:
                    entry.insert(0, initial)
                    entry.select_range(0, tk.END)
                elif placeholder:
                    entry.insert(0, placeholder)
                    entry.config(fg=DIM)
                    entry.bind('<FocusIn>',
                               lambda e, ent=entry, ph=placeholder:
                               self._clear_placeholder(ent, ph))
                    entry.bind('<FocusOut>',
                               lambda e, ent=entry, ph=placeholder:
                               self._restore_placeholder(ent, ph))

        # -- Button row --
        btn_row = tk.Frame(win, bg=BG)
        btn_row.pack(fill='x', padx=16, pady=(4, 12))

        cancel_btn = tk.Button(
            btn_row, text=cancel_text, font=('Consolas', 9),
            fg=DIM, bg=BORDER, activebackground='#30363d',
            activeforeground=TEXT, bd=0, relief='flat',
            padx=14, pady=4, cursor='hand2',
            command=self._cancel)
        cancel_btn.pack(side=tk.RIGHT, padx=(6, 0))
        cancel_btn.bind('<Enter>', lambda e: cancel_btn.config(bg='#30363d'))
        cancel_btn.bind('<Leave>', lambda e: cancel_btn.config(bg=BORDER))

        ok_color = RED if confirm_only and 'delete' in (message or '').lower() else ACCENT
        ok_btn = tk.Button(
            btn_row, text=ok_text, font=('Consolas', 9, 'bold'),
            fg=BG, bg=ok_color, activebackground=ok_color,
            activeforeground=BG, bd=0, relief='flat',
            padx=14, pady=4, cursor='hand2',
            command=self._ok)
        ok_btn.pack(side=tk.RIGHT)
        ok_btn.bind('<Enter>', lambda e: ok_btn.config(bg=self._lighten(ok_color)))
        ok_btn.bind('<Leave>', lambda e: ok_btn.config(bg=ok_color))
        self._ok_color = ok_color

        # Keybindings
        win.bind('<Return>', lambda e: self._ok())
        win.bind('<Escape>', lambda e: self._cancel())

        # Focus first entry
        if self._entries:
            first = self._entries[0]
            first.focus_set()
            if first.get() and first.cget('fg') != DIM:
                first.icursor(tk.END)

        # Size and center on parent
        win.update_idletasks()
        width = max(win.winfo_reqwidth(), 320)
        height = win.winfo_reqheight()
        win.geometry(f"{width}x{height}")
        px = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        win.geometry(f"+{max(px, 0)}+{max(py, 0)}")

        self._confirm_only = confirm_only

    @staticmethod
    def _lighten(hex_color):
        r = min(int(hex_color[1:3], 16) + 30, 255)
        g = min(int(hex_color[3:5], 16) + 30, 255)
        b = min(int(hex_color[5:7], 16) + 30, 255)
        return f'#{r:02x}{g:02x}{b:02x}'

    def _clear_placeholder(self, entry, placeholder):
        if entry.get() == placeholder:
            entry.delete(0, tk.END)
            entry.config(fg=TEXT)

    def _restore_placeholder(self, entry, placeholder):
        if not entry.get():
            entry.insert(0, placeholder)
            entry.config(fg=DIM)

    def _ok(self):
        if self._confirm_only:
            self.result = True
        else:
            values = []
            for entry in self._entries:
                val = entry.get().strip()
                if entry.cget('fg') == DIM:
                    val = ''
                values.append(val)
            self.result = values
        self._win.grab_release()
        self._win.destroy()

    def _cancel(self):
        self.result = None
        self._win.grab_release()
        self._win.destroy()

    def wait(self):
        """Block until the modal is closed and return the result."""
        self._win.wait_window()
        return self.result

    # ---- Convenience class methods ----

    @classmethod
    def ask(cls, parent, title, fields):
        """Show an input modal.  *fields* is a list of dicts with keys
        ``label``, and optionally ``placeholder`` and ``initial``.
        Returns a list of strings or ``None`` if cancelled.
        """
        modal = cls(parent, title=title, fields=fields)
        return modal.wait()

    @classmethod
    def ask_string(cls, parent, title, prompt, *, initial=''):
        """Single-field input.  Returns a string or ``None``."""
        fields = [{'label': prompt, 'initial': initial}]
        result = cls.ask(parent, title, fields)
        if result and result[0]:
            return result[0]
        return None

    @classmethod
    def confirm(cls, parent, title, message, *, ok_text="OK",
                cancel_text="Cancel"):
        """Yes/no confirmation.  Returns ``True`` or ``False``."""
        modal = cls(parent, title=title, message=message,
                    confirm_only=True, ok_text=ok_text,
                    cancel_text=cancel_text)
        return modal.wait() is True
