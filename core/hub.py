"""Game Hub — main application controller."""

import tkinter as tk
from threading import Thread

from version import VERSION
from core.input import InputManager
from core.focus import RobloxFocus
from core.monitor import MonitorManager
from core.config import UserConfig
from core.hotkeys import HotkeyManager
from core.radial import RadialMenu
from core.mini_mode import MiniMode


class GameHub:
    """Central hub that owns shared services and manages game mods."""

    def __init__(self):
        self.running = True

        # Tk root (hidden — mods create their own Toplevel windows)
        self.root = tk.Tk()
        self.root.withdraw()

        # Shared services
        self.input = InputManager()
        self.focus = RobloxFocus()
        self.monitors = MonitorManager()
        self.config = UserConfig()
        self.hotkeys = HotkeyManager()

        # Mini mode
        self.mini_mode = MiniMode(self.root, self._restore_from_mini)

        # Active mod
        self._active_mod = None
        self._wiki_panel = None
        self._wiki_search = None

        # Radial menu (populated when a mod activates)
        self.radial = None

    # ---- Mod lifecycle ----

    def activate_mod(self, mod):
        """Activate a game mod — init, build GUI, register hotkeys, start."""
        self._active_mod = mod
        mod.init()
        mod.build_gui(self.root)
        self._register_mod_hotkeys(mod)
        self._setup_radial(mod)
        mod.start()

        # Start radial polling
        self._poll_radial()

    def _register_mod_hotkeys(self, mod):
        """Register hotkeys for the active mod."""
        from mods.forge.mod import ForgeMod
        if not isinstance(mod, ForgeMod):
            return

        config_hotkeys = self.config.get(
            'mods', 'forge', 'hotkeys', default={})
        global_hotkeys = self.config.get('global_hotkeys', default={})

        def _guarded(callback):
            """Wrap callback so it checks hotkeys.enabled first."""
            def wrapper(event=None):
                if not self.hotkeys.enabled:
                    return
                callback()
            return wrapper

        self.hotkeys.register(
            'circle',
            config_hotkeys.get('circle', 'p'),
            _guarded(lambda: mod._on_node_click(3)))
        self.hotkeys.register(
            'jiggle',
            config_hotkeys.get('jiggle', 'i'),
            _guarded(lambda: mod._on_node_click(0)))
        self.hotkeys.register(
            'bar_game',
            config_hotkeys.get('bar_game', 'o'),
            _guarded(lambda: mod._on_node_click(1)))
        self.hotkeys.register(
            'auto_phase',
            config_hotkeys.get('auto_phase', 'u'),
            _guarded(lambda: mod.toggle_auto_phase()))
        self.hotkeys.register(
            'autoclicker',
            global_hotkeys.get('autoclicker', 'f5'),
            _guarded(lambda: mod._toggle_autoclicker()))
        self.hotkeys.register(
            'hold_left',
            global_hotkeys.get('hold_left', 'f6'),
            _guarded(lambda: mod._toggle_hold_left()))
        self.hotkeys.register(
            'sprint',
            global_hotkeys.get('sprint', 'caps lock'),
            _guarded(lambda: mod._toggle_sprint()))
        self.hotkeys.register(
            'enter_phase',
            'enter',
            _guarded(lambda: mod._handle_enter()))

    def _setup_radial(self, mod):
        """Set up radial menu items for the active mod."""
        from mods.forge.mod import ForgeMod
        if not isinstance(mod, ForgeMod):
            return

        items = [
            {'label': 'Autoclicker',
             'icon': '\u2b50',
             'toggle': lambda: mod._toggle_autoclicker(force=True),
             'state': lambda: mod.autoclicker.active},
            {'label': 'Sprint',
             'icon': '\U0001f3c3',
             'toggle': lambda: mod._toggle_sprint(force=True),
             'state': lambda: mod.sprint.active},
            {'label': 'Mini UI',
             'icon': '\u2500',
             'toggle': lambda: self._minimize(),
             'state': lambda: self.mini_mode.is_active},
            {'label': 'Forge',
             'icon': '\U0001f525',
             'toggle': lambda: mod._toggle_forge(),
             'state': lambda: mod.forge_enabled},
            {'label': 'Wiki',
             'icon': '\U0001f4d6',
             'toggle': lambda: self._open_wiki_search()},
        ]
        self.radial = RadialMenu(self.root, items)

    def _poll_radial(self):
        """Poll for middle-click to open radial menu."""
        if not self.running:
            return
        if self.radial and self.focus.is_focused():
            self.radial.poll_middle_click()
        self.root.after(30, self._poll_radial)

    # ---- Window management ----

    def _minimize(self):
        """Minimize to mini mode."""
        mod = self._active_mod
        if mod and mod._window:
            x = mod._window.winfo_x()
            y = mod._window.winfo_y()
            mod._window.withdraw()
            self.mini_mode.show(x, y)
            self.mini_mode.refresh(mod.get_active_features())

    def _restore_from_mini(self):
        """Restore from mini mode."""
        self.mini_mode.hide()
        mod = self._active_mod
        if mod and mod._window:
            mod._window.deiconify()

    # ---- Wiki ----

    def _toggle_wiki_panel(self):
        """Toggle the wiki panel."""
        from wiki.window import WikiWindow

        if self._wiki_panel:
            self._wiki_panel.destroy()
            self._wiki_panel = None
            return

        mod = self._active_mod
        parent = mod._window if mod and mod._window else self.root

        self._wiki_panel = WikiWindow(parent)

    def _open_wiki_search(self):
        """Open the wiki search overlay from the radial menu."""
        from wiki.search_overlay import WikiSearchOverlay
        from wiki.data import load_wiki_data

        if self._wiki_search:
            self._wiki_search.close()
            self._wiki_search = None

        mod = self._active_mod
        parent = mod._window if mod and mod._window else self.root
        wiki_data = load_wiki_data()

        def _open_wiki_cb(entry_name=None, highlight_key=None,
                          table_index=None):
            if not self._wiki_panel:
                self._toggle_wiki_panel()
            if self._wiki_panel and entry_name:
                self._wiki_panel.navigate_to(
                    entry_name, highlight_key, table_index)

        self._wiki_search = WikiSearchOverlay(
            parent, wiki_data, _open_wiki_cb)

    # ---- Update ----

    def _run_in_app_update(self):
        """Check for and apply update in the background."""
        from updater import check_for_update, apply_update, restart

        mod = self._active_mod
        btn = getattr(mod, '_update_btn', None)

        def _check():
            result = check_for_update()
            if result is None:
                if btn:
                    self.root.after(
                        0, lambda: btn.config(fg='#484f58'))
                    self.root.after(
                        0, lambda: setattr(btn, '_rest_fg', '#484f58'))
                return
            tag, url = result
            if btn:
                self.root.after(
                    0, lambda: btn.config(fg='#50fa7b'))
                self.root.after(
                    0, lambda: setattr(btn, '_rest_fg', '#50fa7b'))
            success = apply_update(url)
            if success:
                self.root.after(0, restart)

        Thread(target=_check, daemon=True).start()

    # ---- Quit ----

    def _quit(self):
        """Shut down the application."""
        self.running = False
        if self._active_mod:
            self._active_mod.destroy()
        self.hotkeys.cleanup()
        self.mini_mode.hide()
        if self._wiki_panel:
            try:
                self._wiki_panel.destroy()
            except Exception:
                pass
        if self._wiki_search:
            try:
                self._wiki_search.close()
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        """Start the Tk main loop."""
        self.root.mainloop()
