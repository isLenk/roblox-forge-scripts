"""Wiki data load/save."""

import json
import os

DEFAULT_ENTRIES = {
    "Ores": {
        "url": "https://forge-roblox.fandom.com/wiki/Ores",
        "data": None,
        "extracted_at": None,
    }
}


def _wiki_save_path():
    """Return path to wiki.json next to this script (or in data/ if exists)."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(base, 'data')
    if os.path.isdir(data_dir):
        return os.path.join(data_dir, 'wiki.json')
    # Fallback to project root
    return os.path.join(base, 'wiki.json')


def load_wiki_data():
    """Load wiki data from disk, seeding defaults if missing."""
    path = _wiki_save_path()
    if os.path.exists(path):
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    # Try legacy path at project root
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    legacy = os.path.join(base, 'wiki.json')
    if os.path.exists(legacy) and legacy != path:
        try:
            with open(legacy, 'r') as f:
                return json.load(f)
        except Exception:
            pass
    return {"entries": dict(DEFAULT_ENTRIES)}


def save_wiki_data(data):
    """Write wiki data to disk."""
    try:
        path = _wiki_save_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"[WIKI] Save error: {e}")


def normalize_entry_data(data):
    """Convert flat row list (old format) to table groups (new format)."""
    if not data:
        return data
    if isinstance(data, list) and data:
        if isinstance(data[0], dict) and 'name' in data[0] and 'rows' in data[0]:
            return data
        return [{"name": "All", "rows": data}]
    return data
