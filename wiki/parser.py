"""Fandom HTML table parser."""

import json
import re
import urllib.request


def _clean_html(cell_html):
    """Strip HTML tags and collapse whitespace."""
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', cell_html)).strip()


def _parse_single_table(table_html):
    """Parse a single <table> HTML string into a list of row dicts."""
    tr_list = re.findall(
        r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL | re.IGNORECASE)
    if not tr_list:
        return []

    headers = None
    data_start = 0
    for i, tr in enumerate(tr_list):
        th_cells = re.findall(
            r'<th[^>]*>(.*?)</th>', tr, re.DOTALL | re.IGNORECASE)
        if th_cells:
            headers = [_clean_html(c) for c in th_cells]
            data_start = i + 1
            break

    if not headers:
        first_cells = re.findall(
            r'<td[^>]*>(.*?)</td>', tr_list[0], re.DOTALL | re.IGNORECASE)
        if first_cells:
            headers = [_clean_html(c) for c in first_cells]
            data_start = 1
        else:
            return []

    rows = []
    for tr in tr_list[data_start:]:
        cells = re.findall(
            r'<td[^>]*>(.*?)</td>', tr, re.DOTALL | re.IGNORECASE)
        if not cells:
            continue
        row = {}
        for j, h in enumerate(headers):
            if j < len(cells):
                val = _clean_html(cells[j])
                if h and val:
                    row[h] = val
        if row:
            rows.append(row)
    return rows


def _parse_fandom_tables(url):
    """For Fandom wiki URLs, fetch and parse tables grouped by tab labels."""
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
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36'),
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        html = data['parse']['text']['*']
    except Exception as e:
        print(f"[WIKI] Fandom API fetch failed: {e}")
        return None

    tokens = []
    for m2 in re.finditer(
            r'<h2[^>]*>(.*?)</h2>', html, re.DOTALL | re.IGNORECASE):
        tokens.append(('heading', m2.start(), _clean_html(m2.group(1))))
    for m2 in re.finditer(
            r'<div[^>]*class="[^"]*tabber wds-tabber[^"]*"', html):
        tokens.append(('tabber_open', m2.start(), None))
    for m2 in re.finditer(r'data-hash="([^"]+)"', html):
        tokens.append((
            'tab_label', m2.start(), m2.group(1).replace('_', ' ')))
    for m2 in re.finditer(
            r'<div[^>]*class="[^"]*wds-tab__content[^"]*"', html):
        tokens.append(('tab_content', m2.start(), None))
    for m2 in re.finditer(
            r'<table[^>]*>.*?</table>', html, re.DOTALL | re.IGNORECASE):
        tokens.append(('table', m2.start(), m2.group(0)))
    tokens.sort(key=lambda t: t[1])

    tabber_stack = []
    current_heading = ''
    current_label = ''
    result = []

    for token_type, _pos, value in tokens:
        if token_type == 'heading':
            current_heading = value
        elif token_type == 'tabber_open':
            tabber_stack.append({'labels': [], 'idx': 0})
        elif token_type == 'tab_label':
            if tabber_stack:
                tabber_stack[-1]['labels'].append(value)
        elif token_type == 'tab_content':
            while (tabber_stack and
                   tabber_stack[-1]['idx'] >= len(
                       tabber_stack[-1]['labels'])):
                tabber_stack.pop()
            if tabber_stack:
                tabber = tabber_stack[-1]
                current_label = tabber['labels'][tabber['idx']]
                tabber['idx'] += 1
            else:
                current_label = ''
        elif token_type == 'table':
            rows = _parse_single_table(value)
            if rows:
                label = (current_label or current_heading
                         or f'Table {len(result) + 1}')
                result.append({
                    'name': label,
                    '_section': current_heading,
                    'rows': rows,
                })

    # Disambiguate duplicate names across sections
    label_sections = {}
    for table in result:
        name = table['name']
        section = table.get('_section', '')
        if name not in label_sections:
            label_sections[name] = set()
        label_sections[name].add(section)

    for table in result:
        name = table['name']
        section = table.pop('_section', '')
        if len(label_sections.get(name, set())) > 1 and section:
            table['name'] = f'{section}: {name}'

    total_rows = sum(len(t['rows']) for t in result)
    print(f"[WIKI] Parsed {total_rows} rows across {len(result)} tables")
    return result if result else None


def extract_wiki_data(url):
    """Extract structured data from a wiki URL."""
    tables = _parse_fandom_tables(url)
    if tables:
        return tables
    print(f"[WIKI] No tables found for: {url}")
    return None
