"""Rebindable hotkey management system."""

import keyboard


class HotkeyManager:
    """Manages rebindable hotkeys with keyboard library hooks."""

    def __init__(self):
        self._hotkeys = {}  # name -> {'key', 'hook', 'callback'}
        self._capturing = None  # name of hotkey being rebound
        self._capture_hook = None
        self._capture_callback = None
        self.enabled = True

    def register(self, name, key, callback):
        """Register a new hotkey.

        Args:
            name: Unique identifier (e.g. 'circle', 'autoclicker')
            key: Key name (e.g. 'p', 'f5', 'caps lock')
            callback: Function to call on key press (receives event)
        """
        hook = keyboard.on_press_key(key, callback)
        self._hotkeys[name] = {
            'key': key,
            'hook': hook,
            'callback': callback,
        }

    def unregister(self, name):
        """Unregister a hotkey by name."""
        entry = self._hotkeys.pop(name, None)
        if entry and entry['hook']:
            try:
                keyboard.unhook(entry['hook'])
            except Exception:
                pass

    def rebind(self, name, new_key):
        """Change the key for a registered hotkey."""
        entry = self._hotkeys.get(name)
        if not entry:
            return
        old_key = entry['key']
        if new_key == old_key:
            return
        # Unhook old
        try:
            keyboard.unhook(entry['hook'])
        except Exception:
            pass
        # Re-register with new key
        entry['key'] = new_key
        entry['hook'] = keyboard.on_press_key(new_key, entry['callback'])
        print(f"[HOTKEY] '{name}' rebound: {old_key} -> {new_key}")

    def start_capture(self, name, on_captured):
        """Enter capture mode for a hotkey. Next key press completes rebind.

        Args:
            name: Hotkey name to rebind
            on_captured: Callback(name, new_key) called on main thread
        """
        if self._capturing is not None:
            return
        self._capturing = name
        self._capture_callback = on_captured
        self._capture_hook = keyboard.on_press(
            self._on_capture, suppress=False)

    def _on_capture(self, event):
        new_key = event.name
        keyboard.unhook(self._capture_hook)
        name = self._capturing
        self._capturing = None
        cb = self._capture_callback
        self._capture_callback = None
        if cb:
            cb(name, new_key)

    def get_key(self, name):
        """Get the current key for a hotkey."""
        entry = self._hotkeys.get(name)
        return entry['key'] if entry else None

    def get_display(self, name):
        """Get the display text for a hotkey's key."""
        key = self.get_key(name)
        return f'[{key.upper()}]' if key else '[?]'

    @property
    def is_capturing(self):
        return self._capturing is not None

    def cleanup(self):
        """Unhook all hotkeys."""
        for entry in self._hotkeys.values():
            try:
                keyboard.unhook(entry['hook'])
            except Exception:
                pass
        self._hotkeys.clear()
        if self._capture_hook:
            try:
                keyboard.unhook(self._capture_hook)
            except Exception:
                pass
