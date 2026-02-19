"""GameMod ABC — base class for all game mods."""

from abc import ABC, abstractmethod
import tkinter as tk


class GameMod(ABC):
    """Base class for game-specific mods."""

    MOD_ID = ""          # e.g. "forge"
    MOD_NAME = ""        # e.g. "Forge"
    GAME_PLACE_IDS = []  # Roblox Place IDs this mod handles
    WIKI_URL = None      # Fandom wiki base URL, or None

    def __init__(self, hub):
        self.hub = hub
        self._components = []
        self._window = None

    @abstractmethod
    def init(self):
        """Register hotkeys, radial items, components."""

    @abstractmethod
    def build_gui(self, parent):
        """Create and return the mod's own Toplevel window."""

    def start(self):
        """Start threads + components."""
        for comp in self._components:
            comp.start()

    def stop(self):
        """Stop threads + components."""
        for comp in self._components:
            comp.stop()

    def destroy(self):
        """Full cleanup."""
        self.stop()
        if self._window:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None

    def use_component(self, cls, **config):
        """Instantiate a reusable component with mod-specific config."""
        comp = cls(self.hub, self, **config)
        self._components.append(comp)
        return comp

    def get_active_features(self):
        """Return (name, color) pairs for mini-mode display.

        Override in subclass.
        """
        return []
