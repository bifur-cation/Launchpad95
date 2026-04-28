"""
ConfigurableButtonElement.py — Skin-aware, multi-state button element.

Extends the ``_Framework`` ``ButtonElement`` class to support named skin
colour keys (e.g. ``"Mode.Session.On"``) in addition to raw integer velocity
values.  This allows button LEDs to be driven entirely by the active skin
without hard-coding MIDI values in component logic.

Key differences from the base ``ButtonElement``:
  - ``set_on_off_values()`` accepts skin key strings, not just integers.
  - ``send_value()`` accepts ``ON_VALUE``/``OFF_VALUE`` sentinels, integers,
    or skin key strings.
  - ``set_light()`` falls back gracefully when a skin colour is missing.
  - ``set_enabled()`` maps to ``suppress_script_forwarding`` instead of the
    base-class enable/disable mechanism, allowing individual buttons to be
    silenced without destroying their listeners.
  - ``force_next_send()`` bypasses the send cache so the LED is refreshed on
    the next call regardless of whether the value has changed.
"""

from _Framework.Skin import SkinColorMissingError
from _Framework.ButtonElement import ButtonElement, ON_VALUE, OFF_VALUE


class ConfigurableButtonElement(ButtonElement):
    """
    A button whose LED colours are driven by named skin keys.

    The ``states`` dict maps ``True`` (on) and ``False`` (off) to skin key
    strings, which are resolved to ``Color`` objects via the active skin.
    Extra states beyond ``True``/``False`` can be added freely.

    Class Attributes:
        default_states (dict): Default skin key mapping
            ``{True: 'DefaultButton.On', False: 'DefaultButton.Off'}``.
        send_depends_on_forwarding (bool): Always ``False``; the button sends
            LED feedback regardless of whether MIDI forwarding is enabled.

    Instance Attributes:
        states (dict): Mutable copy of ``default_states`` that can be
            overridden per-button via :meth:`set_on_off_values`.
        _control_surface: Reference to the owning Launchpad control surface,
            used for logging and context.
    """

    default_states = {True: 'DefaultButton.On', False: 'DefaultButton.Off'}
    send_depends_on_forwarding = False

    def __init__(self, is_momentary, msg_type, channel, identifier,
                 skin=None, default_states=None, control_surface=None, *a, **k):
        """
        Initialise the button and install the skin.

        Args:
            is_momentary (bool): ``True`` if the button fires on press and
                release; ``False`` for toggle buttons.
            msg_type (int): MIDI message type constant (MIDI_NOTE_TYPE or
                MIDI_CC_TYPE from ``_Framework.InputControlElement``).
            channel (int): MIDI channel (0–15).
            identifier (int): MIDI note number or CC number (0–127).
            skin (Skin | None): Skin object for colour lookups.
            default_states (dict | None): Override the class-level
                ``default_states`` mapping for this instance.
            control_surface: Owning control surface reference.
        """
        self._control_surface = control_surface
        super(ConfigurableButtonElement, self).__init__(
            is_momentary, msg_type, channel, identifier, skin=skin, **k)
        if default_states is not None:
            self.default_states = default_states
        # Work on a per-instance copy so mutations don't affect the class default
        self.states = dict(self.default_states)

    # ------------------------------------------------------------------ #
    # On/Off value properties                                              #
    # ------------------------------------------------------------------ #

    @property
    def _on_value(self):
        """Skin key string for the 'on' state (index ``True`` in states)."""
        return self.states[True]

    @property
    def _off_value(self):
        """Skin key string for the 'off' state (index ``False`` in states)."""
        return self.states[False]

    @property
    def on_value(self):
        """Resolved integer MIDI velocity for the 'on' state."""
        return self._try_fetch_skin_value(self._on_value)

    @property
    def off_value(self):
        """Resolved integer MIDI velocity for the 'off' state."""
        return self._try_fetch_skin_value(self._off_value)

    def _try_fetch_skin_value(self, value):
        """
        Attempt to resolve a skin key to its ``Color`` object.

        Falls back to returning the raw value if the key is missing from the
        skin (e.g. when passing a plain integer).

        Args:
            value (str | int): Skin key string or raw MIDI velocity.

        Returns:
            Color | int: Resolved colour, or the original value on failure.
        """
        try:
            return self._skin[value]
        except SkinColorMissingError:
            return value

    # ------------------------------------------------------------------ #
    # State management                                                     #
    # ------------------------------------------------------------------ #

    def reset(self):
        """Turn the LED off using the disabled skin colour."""
        self.set_light('DefaultButton.Disabled')

    def reset_state(self):
        """Restore the button to its default on/off state mapping and re-enable it."""
        self.states = dict(self.default_states)
        super(ConfigurableButtonElement, self).reset_state()
        self.set_enabled(True)

    def set_on_off_values(self, on_value, off_value=None):
        """
        Override the on/off skin keys for this button.

        If ``off_value`` is omitted, ``on_value`` is treated as a prefix and
        ``".On"``/``".Off"`` suffixes are appended automatically.

        Args:
            on_value (str): Skin key for the 'on' state, or prefix when
                ``off_value`` is ``None``.
            off_value (str | None): Skin key for the 'off' state.
        """
        self.clear_send_cache()
        if off_value is None:
            self.states[True] = str(on_value) + ".On"
            self.states[False] = str(on_value) + ".Off"
        else:
            self.states[True] = on_value
            self.states[False] = off_value

    # ------------------------------------------------------------------ #
    # Enable / disable                                                     #
    # ------------------------------------------------------------------ #

    def set_enabled(self, enabled):
        """
        Enable or disable MIDI forwarding for this button.

        When disabled (``enabled=False``) MIDI messages from the Launchpad
        are not forwarded to Live, effectively making the button inert.
        LED feedback is not affected.

        Args:
            enabled (bool): ``True`` to enable, ``False`` to disable.
        """
        self.suppress_script_forwarding = not enabled

    def is_enabled(self):
        """
        Return whether the button is currently forwarding MIDI to Live.

        Returns:
            bool: ``True`` if forwarding is active.
        """
        return not self.suppress_script_forwarding

    # ------------------------------------------------------------------ #
    # LED / send helpers                                                   #
    # ------------------------------------------------------------------ #

    def set_light(self, value):
        """
        Set the LED to a skin colour or fall back to the base class.

        Args:
            value (str | int): Skin key string or raw MIDI velocity.
        """
        try:
            self._draw_skin(value)
        except SkinColorMissingError:
            super(ButtonElement, self).set_light(value)

    def send_value(self, value, **k):
        """
        Send a value to the LED, supporting skin keys, sentinels, and integers.

        Args:
            value: One of:
              - ``ON_VALUE`` sentinel → send on-colour
              - ``OFF_VALUE`` sentinel → send off-colour
              - ``int``     → raw MIDI velocity via base class
              - ``str``     → skin key string → draw via skin
        """
        if value is ON_VALUE:
            self._do_send_on_value(**k)
        elif value is OFF_VALUE:
            self._do_send_off_value(**k)
        elif type(value) is int:
            super(ConfigurableButtonElement, self).send_value(value, **k)
        else:
            self._draw_skin(value)

    def force_next_send(self):
        """
        Force the next LED send to bypass the send-value cache.

        Useful after mode switches where the LED state is known to be stale
        but the cached value has not changed.
        """
        self._force_next_send = True
        self.clear_send_cache()

    def _do_send_on_value(self, **k):
        """Send the 'on' colour (integer or skin key) to the LED."""
        if type(self._on_value) is int:
            super(ConfigurableButtonElement, self).send_value(self._on_value, **k)
        else:
            self._draw_skin(self._on_value)

    def _do_send_off_value(self, **k):
        """Send the 'off' colour (integer or skin key) to the LED."""
        if type(self._off_value) is int:
            super(ConfigurableButtonElement, self).send_value(self._off_value, **k)
        else:
            self._draw_skin(self._off_value)

    def _draw_skin(self, value):
        """
        Resolve a skin key and call its ``draw()`` method on this button.

        Args:
            value (str): Skin key string to look up and draw.
        """
        self._skin[value].draw(self)

    def script_wants_forwarding(self):
        """
        Return whether this button should forward MIDI to the script.

        Returns:
            bool: ``True`` when the button is enabled (forwarding is active).
        """
        return not self.suppress_script_forwarding
