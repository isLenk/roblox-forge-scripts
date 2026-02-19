"""Component ABC — reusable building blocks for mods."""

from abc import ABC, abstractmethod


class Component(ABC):
    """Base class for reusable feature components that mods opt into."""

    def __init__(self, hub, mod, **config):
        self.hub = hub
        self.mod = mod
        self.config = config
        self._active = False

    @property
    def active(self):
        return self._active

    @abstractmethod
    def start(self):
        """Start the component's background work."""

    @abstractmethod
    def stop(self):
        """Stop the component's background work."""

    def toggle(self):
        """Toggle the component on/off."""
        if self._active:
            self.stop()
        else:
            self.start()

    def build_gui(self, parent):
        """Render controls into a parent frame. Mod decides placement.

        Returns the frame, or None if no GUI.
        """
        return None
