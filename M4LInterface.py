"""
M4LInterface.py — On-Screen Display (OSD) bridge for Max for Live integration.

``M4LInterface`` acts as a lightweight data container that aggregates the
current mode name, up to 8 attribute name/value pairs, and two free-form info
strings.  Any Max for Live (M4L) patch that wants to display Launchpad95 state
can subscribe to the ``updateML`` notification and read those fields directly.

Within Launchpad95 every major component calls ``set_osd(osd)`` with a shared
``M4LInterface`` instance, then writes to its attributes and calls
``osd.update()`` whenever the display state changes.
"""

from _Framework.ControlSurfaceComponent import ControlSurfaceComponent


class M4LInterface(ControlSurfaceComponent):
    """
    Shared on-screen display (OSD) data bus.

    Components write to the public attributes and then call :meth:`update` to
    push the change to any registered M4L listener.

    Attributes:
        mode (str): Name of the currently active mode
            (e.g. ``"Session"``, ``"Mixer"``, ``"Device Controller"``).
        info (list[str]): Two-element list of free-form status strings.
            Typically used for track name (index 0) and device name (index 1).
        attributes (list[str]): Eight-element list of parameter values shown
            in the M4L display columns.
        attribute_names (list[str]): Eight-element list of parameter names
            corresponding to :attr:`attributes`.
        _update_listener: Deprecated/internal listener reference (unused).
        _updateML_listener (callable | None): Callback invoked by
            :meth:`update`; set by a M4L patch via :meth:`add_updateML_listener`.
    """

    def __init__(self):
        ControlSurfaceComponent.__init__(self)
        self._name = 'OSD'
        self._update_listener = None
        self._updateML_listener = None
        # Default mode label shown before any component sets it
        self.mode = ' '
        self.clear()

    def disconnect(self):
        """Remove the M4L listener reference on teardown."""
        self._updateML_listener = None

    # ------------------------------------------------------------------ #
    # Mode helpers                                                         #
    # ------------------------------------------------------------------ #

    def set_mode(self, mode):
        """
        Switch the OSD to a new mode and clear all attribute data.

        Args:
            mode (str): Human-readable mode name to display.
        """
        self.clear()
        self.mode = mode

    def clear(self):
        """
        Reset all display data to blank placeholder strings.

        Called on init and whenever the mode changes so stale data is never
        shown for a new context.
        """
        self.info = [' ', ' ']
        self.attributes = [' ' for _ in range(8)]
        self.attribute_names = [' ' for _ in range(8)]

    # ------------------------------------------------------------------ #
    # Legacy update-listener API (kept for compatibility)                  #
    # ------------------------------------------------------------------ #

    def set_update_listener(self, listener):
        """Register a single update listener (legacy; prefer updateML API)."""
        self._update_listener = listener

    def remove_update_listener(self, listener):
        """Deregister the update listener."""
        self._update_listener = None

    def update_has_listener(self):
        """Return ``True`` if an update listener is currently registered."""
        return self._update_listener is not None

    # ------------------------------------------------------------------ #
    # M4L (updateML) listener API                                          #
    # ------------------------------------------------------------------ #

    @property
    def updateML(self):
        """Always returns ``True``; used by M4L to confirm the OSD is live."""
        return True

    def set_updateML_listener(self, listener):
        """Set the M4L update callback (older single-assignment API)."""
        self._updateML_listener = listener

    def add_updateML_listener(self, listener):
        """
        Register a callable that M4L will call when :meth:`update` fires.

        Args:
            listener (callable): Zero-argument function to invoke.
        """
        self._updateML_listener = listener

    def remove_updateML_listener(self, listener):
        """Deregister the M4L update callback."""
        self._updateML_listener = None

    def updateML_has_listener(self, listener):
        """Return ``True`` if an M4L listener is registered."""
        return self._updateML_listener is not None

    # ------------------------------------------------------------------ #
    # Core update method                                                   #
    # ------------------------------------------------------------------ #

    def update(self, args=None):
        """
        Notify the M4L listener that the OSD data has changed.

        If no listener is registered this is a no-op.  Components should
        populate :attr:`mode`, :attr:`info`, :attr:`attributes`, and
        :attr:`attribute_names` before calling this method.

        Args:
            args: Unused; kept for API compatibility with ControlSurfaceComponent.
        """
        if self.updateML_has_listener(None):
            self._updateML_listener()
