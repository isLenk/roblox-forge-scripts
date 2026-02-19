"""LENK.TOOLS — Roblox game hub entry point."""

import ctypes
import sys

# Fix DPI scaling on Windows so screen coords match pixel coords
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def main():
    dev_mode = '--dev' in sys.argv

    if not dev_mode:
        from updater import run_update_check
        run_update_check()

    from core.hub import GameHub
    from core.mod_registry import ModRegistry

    hub = GameHub()
    registry = ModRegistry()

    # Auto-activate installed builtin mods
    installed = hub.config.get('installed_mods', default=[])
    for mod_info in registry.get_builtin_mods():
        if mod_info['id'] in installed:
            mod_cls = registry.load_mod_class(mod_info)
            mod = mod_cls(hub)
            hub.activate_mod(mod)

    hub.run()


if __name__ == '__main__':
    main()
