"""WikiWindow — Toplevel panel for browsing wiki data."""

import tkinter as tk
from tkinter import ttk
from threading import Thread
from datetime import datetime

from core.theme import (BG, BG2, BORDER, DIM, ACCENT, GREEN, RED,
                        style_flat_treeview, apply_rounded_corners)
from core.modal import ThemedModal
from wiki.data import load_wiki_data, save_wiki_data, normalize_entry_data
from wiki.parser import extract_wiki_data
from wiki.search import search_all_entries


class WikiWindow:
    def __init__(self, root, data=None):
        self.root = root
        self.data = data if data else load_wiki_data()
        self._nav_items = {}      # iid -> (entry_name, table_index | None)
        self._build()

    def destroy(self):
        try:
            self.panel.destroy()
        except Exception:
            pass

    def _build(self):
        root_x = self.root.winfo_x()
        root_y = self.root.winfo_y()
        root_w = self.root.winfo_width()

        panel = tk.Toplevel(self.root)
        panel.overrideredirect(True)
        panel.geometry(f"700x520+{root_x + root_w + 10}+{root_y}")
        panel.attributes('-topmost', True)
        panel.configure(bg=BG)
        panel.minsize(500, 350)
        apply_rounded_corners(panel)
        self.panel = panel

        bg_frame = tk.Frame(panel, bg=BG)
        bg_frame.place(x=0, y=0, relwidth=1, relheight=1)

        # Title bar
        titlebar = tk.Frame(panel, bg=BG, height=30)
        titlebar.pack(fill='x')
        titlebar.pack_propagate(False)

        title_lbl = tk.Label(
            titlebar, text="WIKI",
            font=("Consolas", 9, "bold"), fg=DIM, bg=BG)
        title_lbl.pack(side=tk.LEFT, padx=10)

        close_btn = tk.Label(
            titlebar, text='\u2715', font=('Consolas', 10),
            fg=DIM, bg=BG, padx=10, cursor='hand2')
        close_btn.pack(side=tk.RIGHT, fill='y')
        close_btn.bind('<Button-1>', lambda e: self._on_close())
        close_btn.bind('<Enter>',
                       lambda e: close_btn.config(fg=RED, bg='#1a0000'))
        close_btn.bind('<Leave>',
                       lambda e: close_btn.config(fg=DIM, bg=BG))

        def _start_drag(event):
            self._drag_x = event.x
            self._drag_y = event.y

        def _on_drag(event):
            x = panel.winfo_x() + event.x - self._drag_x
            y = panel.winfo_y() + event.y - self._drag_y
            panel.geometry(f"+{x}+{y}")

        for w in (titlebar, title_lbl):
            w.bind('<Button-1>', _start_drag)
            w.bind('<B1-Motion>', _on_drag)

        # Search bar
        search_frame = tk.Frame(panel, bg=BG)
        search_frame.pack(fill='x', padx=10, pady=(4, 4))

        self._search_var = tk.StringVar()
        self._search_entry = tk.Entry(
            search_frame, textvariable=self._search_var,
            font=('Consolas', 10), fg='#c9d1d9', bg=BG2,
            insertbackground=ACCENT, bd=1, relief='flat')
        self._search_entry.pack(fill='x', ipady=3)
        self._search_entry.insert(0, 'Search all entries...')
        self._search_entry.config(fg=DIM)
        self._search_entry.bind('<FocusIn>', self._on_search_focus_in)
        self._search_entry.bind('<FocusOut>', self._on_search_focus_out)
        self._search_var.trace_add('write', self._on_search_changed)

        # Main body (left nav + right table)
        body = tk.Frame(panel, bg=BG)
        body.pack(fill='both', expand=True, padx=10, pady=(0, 4))

        left = tk.Frame(body, bg=BG2, width=200)
        left.pack(side=tk.LEFT, fill='y')
        left.pack_propagate(False)

        # Draggable sash between left and right panels
        sash = tk.Frame(body, bg=BORDER, width=4, cursor='sb_h_double_arrow')
        sash.pack(side=tk.LEFT, fill='y', padx=(2, 4))

        def _sash_start(event):
            self._sash_x = event.x_root
            self._sash_w = left.winfo_width()

        def _sash_drag(event):
            dx = event.x_root - self._sash_x
            new_w = max(100, min(self._sash_w + dx, panel.winfo_width() - 200))
            left.config(width=new_w)

        sash.bind('<Button-1>', _sash_start)
        sash.bind('<B1-Motion>', _sash_drag)
        sash.bind('<Enter>', lambda e: sash.config(bg=ACCENT))
        sash.bind('<Leave>', lambda e: sash.config(bg=BORDER))

        # --- Styles ---
        style = ttk.Style(panel)
        style.theme_use('clam')
        ROW_ALT = '#131921'
        self._row_alt_color = ROW_ALT
        style_flat_treeview(style, 'Wiki', heading_bg='#1a2233')

        # Nav tree style
        style.configure("Nav.Treeview",
                         background=BG2, foreground='#c9d1d9',
                         fieldbackground=BG2,
                         borderwidth=0, relief='flat',
                         font=('Consolas', 10), rowheight=24, indent=14)
        style.layout("Nav.Treeview", [
            ("Nav.Treeview.treearea", {"sticky": "nswe"}),
        ])
        style.map("Nav.Treeview",
                  background=[('selected', '#1f6feb')],
                  foreground=[('selected', '#ffffff')])

        # Directory tree
        self._nav_tree = ttk.Treeview(
            left, show='tree', style='Nav.Treeview',
            selectmode='browse')
        self._nav_tree.pack(fill='both', expand=True, padx=4, pady=(4, 0))
        self._nav_tree.bind('<<TreeviewSelect>>', self._on_nav_select)
        self._nav_tree.bind('<Delete>', self._delete_selected_entry)

        add_frame = tk.Frame(left, bg=BG2)
        add_frame.pack(fill='x', padx=4, pady=(2, 4))
        add_btn = tk.Label(
            add_frame, text='+ Add entry',
            font=('Consolas', 9), fg=DIM, bg=BG2, cursor='hand2',
            anchor='w', padx=4, pady=2)
        add_btn.pack(fill='x')
        add_btn.bind('<Button-1>', lambda e: self._add_entry())
        add_btn.bind('<Enter>', lambda e: add_btn.config(fg=ACCENT))
        add_btn.bind('<Leave>', lambda e: add_btn.config(fg=DIM))

        # Right panel
        right = tk.Frame(body, bg=BG)
        right.pack(side=tk.LEFT, fill='both', expand=True)

        header_row = tk.Frame(right, bg=BG)
        header_row.pack(fill='x', pady=(0, 4))

        self._entry_name_lbl = tk.Label(
            header_row, text='Select an entry',
            font=('Consolas', 11, 'bold'), fg='#c9d1d9', bg=BG, anchor='w')
        self._entry_name_lbl.pack(side=tk.LEFT, fill='x', expand=True)

        self._regen_btn = tk.Button(
            header_row, text='\u21BB Regen', font=('Consolas', 9, 'bold'),
            fg=ACCENT, bg=BORDER, activebackground='#30363d',
            activeforeground=ACCENT, bd=0, relief='flat', padx=6, pady=1,
            command=self._regenerate_entry)
        self._regen_btn.pack(side=tk.RIGHT)

        url_row = tk.Frame(right, bg=BG)
        url_row.pack(fill='x', pady=(0, 4))
        tk.Label(url_row, text='URL:', font=('Consolas', 9),
                 fg=DIM, bg=BG).pack(side=tk.LEFT)
        self._url_lbl = tk.Label(
            url_row, text='', font=('Consolas', 9),
            fg=ACCENT, bg=BG, anchor='w')
        self._url_lbl.pack(side=tk.LEFT, fill='x', expand=True, padx=(4, 0))

        self._status_lbl = tk.Label(
            right, text='', font=('Consolas', 9), fg=DIM, bg=BG, anchor='w')
        self._status_lbl.pack(fill='x')

        # Single table display area (replaces notebook tabs)
        self._table_frame = tk.Frame(right, bg=BG)
        self._table_frame.pack(fill='both', expand=True)

        self._selected_entry = None
        self._current_tree = None
        self._refresh_nav()

        entries = self.data.get('entries', {})
        if len(entries) == 1:
            # Auto-select the only entry
            children = self._nav_tree.get_children()
            if children:
                self._nav_tree.selection_set(children[0])
                self._nav_tree.item(children[0], open=True)
                self._on_nav_select(None)

        # Resize grip
        grip = tk.Label(panel, text='\u2921', font=('Consolas', 12),
                        fg='#30363d', bg=BG, cursor='bottom_right_corner')
        grip.place(relx=1.0, rely=1.0, anchor='se')

        def _start_resize(event):
            self._resize_x = event.x_root
            self._resize_y = event.y_root
            self._resize_w = panel.winfo_width()
            self._resize_h = panel.winfo_height()

        def _on_resize(event):
            dw = event.x_root - self._resize_x
            dh = event.y_root - self._resize_y
            nw = max(self._resize_w + dw, 500)
            nh = max(self._resize_h + dh, 350)
            panel.geometry(f"{nw}x{nh}")

        grip.bind('<Button-1>', _start_resize)
        grip.bind('<B1-Motion>', _on_resize)

    # ---- Navigation tree ----

    def _refresh_nav(self, filter_names=None):
        """Rebuild the directory tree.  If *filter_names* is given, only
        show those entry names."""
        self._nav_tree.delete(*self._nav_tree.get_children())
        self._nav_items.clear()

        entries = self.data.get('entries', {})
        for name, entry in entries.items():
            if filter_names is not None and name not in filter_names:
                continue
            iid = self._nav_tree.insert('', tk.END, text=name, open=False)
            self._nav_items[iid] = (name, None)
            tables = normalize_entry_data(entry.get('data'))
            if tables:
                for i, tbl in enumerate(tables):
                    tbl_name = tbl.get('name', f'Table {i+1}')
                    child_iid = self._nav_tree.insert(iid, tk.END,
                                                       text=tbl_name)
                    self._nav_items[child_iid] = (name, i)

    def _on_nav_select(self, event):
        sel = self._nav_tree.selection()
        if not sel:
            return
        iid = sel[0]
        info = self._nav_items.get(iid)
        if not info:
            return
        entry_name, table_idx = info

        entry = self.data.get('entries', {}).get(entry_name)
        if not entry:
            return

        # If clicking an entry (parent), expand it
        if table_idx is None:
            self._nav_tree.item(iid, open=True)

        self._selected_entry = entry_name
        self._entry_name_lbl.config(text=f'Entry: "{entry_name}"')
        self._url_lbl.config(text=entry.get('url', ''))

        tables = normalize_entry_data(entry.get('data'))
        if not tables:
            self._clear_table()
            self._status_lbl.config(
                text='No data yet \u2014 click Regen to extract', fg=DIM)
            return

        # Entry click → first table; table click → that table
        idx = table_idx if table_idx is not None else 0
        if idx < len(tables):
            tbl = tables[idx]
            self._show_table(tbl.get('rows', []))
            total_rows = sum(len(t.get('rows', [])) for t in tables)
            ts = entry.get('extracted_at', '')
            tbl_name = tbl.get('name', f'Table {idx+1}')
            self._status_lbl.config(
                text=f'{tbl_name}  \u2502  {total_rows} row(s) in '
                     f'{len(tables)} table(s)  \u2502  {ts}',
                fg=DIM)

    # ---- Table display ----

    def _clear_table(self):
        self._current_tree = None
        for w in self._table_frame.winfo_children():
            w.destroy()

    def _show_table(self, rows):
        self._clear_table()
        if not rows:
            tk.Label(self._table_frame, text='No data',
                     font=('Consolas', 10), fg=DIM, bg=BG).pack(expand=True)
            return

        all_cols = list(rows[0].keys())
        cols = [c for c in all_cols
                if any(str(row.get(c, '')).strip() for row in rows[:20])]
        if not cols:
            cols = all_cols

        tree = ttk.Treeview(
            self._table_frame, columns=cols, show='headings',
            style='Wiki.Treeview', selectmode='browse')
        self._current_tree = tree

        sort_state = {}  # col -> True=ascending, False=descending

        def _sort_by(col):
            ascending = not sort_state.get(col, False)
            sort_state.clear()
            sort_state[col] = ascending

            items = [(tree.set(iid, col), iid)
                     for iid in tree.get_children()]
            # Try numeric sort, fall back to string
            try:
                items.sort(key=lambda x: float(x[0]),
                           reverse=not ascending)
            except ValueError:
                items.sort(key=lambda x: x[0].lower(),
                           reverse=not ascending)

            for idx, (_, iid) in enumerate(items):
                tree.move(iid, '', idx)
                tag = 'oddrow' if idx % 2 else 'evenrow'
                tree.item(iid, tags=(tag,))

            # Update heading text with sort arrow
            arrow = ' \u25b2' if ascending else ' \u25bc'
            for c in cols:
                tree.heading(c, text=c + (arrow if c == col else ''))

        for col in cols:
            tree.heading(col, text=col,
                         command=lambda c=col: _sort_by(c))
            max_w = len(col) * 9
            for row in rows[:20]:
                val_w = len(str(row.get(col, ''))) * 8
                if val_w > max_w:
                    max_w = val_w
            tree.column(col, width=min(max_w + 16, 250), anchor='w')

        tree.tag_configure('oddrow', background=self._row_alt_color)
        tree.tag_configure('evenrow', background=BG2)
        tree.tag_configure('highlight', background='#1f6feb',
                           foreground='#ffffff')

        for i, row in enumerate(rows):
            vals = [str(row.get(c, '')) for c in cols]
            tag = 'oddrow' if i % 2 else 'evenrow'
            tree.insert('', tk.END, values=vals, tags=(tag,))

        y_scroll = ttk.Scrollbar(self._table_frame, orient='vertical',
                                  command=tree.yview,
                                  style='Wiki.Vertical.TScrollbar')
        x_scroll = ttk.Scrollbar(self._table_frame, orient='horizontal',
                                  command=tree.xview,
                                  style='Wiki.Horizontal.TScrollbar')
        tree.configure(yscrollcommand=y_scroll.set,
                        xscrollcommand=x_scroll.set)
        x_scroll.pack(side=tk.BOTTOM, fill='x')
        tree.pack(side=tk.LEFT, fill='both', expand=True)
        y_scroll.pack(side=tk.RIGHT, fill='y')

    # ---- Search ----

    def _on_close(self):
        self._save()
        self.panel.destroy()

    def _save(self):
        save_wiki_data(self.data)

    def _on_search_focus_in(self, event):
        if self._search_entry.get() == 'Search all entries...':
            self._search_entry.delete(0, tk.END)
            self._search_entry.config(fg='#c9d1d9')

    def _on_search_focus_out(self, event):
        if not self._search_entry.get():
            self._search_entry.insert(0, 'Search all entries...')
            self._search_entry.config(fg=DIM)

    def _on_search_changed(self, *_):
        query = self._search_var.get()
        if query == 'Search all entries...' or not query:
            self._refresh_nav()
            self._clear_table()
            self._status_lbl.config(text='', fg=DIM)
            return

        results = search_all_entries(self.data, query)
        q = query.lower()
        name_matches = [n for n in self.data.get('entries', {})
                        if q in n.lower()]

        if not results and not name_matches:
            self._clear_table()
            self._status_lbl.config(text='No results found', fg=RED)
            return

        matched_names = list(dict.fromkeys(
            name_matches + [r[0] for r in results]))
        self._refresh_nav(filter_names=set(matched_names))

        matched_rows = [r[1] for r in results]
        if matched_rows:
            self._show_table(matched_rows)
            self._status_lbl.config(
                text=f'{len(matched_rows)} matching row(s)', fg=GREEN)
        elif name_matches:
            entry = self.data['entries'].get(name_matches[0])
            if entry and entry.get('data'):
                tables = normalize_entry_data(entry['data'])
                if tables:
                    self._show_table(tables[0].get('rows', []))
                self._status_lbl.config(
                    text=f'Showing "{name_matches[0]}"', fg=ACCENT)
            else:
                self._clear_table()
                self._status_lbl.config(
                    text=f'Entry "{name_matches[0]}" (no data)', fg=DIM)

    # ---- Entry management ----

    def _add_entry(self):
        result = ThemedModal.ask(self.panel, "New Wiki Entry", [
            {"label": "Entry name"},
            {"label": "URL", "placeholder": "https://..."},
        ])
        if not result:
            return
        name, url = result[0].strip(), result[1].strip()
        if not name or not url:
            return
        if name in self.data.get('entries', {}):
            ThemedModal.confirm(self.panel, "Duplicate",
                                f'"{name}" already exists.',
                                ok_text="OK", cancel_text="Back")
            return

        self.data.setdefault('entries', {})[name] = {
            "url": url.strip(), "data": None, "extracted_at": None,
        }
        self._save()
        self._refresh_nav()

        # Select the new entry
        for iid, info in self._nav_items.items():
            if info == (name, None):
                self._nav_tree.selection_set(iid)
                self._nav_tree.see(iid)
                self._on_nav_select(None)
                break

    def _delete_selected_entry(self, event=None):
        sel = self._nav_tree.selection()
        if not sel:
            return
        info = self._nav_items.get(sel[0])
        if not info:
            return
        name = info[0]
        if not ThemedModal.confirm(
                self.panel, "Delete Entry",
                f'Delete "{name}" and its cached data?',
                ok_text="Delete", cancel_text="Cancel"):
            return
        self.data.get('entries', {}).pop(name, None)
        self._save()
        self._refresh_nav()
        self._selected_entry = None
        self._entry_name_lbl.config(text='Select an entry')
        self._url_lbl.config(text='')
        self._clear_table()
        self._status_lbl.config(text='', fg=DIM)

    # ---- Regenerate ----

    def _regenerate_entry(self):
        if not self._selected_entry:
            self._status_lbl.config(text='No entry selected', fg=RED)
            return

        name = self._selected_entry
        entry = self.data.get('entries', {}).get(name)
        if not entry:
            return
        url = entry.get('url', '')
        if not url:
            self._status_lbl.config(text='No URL set for this entry', fg=RED)
            return

        self._status_lbl.config(text='Parsing tables...', fg=ACCENT)
        self._regen_btn.config(state='disabled')

        def _worker():
            try:
                tables = extract_wiki_data(url)
                if not tables:
                    self.panel.after(0, lambda: self._on_extract_error(
                        'No tables found on this page'))
                    return
                entry['data'] = tables
                entry['extracted_at'] = datetime.now().isoformat(
                    timespec='seconds')
                save_wiki_data(self.data)
                self.panel.after(
                    0, lambda: self._on_extract_done(name, tables))
            except Exception as e:
                import traceback
                traceback.print_exc()
                msg = (f'{type(e).__name__}: {e}'
                       if str(e) else type(e).__name__)
                self.panel.after(
                    0, lambda m=msg: self._on_extract_error(m))

        Thread(target=_worker, daemon=True).start()

    def _on_extract_done(self, name, tables):
        self._regen_btn.config(state='normal')
        # Rebuild nav so new table children appear
        self._refresh_nav()
        # Re-select the entry and expand it
        for iid, info in self._nav_items.items():
            if info == (name, None):
                self._nav_tree.selection_set(iid)
                self._nav_tree.item(iid, open=True)
                self._nav_tree.see(iid)
                break
        if self._selected_entry == name and tables:
            self._show_table(tables[0].get('rows', []))
            total_rows = sum(len(t.get('rows', [])) for t in tables)
            ts = self.data['entries'][name].get('extracted_at', '')
            self._status_lbl.config(
                text=f'{total_rows} row(s) in {len(tables)} table(s)  |  {ts}',
                fg=GREEN)

    def _on_extract_error(self, msg):
        self._regen_btn.config(state='normal')
        self._status_lbl.config(text=f'Error: {msg}', fg=RED)

    # ---- Public API ----

    def navigate_to(self, entry_name, highlight_key=None,
                    table_index=None):
        """Navigate to an entry, optionally to a specific table and row.

        *table_index* — which table (subsection) to display.
        *highlight_key* — first-column value of the row to highlight.
        """
        # Select the correct nav item (table subsection or entry root)
        target = (entry_name, table_index)
        found = False
        for iid, info in self._nav_items.items():
            if info == target:
                self._nav_tree.selection_set(iid)
                self._nav_tree.see(iid)
                # Expand parent entry if selecting a sub-table
                if table_index is not None:
                    parent_iid = self._nav_tree.parent(iid)
                    if parent_iid:
                        self._nav_tree.item(parent_iid, open=True)
                else:
                    self._nav_tree.item(iid, open=True)
                self._on_nav_select(None)
                found = True
                break

        # Fallback: select entry root if table_index not found
        if not found:
            for iid, info in self._nav_items.items():
                if info == (entry_name, None):
                    self._nav_tree.selection_set(iid)
                    self._nav_tree.item(iid, open=True)
                    self._nav_tree.see(iid)
                    self._on_nav_select(None)
                    break

        if highlight_key and self._current_tree:
            tree = self._current_tree
            cols = tree['columns']
            first_col = cols[0] if cols else None
            if first_col:
                for row_iid in tree.get_children():
                    if tree.set(row_iid, first_col) == highlight_key:
                        tree.item(row_iid, tags=('highlight',))
                        tree.selection_set(row_iid)
                        tree.see(row_iid)
                        tree.focus(row_iid)
                        break
