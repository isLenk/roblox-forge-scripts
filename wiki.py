"""
Wiki Feature
=============
Gemini-powered wiki data extraction from Roblox Forge wiki pages.
Caches structured data locally in wiki.json and provides search.
"""

import json
import os
import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
from threading import Thread
from datetime import datetime
import urllib.request
import urllib.error

# ---- Theme constants (match circle_bot.py) ----
BG = '#0d1117'
BG2 = '#161b22'
BORDER = '#21262d'
DIM = '#484f58'
ACCENT = '#58a6ff'
GREEN = '#50fa7b'
RED = '#ff5555'

DEFAULT_ENTRIES = {
    "Ores": {
        "url": "https://forge-roblox.fandom.com/wiki/Ores",
        "data": None,
        "extracted_at": None,
    }
}


def _wiki_save_path():
    """Return path to wiki.json next to this script."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'wiki.json')


def load_wiki_data():
    """Load wiki data from disk, seeding defaults if missing."""
    path = _wiki_save_path()
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"gemini_api_key": "", "entries": dict(DEFAULT_ENTRIES)}


def save_wiki_data(data):
    """Write wiki data to disk."""
    try:
        with open(_wiki_save_path(), 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[WIKI] Save error: {e}")


_EXTRACT_PROMPT = (
    "Extract ALL tabular/structured data into a JSON array of objects. "
    "Each object is one row. Use the table headers as keys. "
    "Include data from ALL tables/tabs/sections. "
    "Combine all rows into one flat JSON array. "
    "Return ONLY valid JSON, no markdown fences."
)


def _parse_fandom_tables(url):
    """For Fandom wiki URLs, fetch and parse ALL tables into list-of-dicts.

    Uses the MediaWiki API which returns full HTML including hidden tab content.
    Returns list of dicts, or None for non-Fandom URLs / on failure.
    """
    import re
    m = re.match(r'https?://([^/]+\.fandom\.com)/wiki/(.+)', url)
    if not m:
        return None
    domain, page = m.group(1), m.group(2)
    api_url = (
        f'https://{domain}/api.php?action=parse'
        f'&page={urllib.request.quote(page, safe="")}'
        f'&prop=text&format=json'
    )
    try:
        req = urllib.request.Request(api_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        html = data['parse']['text']['*']
    except Exception as e:
        print(f"[WIKI] Fandom API fetch failed: {e}")
        return None

    def _clean(cell_html):
        return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', cell_html)).strip()

    tables = re.findall(r'<table[^>]*>.*?</table>', html, re.DOTALL | re.IGNORECASE)
    if not tables:
        return None

    all_rows = []
    for t in tables:
        tr_list = re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.DOTALL | re.IGNORECASE)
        if not tr_list:
            continue

        # First row with <th> cells is the header
        headers = None
        data_start = 0
        for i, tr in enumerate(tr_list):
            th_cells = re.findall(r'<th[^>]*>(.*?)</th>', tr, re.DOTALL | re.IGNORECASE)
            if th_cells:
                headers = [_clean(c) for c in th_cells]
                data_start = i + 1
                break

        if not headers:
            # No headers found — try using first row as headers
            first_cells = re.findall(r'<td[^>]*>(.*?)</td>', tr_list[0], re.DOTALL | re.IGNORECASE)
            if first_cells:
                headers = [_clean(c) for c in first_cells]
                data_start = 1
            else:
                continue

        # Filter out empty headers (like Image columns)
        for i, tr in enumerate(tr_list[data_start:]):
            cells = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.DOTALL | re.IGNORECASE)
            if not cells:
                continue
            row = {}
            for j, h in enumerate(headers):
                if j < len(cells):
                    val = _clean(cells[j])
                    if h and val:  # skip empty header or empty value
                        row[h] = val
            if row:
                all_rows.append(row)

    print(f"[WIKI] Parsed {len(all_rows)} rows from {len(tables)} tables")
    return all_rows if all_rows else None


def _strip_markdown_fences(text):
    """Remove ```json ... ``` wrappers from LLM output."""
    text = text.strip()
    if text.startswith('```'):
        first_nl = text.index('\n')
        text = text[first_nl + 1:]
    if text.endswith('```'):
        text = text[:-3]
    return text.strip()


def _llm_request_with_retry(req_builder, label):
    """Fire an HTTP request with retry on 429. req_builder() returns a new Request."""
    import time as _time
    for attempt in range(4):
        try:
            req = req_builder()
            print(f"[WIKI] {label} request -> {req.full_url[:80]}  (attempt {attempt + 1}, body {len(req.data)} bytes)")
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode('utf-8')
                print(f"[WIKI] {label} response: {resp.status} ({len(raw)} bytes)")
                return json.loads(raw)
        except urllib.error.HTTPError as e:
            body = ''
            try:
                body = e.read().decode('utf-8', errors='replace')[:500]
            except Exception:
                pass
            print(f"[WIKI] {label} HTTP {e.code}: {e.reason}\n{body}")
            if e.code == 429 and attempt < 3:
                wait = (attempt + 1) * 10
                print(f"[WIKI] {label} retrying in {wait}s...")
                _time.sleep(wait)
            else:
                raise
        except Exception as e:
            print(f"[WIKI] {label} error: {type(e).__name__}: {e}")
            raise


def _extract_gemini(api_key, url):
    """Call Gemini API with URL context — Gemini fetches the page itself."""
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.0-flash:generateContent?key={api_key}"
    )
    body = json.dumps({
        "contents": [{"parts": [{"text": f"{_EXTRACT_PROMPT}\n\nURL: {url}"}]}],
        "tools": [{"url_context": {}}],
        "generationConfig": {"maxOutputTokens": 65536},
    }).encode('utf-8')

    def build_req():
        return urllib.request.Request(
            endpoint, data=body,
            headers={'Content-Type': 'application/json'}, method='POST')

    result = _llm_request_with_retry(build_req, 'Gemini')
    print(f"[WIKI] Gemini raw response:\n{json.dumps(result, indent=2)[:3000]}")
    try:
        text = result['candidates'][0]['content']['parts'][0]['text']
    except (KeyError, IndexError) as e:
        print(f"[WIKI] Unexpected response structure: {e}")
        raise ValueError(f"Gemini returned unexpected response: {json.dumps(result)[:500]}")
    print(f"[WIKI] Gemini text output:\n{text[:2000]}")
    return _strip_markdown_fences(text)


def _extract_openai(api_key, url):
    """Call OpenAI Responses API with web search — model fetches the page itself."""
    endpoint = "https://api.openai.com/v1/responses"
    body = json.dumps({
        "model": "gpt-4o-mini",
        "input": f"{_EXTRACT_PROMPT}\n\nURL: {url}",
        "tools": [{"type": "web_search_preview"}],
        "max_output_tokens": 16384,
    }).encode('utf-8')

    def build_req():
        return urllib.request.Request(
            endpoint, data=body,
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
            }, method='POST')

    result = _llm_request_with_retry(build_req, 'OpenAI')
    print(f"[WIKI] OpenAI raw response:\n{json.dumps(result, indent=2)[:3000]}")
    # Extract text from the response output items
    try:
        text = ''
        for item in result.get('output', []):
            if item.get('type') == 'message':
                for content in item.get('content', []):
                    if content.get('type') == 'output_text':
                        text = content['text']
                        break
                if text:
                    break
        if not text:
            raise KeyError('No output_text found')
    except (KeyError, IndexError) as e:
        print(f"[WIKI] Unexpected response structure: {e}")
        raise ValueError(f"OpenAI returned unexpected response: {json.dumps(result)[:500]}")
    print(f"[WIKI] OpenAI text output:\n{text[:2000]}")
    return _strip_markdown_fences(text)


def _parse_truncated_json(text):
    """Try to parse JSON, recovering partial arrays if truncated."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try to salvage a truncated JSON array by closing it
    # Find the last complete object (ends with })
    last_brace = text.rfind('}')
    if last_brace > 0:
        truncated = text[:last_brace + 1].rstrip().rstrip(',') + ']'
        try:
            result = json.loads(truncated)
            print(f"[WIKI] Recovered truncated JSON ({len(result)} rows)")
            return result
        except json.JSONDecodeError:
            pass
    raise json.JSONDecodeError("Could not parse or recover JSON", text, 0)


def extract_with_llm(provider, api_key, url):
    """Extract structured data from a wiki URL.

    For Fandom wikis: parses HTML tables directly (instant, no API key needed).
    For other URLs: falls back to LLM with web search.
    """
    # Try direct HTML parsing first (Fandom wikis)
    rows = _parse_fandom_tables(url)
    if rows:
        print(f"[WIKI] Direct parse succeeded — {len(rows)} rows, no LLM needed")
        return rows

    # Fallback: LLM with web search
    print(f"[WIKI] Falling back to {provider} LLM for: {url}")
    if provider == 'openai':
        text = _extract_openai(api_key, url)
    else:
        text = _extract_gemini(api_key, url)

    return _parse_truncated_json(text)


def search_all_entries(data, query):
    """Search across all cached wiki entries for a query string.

    Returns list of (entry_name, row_dict, matched_field, matched_value).
    """
    if not query:
        return []
    q = query.lower()
    results = []
    for name, entry in data.get('entries', {}).items():
        rows = entry.get('data')
        if not rows:
            continue
        for row in rows:
            for field, value in row.items():
                if q in str(value).lower():
                    results.append((name, row, field, str(value)))
                    break  # one match per row is enough
    return results


# ================================================================
#  WikiWindow — Toplevel panel
# ================================================================

class WikiWindow:
    def __init__(self, root, data=None):
        self.root = root
        self.data = data if data else load_wiki_data()
        self._build()

    def destroy(self):
        try:
            self.panel.destroy()
        except Exception:
            pass

    # ---- Build the window ----
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
        self.panel = panel

        # ---- Dotted background (tiled via configure, not fixed image) ----
        panel.configure(bg=BG)
        # Use a frame as background to avoid fixed-size image issues on resize
        bg_frame = tk.Frame(panel, bg=BG)
        bg_frame.place(x=0, y=0, relwidth=1, relheight=1)

        # ---- Custom title bar ----
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

        # Dragging
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

        # ---- Search bar ----
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

        # ---- Main body (left + right) ----
        body = tk.Frame(panel, bg=BG)
        body.pack(fill='both', expand=True, padx=10, pady=(0, 4))

        # Left panel
        left = tk.Frame(body, bg=BG2, width=200)
        left.pack(side=tk.LEFT, fill='y', padx=(0, 6))
        left.pack_propagate(False)

        self._entry_listbox = tk.Listbox(
            left, font=('Consolas', 10), fg='#c9d1d9', bg=BG2,
            selectbackground='#1f6feb', selectforeground='#ffffff',
            bd=0, highlightthickness=0, activestyle='none')
        self._entry_listbox.pack(fill='both', expand=True, padx=4, pady=(4, 0))
        self._entry_listbox.bind('<<ListboxSelect>>', self._on_entry_select)
        self._entry_listbox.bind('<Delete>', self._delete_selected_entry)

        # Add entry button
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

        # Provider + API key section
        provider_frame = tk.Frame(left, bg=BORDER)
        provider_frame.pack(fill='x', padx=4, pady=(0, 2))

        self._provider = self.data.get('provider', 'gemini')
        self._provider_btn = tk.Label(
            provider_frame,
            text=self._provider.upper(),
            font=('Consolas', 8, 'bold'),
            fg=GREEN if self._provider == 'gemini' else '#f0c040',
            bg=BG2, padx=4, pady=2, cursor='hand2')
        self._provider_btn.pack(side=tk.LEFT, padx=(2, 2), pady=2)
        self._provider_btn.bind('<Button-1>', lambda e: self._cycle_provider())

        tk.Label(provider_frame, text='\u25C0\u25B6', font=('Consolas', 7),
                 fg=DIM, bg=BORDER).pack(side=tk.LEFT)

        key_frame = tk.Frame(left, bg=BORDER)
        key_frame.pack(fill='x', padx=4, pady=(0, 4))
        tk.Label(key_frame, text='Key:', font=('Consolas', 8),
                 fg=DIM, bg=BORDER).pack(side=tk.LEFT, padx=(4, 2))

        self._api_key_var = tk.StringVar(
            value=self.data.get(f'{self._provider}_api_key', ''))
        api_entry = tk.Entry(
            key_frame, textvariable=self._api_key_var, show='*',
            font=('Consolas', 9), fg=ACCENT, bg=BG2,
            insertbackground=ACCENT, bd=0, relief='flat', width=14)
        api_entry.pack(side=tk.LEFT, fill='x', expand=True, padx=2, pady=2)
        self._api_key_var.trace_add('write', self._on_api_key_changed)

        # Right panel
        right = tk.Frame(body, bg=BG)
        right.pack(side=tk.LEFT, fill='both', expand=True)

        # Header row
        header_row = tk.Frame(right, bg=BG)
        header_row.pack(fill='x', pady=(0, 4))

        self._entry_name_lbl = tk.Label(
            header_row, text='Select an entry',
            font=('Consolas', 11, 'bold'), fg='#c9d1d9', bg=BG,
            anchor='w')
        self._entry_name_lbl.pack(side=tk.LEFT, fill='x', expand=True)

        self._regen_btn = tk.Button(
            header_row, text='\u21BB Regen', font=('Consolas', 9, 'bold'),
            fg=ACCENT, bg=BORDER, activebackground='#30363d',
            activeforeground=ACCENT, bd=0, relief='flat', padx=6, pady=1,
            command=self._regenerate_entry)
        self._regen_btn.pack(side=tk.RIGHT)

        # URL row
        url_row = tk.Frame(right, bg=BG)
        url_row.pack(fill='x', pady=(0, 4))
        tk.Label(url_row, text='URL:', font=('Consolas', 9),
                 fg=DIM, bg=BG).pack(side=tk.LEFT)
        self._url_var = tk.StringVar()
        self._url_entry = tk.Entry(
            url_row, textvariable=self._url_var,
            font=('Consolas', 9), fg=ACCENT, bg=BG2,
            insertbackground=ACCENT, bd=0, relief='flat',
            state='readonly')
        self._url_entry.pack(side=tk.LEFT, fill='x', expand=True, padx=(4, 0))

        # Status label (loading/error)
        self._status_lbl = tk.Label(
            right, text='', font=('Consolas', 9), fg=DIM, bg=BG, anchor='w')
        self._status_lbl.pack(fill='x')

        # Data table
        table_frame = tk.Frame(right, bg=BG)
        table_frame.pack(fill='both', expand=True)

        # Style for treeview
        style = ttk.Style(panel)
        style.theme_use('clam')
        ROW_ALT = '#131921'
        style.configure("Wiki.Treeview",
                         background=BG2, foreground='#c9d1d9',
                         fieldbackground=BG2, borderwidth=0,
                         rowheight=26,
                         font=('Consolas', 9))
        style.configure("Wiki.Treeview.Heading",
                         background='#1a2233', foreground=ACCENT,
                         font=('Consolas', 9, 'bold'), borderwidth=0,
                         padding=(8, 4))
        style.map("Wiki.Treeview.Heading",
                  background=[('active', '#1f2d44')])
        style.map("Wiki.Treeview",
                  background=[('selected', '#1f6feb')],
                  foreground=[('selected', '#ffffff')])
        # Scrollbar styling
        style.configure("Wiki.Vertical.TScrollbar",
                         background=BORDER, troughcolor=BG2,
                         borderwidth=0, arrowsize=0, width=10)
        style.map("Wiki.Vertical.TScrollbar",
                  background=[('active', '#30363d'), ('!active', BORDER)])
        style.configure("Wiki.Horizontal.TScrollbar",
                         background=BORDER, troughcolor=BG2,
                         borderwidth=0, arrowsize=0, width=10)
        style.map("Wiki.Horizontal.TScrollbar",
                  background=[('active', '#30363d'), ('!active', BORDER)])

        self._tree = ttk.Treeview(
            table_frame, columns=('placeholder',), show='headings',
            style='Wiki.Treeview', height=12, selectmode='browse')
        self._tree.heading('placeholder', text='Data')
        self._tree.column('placeholder', width=400)
        self._row_alt_color = ROW_ALT
        self._tree.tag_configure('oddrow', background=ROW_ALT)
        self._tree.tag_configure('evenrow', background=BG2)

        y_scroll = ttk.Scrollbar(table_frame, orient='vertical',
                                  command=self._tree.yview,
                                  style='Wiki.Vertical.TScrollbar')
        x_scroll = ttk.Scrollbar(table_frame, orient='horizontal',
                                  command=self._tree.xview,
                                  style='Wiki.Horizontal.TScrollbar')
        self._tree.configure(yscrollcommand=y_scroll.set,
                              xscrollcommand=x_scroll.set)
        x_scroll.pack(side=tk.BOTTOM, fill='x')
        self._tree.pack(side=tk.LEFT, fill='both', expand=True)
        y_scroll.pack(side=tk.RIGHT, fill='y')

        self._selected_entry = None
        self._refresh_entry_list()

        # If there's only one entry, auto-select it
        entries = self.data.get('entries', {})
        if len(entries) == 1:
            self._entry_listbox.selection_set(0)
            self._on_entry_select(None)

        # ---- Resize grip (bottom-right corner) ----
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

    # ---- Close handler ----
    def _on_close(self):
        self._save()
        self.panel.destroy()

    # ---- Save ----
    def _save(self):
        self.data['provider'] = self._provider
        self.data[f'{self._provider}_api_key'] = self._api_key_var.get()
        save_wiki_data(self.data)

    # ---- Search placeholder ----
    def _on_search_focus_in(self, event):
        if self._search_entry.get() == 'Search all entries...':
            self._search_entry.delete(0, tk.END)
            self._search_entry.config(fg='#c9d1d9')

    def _on_search_focus_out(self, event):
        if not self._search_entry.get():
            self._search_entry.insert(0, 'Search all entries...')
            self._search_entry.config(fg=DIM)

    # ---- Search logic ----
    def _on_search_changed(self, *_):
        query = self._search_var.get()
        if query == 'Search all entries...' or not query:
            self._refresh_entry_list()
            self._clear_table()
            self._status_lbl.config(text='', fg=DIM)
            return

        results = search_all_entries(self.data, query)

        # Also match entry names themselves
        q = query.lower()
        name_matches = [n for n in self.data.get('entries', {})
                        if q in n.lower()]

        if not results and not name_matches:
            self._clear_table()
            self._status_lbl.config(text='No results found', fg=RED)
            return

        # Combine: entries matched by name + entries matched by content
        matched_names = list(dict.fromkeys(
            name_matches + [r[0] for r in results]))
        self._entry_listbox.delete(0, tk.END)
        for name in matched_names:
            self._entry_listbox.insert(tk.END, name)

        # Show matched rows in the table
        matched_rows = [r[1] for r in results]
        if matched_rows:
            self._populate_table(matched_rows)
            self._status_lbl.config(
                text=f'{len(matched_rows)} matching row(s)', fg=GREEN)
        elif name_matches:
            # Name matched but no row-level match — show first matched entry's data
            entry = self.data['entries'].get(name_matches[0])
            if entry and entry.get('data'):
                self._populate_table(entry['data'])
                self._status_lbl.config(
                    text=f'Showing "{name_matches[0]}"', fg=ACCENT)
            else:
                self._clear_table()
                self._status_lbl.config(
                    text=f'Entry "{name_matches[0]}" (no data)', fg=DIM)

    # ---- Provider toggle ----
    def _cycle_provider(self):
        # Save current key before switching
        self.data[f'{self._provider}_api_key'] = self._api_key_var.get()
        self._provider = 'openai' if self._provider == 'gemini' else 'gemini'
        self.data['provider'] = self._provider
        # Update button label + color
        self._provider_btn.config(
            text=self._provider.upper(),
            fg=GREEN if self._provider == 'gemini' else '#f0c040')
        # Load the other provider's key
        self._api_key_var.set(self.data.get(f'{self._provider}_api_key', ''))

    # ---- API key changed ----
    def _on_api_key_changed(self, *_):
        self.data[f'{self._provider}_api_key'] = self._api_key_var.get()

    # ---- Entry list ----
    def _refresh_entry_list(self):
        self._entry_listbox.delete(0, tk.END)
        for name in self.data.get('entries', {}):
            self._entry_listbox.insert(tk.END, name)

    def _on_entry_select(self, event):
        sel = self._entry_listbox.curselection()
        if not sel:
            return
        name = self._entry_listbox.get(sel[0])
        self._selected_entry = name
        entry = self.data.get('entries', {}).get(name)
        if not entry:
            return

        self._entry_name_lbl.config(text=f'Entry: "{name}"')
        self._url_entry.config(state='normal')
        self._url_var.set(entry.get('url', ''))
        self._url_entry.config(state='readonly')

        rows = entry.get('data')
        if rows:
            self._populate_table(rows)
            ts = entry.get('extracted_at', '')
            self._status_lbl.config(
                text=f'{len(rows)} row(s)  |  Extracted: {ts}', fg=DIM)
        else:
            self._clear_table()
            self._status_lbl.config(
                text='No data yet \u2014 click Regen to extract', fg=DIM)

    # ---- Table ----
    def _populate_table(self, rows):
        """Populate the treeview with a list of row dicts."""
        # Clear existing
        for item in self._tree.get_children():
            self._tree.delete(item)

        if not rows:
            return

        # Build columns from the first row's keys (skip empty-only columns like Image)
        all_cols = list(rows[0].keys())
        cols = [c for c in all_cols
                if any(str(row.get(c, '')).strip() for row in rows[:20])]
        if not cols:
            cols = all_cols
        self._tree['columns'] = cols
        for col in cols:
            self._tree.heading(col, text=col)
            # Auto-size: use max of header length and first few values
            max_w = len(col) * 9
            for row in rows[:20]:
                val_w = len(str(row.get(col, ''))) * 8
                if val_w > max_w:
                    max_w = val_w
            self._tree.column(col, width=min(max_w + 16, 250), anchor='w')

        for i, row in enumerate(rows):
            vals = [str(row.get(c, '')) for c in cols]
            tag = 'oddrow' if i % 2 else 'evenrow'
            self._tree.insert('', tk.END, values=vals, tags=(tag,))

    def _clear_table(self):
        for item in self._tree.get_children():
            self._tree.delete(item)

    # ---- Add entry ----
    def _add_entry(self):
        name = simpledialog.askstring(
            "New Wiki Entry", "Entry name:",
            parent=self.panel)
        if not name or not name.strip():
            return
        name = name.strip()
        if name in self.data.get('entries', {}):
            messagebox.showwarning("Duplicate", f'"{name}" already exists.',
                                    parent=self.panel)
            return

        url = simpledialog.askstring(
            "Wiki URL", f'URL for "{name}":',
            parent=self.panel)
        if not url or not url.strip():
            return

        self.data.setdefault('entries', {})[name] = {
            "url": url.strip(),
            "data": None,
            "extracted_at": None,
        }
        self._save()
        self._refresh_entry_list()

        # Select the new entry
        names = list(self.data['entries'].keys())
        idx = names.index(name)
        self._entry_listbox.selection_clear(0, tk.END)
        self._entry_listbox.selection_set(idx)
        self._on_entry_select(None)

    # ---- Delete entry ----
    def _delete_selected_entry(self, event=None):
        sel = self._entry_listbox.curselection()
        if not sel:
            return
        name = self._entry_listbox.get(sel[0])
        if not messagebox.askyesno(
                "Delete Entry",
                f'Delete "{name}" and its cached data?',
                parent=self.panel):
            return
        self.data.get('entries', {}).pop(name, None)
        self._save()
        self._refresh_entry_list()
        self._selected_entry = None
        self._entry_name_lbl.config(text='Select an entry')
        self._url_entry.config(state='normal')
        self._url_var.set('')
        self._url_entry.config(state='readonly')
        self._clear_table()
        self._status_lbl.config(text='', fg=DIM)

    # ---- Regenerate (extract) ----
    def _regenerate_entry(self):
        if not self._selected_entry:
            self._status_lbl.config(text='No entry selected', fg=RED)
            return
        api_key = self._api_key_var.get().strip()
        if not api_key:
            self._status_lbl.config(text='Enter a Gemini API key first', fg=RED)
            return

        name = self._selected_entry
        entry = self.data.get('entries', {}).get(name)
        if not entry:
            return
        url = entry.get('url', '')
        if not url:
            self._status_lbl.config(text='No URL set for this entry', fg=RED)
            return

        provider = self._provider
        self._status_lbl.config(text=f'Sending to {provider.upper()}...', fg=ACCENT)
        self._regen_btn.config(state='disabled')

        def _worker():
            try:
                rows = extract_with_llm(provider, api_key, url)
                entry['data'] = rows
                entry['extracted_at'] = datetime.now().isoformat(
                    timespec='seconds')
                self.data[f'{provider}_api_key'] = api_key
                save_wiki_data(self.data)
                self.panel.after(0, lambda: self._on_extract_done(name, rows))
            except Exception as e:
                import traceback
                traceback.print_exc()
                msg = f'{type(e).__name__}: {e}' if str(e) else type(e).__name__
                self.panel.after(0, lambda m=msg: self._on_extract_error(m))

        Thread(target=_worker, daemon=True).start()

    def _on_extract_done(self, name, rows):
        self._regen_btn.config(state='normal')
        if self._selected_entry == name:
            self._populate_table(rows)
            ts = self.data['entries'][name].get('extracted_at', '')
            self._status_lbl.config(
                text=f'{len(rows)} row(s) extracted  |  {ts}', fg=GREEN)

    def _on_extract_error(self, msg):
        self._regen_btn.config(state='normal')
        self._status_lbl.config(text=f'Error: {msg}', fg=RED)

    # ---- Navigate to entry by name (used from radial search) ----
    def navigate_to(self, entry_name):
        """Select and display a specific entry by name."""
        names = list(self.data.get('entries', {}).keys())
        if entry_name not in names:
            return
        idx = names.index(entry_name)
        self._entry_listbox.selection_clear(0, tk.END)
        self._entry_listbox.selection_set(idx)
        self._entry_listbox.see(idx)
        self._on_entry_select(None)


# ================================================================
#  Radial Wiki Search — floating search overlay
# ================================================================

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
        w, h = 480, 44
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

        # Outer glow border (2px accent)
        inner = tk.Frame(self.win, bg=BG)
        inner.pack(fill='both', expand=True, padx=2, pady=2)

        # Icon + entry
        row = tk.Frame(inner, bg=BG)
        row.pack(fill='both', expand=True)

        tk.Label(row, text='\U0001f50d', font=('Segoe UI Emoji', 13),
                 fg=DIM, bg=BG).pack(side=tk.LEFT, padx=(10, 0))

        self._search_var = tk.StringVar()
        self._entry = tk.Entry(
            row, textvariable=self._search_var,
            font=('Consolas', 13), fg='#e6edf3', bg=BG,
            insertbackground=ACCENT, bd=0, relief='flat')
        self._entry.pack(side=tk.LEFT, fill='both', expand=True, padx=(6, 10))
        self._entry.focus_force()

        # Placeholder
        self._placeholder_on = True
        self._entry.insert(0, 'Search wiki...')
        self._entry.config(fg=DIM)
        self._entry.bind('<FocusIn>', self._on_entry_focus)

        self._search_var.trace_add('write', self._on_type)
        self._entry.bind('<Escape>', lambda e: self.close())
        self._entry.bind('<Return>', self._on_enter)
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
        y = self._win_y + 46
        w = self._win_w
        n = min(len(self._results), 8)
        item_h = 32
        h = n * item_h + 4

        dd = tk.Toplevel(self.root)
        dd.overrideredirect(True)
        dd.attributes('-topmost', True)
        dd.attributes('-alpha', 0.97)
        dd.configure(bg='#1f6feb')
        dd.geometry(f'{w}x{h}+{x}+{y}')

        inner = tk.Frame(dd, bg=BG)
        inner.pack(fill='both', expand=True, padx=2, pady=2)

        self._dropdown_items = []
        for i, (entry_name, row, field, value) in enumerate(self._results[:8]):
            item = tk.Frame(inner, bg=BG, cursor='hand2')
            item.pack(fill='x')

            # Entry name in accent, field:value in dim
            name_lbl = tk.Label(
                item, text=entry_name,
                font=('Consolas', 9, 'bold'), fg=ACCENT, bg=BG,
                anchor='w')
            name_lbl.pack(side=tk.LEFT, padx=(10, 4))

            detail_lbl = tk.Label(
                item, text=f'{field}: {value}',
                font=('Consolas', 9), fg='#8b949e', bg=BG,
                anchor='w')
            detail_lbl.pack(side=tk.LEFT, fill='x', expand=True, padx=(0, 10))

            # Pad the row height
            item.configure(height=item_h)
            item.pack_propagate(False)

            # Hover + click bindings
            widgets = [item, name_lbl, detail_lbl]
            for widget in widgets:
                widget.bind('<Enter>',
                            lambda e, idx=i: self._on_item_hover(idx))
                widget.bind('<Button-1>',
                            lambda e, idx=i: self._on_item_click(idx))

            self._dropdown_items.append({
                'frame': item, 'name': name_lbl, 'detail': detail_lbl})

        dd.bind('<Escape>', lambda e: self.close())
        self._dropdown = dd

    def _on_item_hover(self, idx):
        """Highlight hovered item and show preview tooltip."""
        if idx == self._hovered_idx:
            return
        # Un-highlight previous
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
            # Show tooltip for this item
            self._show_result_tooltip(idx)

    def _on_item_click(self, idx):
        if 0 <= idx < len(self._results):
            entry_name = self._results[idx][0]
            self._open_in_wiki(entry_name)

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
        if self._hovered_idx >= 0 and self._hovered_idx < len(self._results):
            entry_name = self._results[self._hovered_idx][0]
            self._open_in_wiki(entry_name)
        elif self._results:
            self._on_item_hover(0)

    def _show_result_tooltip(self, idx):
        if idx >= len(self._results):
            return
        entry_name, row, _, _ = self._results[idx]
        self._close_tooltip()

        # Position to the right of the search bar
        tip_x = self._win_x + self._win_w + 10
        tip_y = self._win_y
        tip_w = 300
        # Filter out empty values for display
        items = [(k, v) for k, v in row.items() if str(v).strip()]
        tip_h = len(items) * 22 + 44

        tip = tk.Toplevel(self.root)
        tip.overrideredirect(True)
        tip.attributes('-topmost', True)
        tip.attributes('-alpha', 0.97)
        tip.configure(bg='#1f6feb')
        tip.geometry(f'{tip_w}x{tip_h}+{tip_x}+{tip_y}')

        inner = tk.Frame(tip, bg=BG)
        inner.pack(fill='both', expand=True, padx=2, pady=2)

        # Header
        hdr = tk.Frame(inner, bg='#1a2233')
        hdr.pack(fill='x')
        tk.Label(hdr, text=entry_name,
                 font=('Consolas', 10, 'bold'), fg=ACCENT, bg='#1a2233',
                 anchor='w').pack(fill='x', padx=8, pady=(4, 4))

        # Key-value pairs with alternating rows
        for i, (k, v) in enumerate(items):
            rbg = '#131921' if i % 2 else BG
            row_f = tk.Frame(inner, bg=rbg)
            row_f.pack(fill='x')
            tk.Label(row_f, text=k, font=('Consolas', 8, 'bold'),
                     fg=DIM, bg=rbg, anchor='w', width=12).pack(
                         side=tk.LEFT, padx=(8, 4), pady=1)
            tk.Label(row_f, text=str(v), font=('Consolas', 9),
                     fg='#e6edf3', bg=rbg, anchor='w').pack(
                         side=tk.LEFT, padx=(0, 8), pady=1)

        # "Open in Wiki" link
        link_f = tk.Frame(inner, bg=BG)
        link_f.pack(fill='x')
        link = tk.Label(
            link_f, text='\u25B6  Open in Wiki',
            font=('Consolas', 9, 'bold'), fg=GREEN, bg=BG,
            cursor='hand2', anchor='w')
        link.pack(padx=8, pady=(4, 4))
        link.bind('<Button-1>',
                  lambda e, n=entry_name: self._open_in_wiki(n))
        link.bind('<Enter>', lambda e: link.config(fg='#70ffab'))
        link.bind('<Leave>', lambda e: link.config(fg=GREEN))

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

    def _open_in_wiki(self, entry_name):
        self.close()
        self._open_wiki(entry_name)
