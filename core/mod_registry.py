"""Mod registry — discovers and loads game mods from mods.json."""

import json
import os
import importlib


class ModRegistry:
    """Loads the mod manifest and instantiates mod classes."""

    def __init__(self):
        self._manifest = self._load_manifest()

    def _load_manifest(self):
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(base, 'mods.json')
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except Exception:
            return {"schema_version": 1, "mods": []}

    def get_all_mods(self):
        """Return all mod entries from the manifest."""
        return self._manifest.get('mods', [])

    def get_builtin_mods(self):
        """Return only builtin mod entries."""
        return [m for m in self.get_all_mods() if m.get('builtin')]

    def get_mod_for_place(self, place_id):
        """Find a mod entry that handles the given Roblox Place ID."""
        for mod_info in self.get_all_mods():
            if str(place_id) in [str(p) for p in mod_info.get('place_ids', [])]:
                return mod_info
        return None

    def load_mod_class(self, mod_info):
        """Import and return the mod class from its module path."""
        module_path = mod_info['module']
        class_name = mod_info['class']
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
