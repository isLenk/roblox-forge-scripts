"""WikiSearchOverlay — floating search bar for quick wiki lookups."""

import tkinter as tk

from core.theme import BG, BG2, DIM, ACCENT, GREEN
from wiki.data import normalize_entry_data
from wiki.search import search_all_entries


class WikiSearchOverlay:
    """Floating search bar for quick wiki lookups from the radial menu."""

    def __init__(self, root, wiki_data, open_wiki_callback):
        self.root = root
        self.data = wiki_data
        self._open_wiki = open_wiki_callback
        self._tooltip = None
        self._tooltip_after_id = None
        self._hovered_idx = -1
        self._build()

    def _build(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        w, h = 480, 72
        x = (sw - w) // 2
        y = (sh - h) // 2 - 120

        self.win = tk.Toplevel(self.root)
        self.win.overrideredirect(True)
        self.win.attributes('-topmost', True)
        self.win.attributes('-alpha', 0.97)
        self.win.configure(bg='#1f6feb')
        self.win.geometry(f'{w}x{h}+{x}+{y}')
        self._win_x = x
        self._win_y = y
        self._win_w = w

        inner = tk.Frame(self.win, bg=BG)
        inner.pack(fill='both', expand=True, padx=2, pady=2)

        row = tk.Frame(inner, bg=BG)
        row.pack(fill='both', expand=True)

        tk.Label(row, text='\U0001f50d', font=('Segoe UI Emoji', 13),
                 fg=DIM, bg=BG).pack(side=tk.LEFT, padx=(10, 0))

        self._search_var = tk.StringVar()
        entry_frame = tk.Frame(row, bg=BG)
        entry_frame.pack(side=tk.LEFT, fill='both', expand=True, padx=(6, 10))
        self._entry_font = ('Consolas', 13)
        self._entry = tk.Entry(
            entry_frame, textvariable=self._search_var,
            font=self._entry_font, fg='#e6edf3', bg=BG,
            insertbackground=ACCENT, bd=0, relief='flat')
        self._entry.pack(fill='both', expand=True)
        self._ghost_label = tk.Label(
            entry_frame, text='', font=self._entry_font,
            fg='#484f58', bg=BG, anchor='w')
        self._ghost_suffix = ''
        self._entry.focus_force()

        self._placeholder_on = True
        self._entry.insert(0, 'Search wiki...')
        self._entry.config(fg=DIM)
        self._entry.bind('<FocusIn>', self._on_entry_focus)

        hint = tk.Label(
            inner,
            text='a, b  multi-search  \u2502  :col  filter by column',
            font=('Consolas', 8), fg=DIM, bg=BG, anchor='w')
        hint.pack(fill='x', padx=(12, 10), pady=(0, 2))

        self._all_columns = self._collect_columns()
        self._search_var.trace_add('write', self._on_type)
        self._entry.bind('<Escape>', lambda e: self.close())
        self._entry.bind('<Return>', self._on_enter)
        self._entry.bind('<Tab>', self._on_tab)
        self._entry.bind('<Down>', self._on_arrow_down)
        self._entry.bind('<Up>', self._on_arrow_up)
        self.win.bind('<FocusOut>', self._on_focus_out)

        self._dropdown = None
        self._dropdown_items = []
        self._results = []

    def _on_entry_focus(self, event):
        if self._placeholder_on:
            self._entry.delete(0, tk.END)
            self._entry.config(fg='#e6edf3')
            self._placeholder_on = False

    def _collect_columns(self):
        """Gather all unique column names from the wiki data."""
        cols = set()
        for entry in self.data.get('entries', {}).values():
            tables = normalize_entry_data(entry.get('data'))
            if not tables:
                continue
            for table in tables:
                rows = table.get('rows', [])
                if rows:
                    cols.update(rows[0].keys())
        return sorted(cols)

    def _get_col_completion(self):
        """Return (token_start, prefix, completed) for a :col token at cursor,
        or None if no completion is available."""
        text = self._entry.get()
        cursor = self._entry.index(tk.INSERT)
        left = text[:cursor]
        seg_start = left.rfind(',')
        seg_start = seg_start + 1 if seg_start >= 0 else 0
        segment = left[seg_start:].lstrip()
        if not segment.startswith(':') or len(segment) < 2:
            return None
        prefix = segment[1:]
        matches = [c for c in self._all_columns
                   if c.lower().startswith(prefix.lower())]
        if not matches:
            return None
        completed = matches[0]
        if completed.lower() == prefix.lower():
            return None
        token_start = seg_start + (len(left[seg_start:])
                                   - len(left[seg_start:].lstrip()))
        return token_start, prefix, completed

    def _update_ghost(self):
        """Show or hide the ghost completion text after the cursor."""
        result = self._get_col_completion()
        if not result:
            self._hide_ghost()
            return
        _, prefix, completed = result
        suffix = completed[len(prefix):]
        self._ghost_suffix = suffix
        # Measure pixel offset of cursor position
        import tkinter.font as tkfont
        font = tkfont.Font(font=self._entry_font)
        text = self._entry.get()
        cursor = self._entry.index(tk.INSERT)
        text_px = font.measure(text[:cursor])
        self._ghost_label.config(text=suffix)
        self._ghost_label.place(x=text_px, y=0, height=self._entry.winfo_height())

    def _hide_ghost(self):
        self._ghost_suffix = ''
        self._ghost_label.place_forget()

    def _on_tab(self, event):
        """Accept the ghost completion."""
        result = self._get_col_completion()
        if not result:
            return 'break'
        token_start, prefix, completed = result
        cursor = self._entry.index(tk.INSERT)
        self._entry.delete(token_start, cursor)
        self._entry.insert(token_start, f':{completed}')
        self._hide_ghost()
        return 'break'

    def close(self):
        self._close_tooltip()
        self._close_dropdown()
        try:
            self.win.destroy()
        except Exception:
            pass

    def _on_focus_out(self, event):
        try:
            focused = self.root.focus_get()
            if focused:
                top = focused.winfo_toplevel()
                if top == self.win:
                    return
                if self._dropdown and top == self._dropdown:
                    return
                if self._tooltip and top == self._tooltip:
                    return
        except Exception:
            pass
        self.root.after(150, self._check_focus)

    def _check_focus(self):
        try:
            focused = self.root.focus_get()
            if focused:
                top = focused.winfo_toplevel()
                if top == self.win:
                    return
                if self._dropdown and top == self._dropdown:
                    return
                if self._tooltip and top == self._tooltip:
                    return
        except Exception:
            pass
        self.close()

    def _on_type(self, *_):
        if self._placeholder_on:
            return
        # Defer ghost update so the cursor position is current
        self._entry.after_idle(self._update_ghost)
        query = self._search_var.get().strip()
        if not query:
            self._close_dropdown()
            self._close_tooltip()
            return

        self._results = search_all_entries(self.data, query)
        if not self._results:
            self._close_dropdown()
            self._close_tooltip()
            return

        self._show_dropdown()

    def _show_dropdown(self):
        self._close_dropdown()
        self._hovered_idx = -1
        x = self._win_x
        y = self._win_y + 74
        w = self._win_w
        item_h = 32
        avail = self.root.winfo_screenheight() - y - 40
        max_visible = min(len(self._results), max(1, avail // item_h))
        h = max_visible * item_h + 4
        needs_scroll = len(self._results) > max_visible

        dd = tk.Toplevel(self.root)
        dd.overrideredirect(True)
        dd.attributes('-topmost', True)
        dd.attributes('-alpha', 0.97)
        dd.configure(bg='#1f6feb')
        dd.geometry(f'{w}x{h}+{x}+{y}')

        inner = tk.Frame(dd, bg=BG)
        inner.pack(fill='both', expand=True, padx=2, pady=2)

        if needs_scroll:
            canvas = tk.Canvas(inner, bg=BG, highlightthickness=0)
            container = tk.Frame(canvas, bg=BG)
            container.bind('<Configure>',
                           lambda e: canvas.configure(
                               scrollregion=canvas.bbox('all')))
            canvas.create_window((0, 0), window=container, anchor='nw',
                                width=w - 6)
            canvas.pack(fill='both', expand=True)

            def _on_wheel(e):
                canvas.yview_scroll(-1 * (e.delta // 120), 'units')
            canvas.bind('<MouseWheel>', _on_wheel)
            container.bind('<MouseWheel>', _on_wheel)
            parent = container
        else:
            parent = inner

        self._dropdown_items = []
        for i, (entry_name, row, field, value, _ti) in enumerate(self._results):
            item = tk.Frame(parent, bg=BG, cursor='hand2')
            item.pack(fill='x')

            name_lbl = tk.Label(
                item, text=entry_name,
                font=('Consolas', 9, 'bold'), fg=ACCENT, bg=BG, anchor='w')
            name_lbl.pack(side=tk.LEFT, padx=(10, 4))

            first_val = next(iter(row.values()), value)
            detail_lbl = tk.Label(
                item, text=str(first_val),
                font=('Consolas', 9), fg='#8b949e', bg=BG, anchor='w')
            detail_lbl.pack(side=tk.LEFT, fill='x', expand=True, padx=(0, 10))

            item.configure(height=item_h)
            item.pack_propagate(False)

            widgets = [item, name_lbl, detail_lbl]
            for widget in widgets:
                widget.bind('<Enter>',
                            lambda e, idx=i: self._on_item_hover(idx))
                widget.bind('<Button-1>',
                            lambda e, idx=i: self._on_item_click(idx))
                if needs_scroll:
                    widget.bind('<MouseWheel>', _on_wheel)

            self._dropdown_items.append({
                'frame': item, 'name': name_lbl, 'detail': detail_lbl})

        dd.bind('<Escape>', lambda e: self.close())
        self._dropdown = dd

    def _on_item_hover(self, idx):
        if idx == self._hovered_idx:
            return
        if 0 <= self._hovered_idx < len(self._dropdown_items):
            prev = self._dropdown_items[self._hovered_idx]
            for w in (prev['frame'], prev['name'], prev['detail']):
                w.config(bg=BG)

        self._hovered_idx = idx
        if 0 <= idx < len(self._dropdown_items):
            cur = self._dropdown_items[idx]
            hbg = '#161b22'
            for w in (cur['frame'], cur['name'], cur['detail']):
                w.config(bg=hbg)
            self._show_result_tooltip(idx)

    def _on_item_click(self, idx):
        if 0 <= idx < len(self._results):
            r = self._results[idx]
            entry_name, row, ti = r[0], r[1], r[4]
            first_val = str(next(iter(row.values()), ''))
            self._open_in_wiki(entry_name, first_val, ti)

    def _close_dropdown(self):
        if self._dropdown:
            try:
                self._dropdown.destroy()
            except Exception:
                pass
            self._dropdown = None
            self._dropdown_items = []
            self._hovered_idx = -1

    def _on_arrow_down(self, event):
        if not self._dropdown or not self._results:
            return
        new = min(self._hovered_idx + 1, len(self._dropdown_items) - 1)
        self._on_item_hover(new)

    def _on_arrow_up(self, event):
        if not self._dropdown or not self._results:
            return
        new = max(self._hovered_idx - 1, 0)
        self._on_item_hover(new)

    def _on_enter(self, event):
        if 0 <= self._hovered_idx < len(self._results):
            r = self._results[self._hovered_idx]
            entry_name, row, ti = r[0], r[1], r[4]
            first_val = str(next(iter(row.values()), ''))
            self._open_in_wiki(entry_name, first_val, ti)
        elif self._results:
            self._on_item_hover(0)

    def _show_result_tooltip(self, idx):
        if idx >= len(self._results):
            return
        r = self._results[idx]
        entry_name, row, ti = r[0], r[1], r[4]
        first_val = str(next(iter(row.values()), ''))
        self._close_tooltip()

        tip_w = 400
        items = [(k, v) for k, v in row.items() if str(v).strip()]

        tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        tip.attributes('-topmost', True)
        tip.attributes('-alpha', 0.97)
        tip.configure(bg='#1f6feb')

        inner = tk.Frame(tip, bg=BG)
        inner.pack(fill='both', expand=True, padx=2, pady=2)

        hdr = tk.Frame(inner, bg='#1a2233')
        hdr.pack(fill='x')
        tk.Label(hdr, text=entry_name,
                 font=('Consolas', 10, 'bold'), fg=ACCENT, bg='#1a2233',
                 anchor='w').pack(fill='x', padx=8, pady=(4, 4))

        for i, (k, v) in enumerate(items):
            rbg = '#131921' if i % 2 else BG
            row_f = tk.Frame(inner, bg=rbg)
            row_f.pack(fill='x')
            tk.Label(row_f, text=k, font=('Consolas', 8, 'bold'),
                     fg=DIM, bg=rbg, anchor='nw', width=12).pack(
                         side=tk.LEFT, padx=(8, 4), pady=1)
            tk.Label(row_f, text=str(v), font=('Consolas', 9),
                     fg='#e6edf3', bg=rbg, anchor='w',
                     wraplength=tip_w - 140).pack(
                         side=tk.LEFT, fill='x', padx=(0, 8), pady=1)

        link_f = tk.Frame(inner, bg=BG)
        link_f.pack(fill='x')
        link = tk.Label(
            link_f, text='\u25B6  Open in Wiki',
            font=('Consolas', 9, 'bold'), fg=GREEN, bg=BG,
            cursor='hand2', anchor='w')
        link.pack(padx=8, pady=(4, 4))
        link.bind('<Button-1>',
                  lambda e, n=entry_name, k=first_val, t=ti: self._open_in_wiki(n, k, t))
        link.bind('<Enter>', lambda e: link.config(fg='#70ffab'))
        link.bind('<Leave>', lambda e: link.config(fg=GREEN))

        tip.update_idletasks()
        tip_h = tip.winfo_reqheight()
        tip_x = self._win_x + self._win_w + 10
        tip_y = self._win_y
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        if tip_x + tip_w > screen_w:
            tip_x = self._win_x - tip_w - 10
        tip_h = min(tip_h, screen_h - tip_y - 40)
        tip.geometry(f'{tip_w}x{tip_h}+{tip_x}+{tip_y}')

        self._tooltip = tip
        self._tooltip_after_id = self.root.after(10000, self._close_tooltip)

    def _close_tooltip(self):
        if self._tooltip_after_id:
            try:
                self.root.after_cancel(self._tooltip_after_id)
            except Exception:
                pass
            self._tooltip_after_id = None
        if self._tooltip:
            try:
                self._tooltip.destroy()
            except Exception:
                pass
            self._tooltip = None

    def _open_in_wiki(self, entry_name, highlight_key=None, table_index=None):
        self.close()
        self._open_wiki(entry_name, highlight_key, table_index)
