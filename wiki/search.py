"""Wiki search functionality."""

from wiki.data import normalize_entry_data


def _parse_query(query):
    """Parse a query string into search terms and column filters.

    Supports comma-separated terms and ``:column`` filters.
    Returns (terms, col_filters) where both are lists of lowercase strings.
    """
    terms = []
    col_filters = []
    for part in query.split(','):
        part = part.strip()
        if not part:
            continue
        if part.startswith(':'):
            col_name = part[1:].strip()
            if col_name:
                col_filters.append(col_name.lower())
        else:
            terms.append(part.lower())
    return terms, col_filters


def search_all_entries(data, query):
    """Search across all cached wiki entries for a query string.

    Supports comma-separated terms (match any) and ``:column`` filters
    to restrict results to tables containing that column.

    Returns list of (entry_name, row_dict, matched_field, matched_value,
    table_index).  Rows with the same first-column value are merged into
    one result (keeps the first table_index encountered).
    """
    if not query:
        return []
    terms, col_filters = _parse_query(query)
    if not terms and not col_filters:
        return []

    raw = []
    for name, entry in data.get('entries', {}).items():
        tables = normalize_entry_data(entry.get('data'))
        if not tables:
            continue
        for ti, table in enumerate(tables):
            rows = table.get('rows', [])
            if not rows:
                continue

            # Column filter: skip tables missing any required column
            if col_filters:
                table_cols = [c.lower() for c in rows[0].keys()]
                if not all(any(cf in tc for tc in table_cols)
                           for cf in col_filters):
                    continue

            # If only column filters and no search terms, return all rows
            if not terms:
                for row in rows:
                    first_val = str(next(iter(row.values()), ''))
                    raw.append((name, row, '', first_val, ti))
                continue

            for row in rows:
                for field, value in row.items():
                    val_lower = str(value).lower()
                    if any(t in val_lower for t in terms):
                        raw.append((name, row, field, str(value), ti))
                        break

    # Merge rows that share the same first-column value
    seen = {}
    results = []
    for entry_name, row, field, value, ti in raw:
        key = str(next(iter(row.values()), ''))
        if key in seen:
            seen[key][1].update(row)
        else:
            merged_row = dict(row)
            item = [entry_name, merged_row, field, value, ti]
            seen[key] = item
            results.append(item)

    return [tuple(r) for r in results]
