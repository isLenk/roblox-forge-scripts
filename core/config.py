"""User configuration management."""

import json
import os


def _config_dir():
    """Return the data/ directory path."""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'data')


def _config_path():
    return os.path.join(_config_dir(), 'config.json')


DEFAULT_CONFIG = {
    "installed_mods": ["forge"],
    "hotkeys_enabled": True,
    "global_hotkeys": {
        "autoclicker": "f5",
        "hold_left": "f6",
        "sprint": "caps lock",
    },
    "mods": {
        "forge": {
            "hotkeys": {
                "circle": "p",
                "jiggle": "i",
                "bar_game": "o",
                "auto_phase": "u",
            },
            "auto_sell": {
                "positions": {},
                "interval": 300,
                "camlock": False,
            },
        },
    },
}


class UserConfig:
    """Manages user configuration persisted to data/config.json."""

    def __init__(self):
        self._path = _config_path()
        self._data = dict(DEFAULT_CONFIG)
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, 'r') as f:
                    saved = json.load(f)
                self._deep_merge(self._data, saved)
            except Exception:
                pass
        # Migrate legacy files
        self._migrate_legacy()

    def _migrate_legacy(self):
        """Migrate legacy autosell.json and macros.json into config."""
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Migrate autosell.json
        legacy_as = os.path.join(base, 'autosell.json')
        if os.path.exists(legacy_as):
            try:
                with open(legacy_as, 'r') as f:
                    as_data = json.load(f)
                forge = self._data.setdefault('mods', {}).setdefault(
                    'forge', {})
                auto_sell = forge.setdefault('auto_sell', {})
                if 'positions' in as_data:
                    auto_sell['positions'] = {
                        k: tuple(v)
                        for k, v in as_data['positions'].items()
                    }
                if 'interval' in as_data:
                    auto_sell['interval'] = as_data['interval']
                if 'camlock' in as_data:
                    auto_sell['camlock'] = as_data['camlock']
            except Exception:
                pass

        # Migrate macros.json
        legacy_macros = os.path.join(base, 'macros.json')
        if os.path.exists(legacy_macros):
            try:
                with open(legacy_macros, 'r') as f:
                    macros = json.load(f)
                self._data['macros'] = macros
            except Exception:
                pass

    def _deep_merge(self, base, override):
        """Merge override into base dict recursively."""
        for k, v in override.items():
            if (k in base and isinstance(base[k], dict)
                    and isinstance(v, dict)):
                self._deep_merge(base[k], v)
            else:
                base[k] = v

    def save(self):
        """Persist config to disk."""
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, 'w') as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            print(f"[CONFIG] Save error: {e}")

    def get(self, *keys, default=None):
        """Get a nested config value. e.g. config.get('mods', 'forge', 'hotkeys')"""
        d = self._data
        for k in keys:
            if isinstance(d, dict):
                d = d.get(k)
            else:
                return default
            if d is None:
                return default
        return d

    def set(self, *keys_and_value):
        """Set a nested config value. Last arg is the value."""
        if len(keys_and_value) < 2:
            return
        keys = keys_and_value[:-1]
        value = keys_and_value[-1]
        d = self._data
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value

    @property
    def data(self):
        return self._data
