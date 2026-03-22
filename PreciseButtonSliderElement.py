"""
PreciseButtonSliderElement.py — Enhanced button slider with volume and pan display modes.

Extends :class:`~ButtonSliderElement.ButtonSliderElement` to add three display
modes that are better suited to mixer controls:

``SLIDER_MODE_SINGLE``
    One button lights up (inherited behaviour from the base class).

``SLIDER_MODE_VOLUME``
    Buttons light cumulatively from the bottom up (bar-graph style).
    Uses a configurable ``value_map`` that converts the 0–127 MIDI range
    to non-linear dB levels (see :data:`SubSelectorComponent.VOL_VALUE_MAP`).

``SLIDER_MODE_PAN``
    Buttons light outward from the centre.  Positive pan lights buttons on
    the right half; negative pan lights buttons on the left half.  Centre
    (value ≈ 63/64) leaves all buttons dark.

The class also handles a disabled state so that a slider column can be
silenced without disconnecting it from its parameter.
"""

from _Framework.ButtonSliderElement import ButtonSliderElement
from .Log import log

# Slider display mode constants
SLIDER_MODE_SINGLE = 0   # Single lit button (base class style)
SLIDER_MODE_VOLUME = 1   # Cumulative bar graph (bottom-up)
SLIDER_MODE_PAN = 2      # Centred bi-directional display


class PreciseButtonSliderElement(ButtonSliderElement):
    """
    Button slider with volume-bar and pan-indicator display modes.

    Instance Attributes:
        _disabled (bool): When ``True`` all LED sends are suppressed and
            button presses are ignored.
        _mode (int): Current display mode; one of the ``SLIDER_MODE_*``
            constants.
        _value_map (tuple[float]): Normalised (0.0–1.0) level thresholds for
            each button position.  Index 0 corresponds to the lowest button.
            The default map is a uniform linear distribution.
    """

    def __init__(self, buttons):
        """
        Initialise the slider with a linear default value map.

        Args:
            buttons (tuple[ButtonElement]): Ordered set of physical buttons.
        """
        ButtonSliderElement.__init__(self, buttons)
        num_buttons = len(buttons)
        self._disabled = False
        self._mode = SLIDER_MODE_VOLUME  # Default to volume bar-graph
        # Linear map: each button covers an equal fraction of the 0–1 range
        self._value_map = tuple([float(index / num_buttons)
                                 for index in range(num_buttons)])

    # ------------------------------------------------------------------ #
    # Configuration                                                        #
    # ------------------------------------------------------------------ #

    def set_disabled(self, disabled):
        """
        Suppress or restore all slider activity.

        Args:
            disabled (bool): ``True`` to silence this column.
        """
        assert isinstance(disabled, type(False))
        self._disabled = disabled

    def set_mode(self, mode):
        """
        Change the LED display mode.

        Args:
            mode (int): One of ``SLIDER_MODE_SINGLE``, ``SLIDER_MODE_VOLUME``,
                or ``SLIDER_MODE_PAN``.
        """
        assert mode in (SLIDER_MODE_SINGLE, SLIDER_MODE_VOLUME, SLIDER_MODE_PAN)
        if mode != self._mode:
            self._mode = mode

    def set_value_map(self, value_map):
        """
        Replace the normalised level map used by volume and pan modes.

        Args:
            value_map (tuple[float]): Must have the same length as the button
                count.  Values should be normalised fractions (0.0–1.0 for
                volume, −1.0–1.0 for pan).
        """
        assert isinstance(value_map, (tuple, type(None)))
        assert len(value_map) == len(self._buttons)
        self._value_map = value_map

    # ------------------------------------------------------------------ #
    # Parameter connection                                                 #
    # ------------------------------------------------------------------ #

    def connect_to(self, parameter):
        """
        Connect and force an immediate LED refresh.

        Args:
            parameter: Live device parameter to map to.
        """
        ButtonSliderElement.connect_to(self, parameter)
        if self._parameter_to_map_to is not None:
            self._last_sent_value = -1  # Invalidate cache to force redraw
            self._on_parameter_changed()

    def release_parameter(self):
        """Disconnect and reset all button LEDs."""
        old_param = self._parameter_to_map_to
        ButtonSliderElement.release_parameter(self)
        if not self._disabled and old_param is not None:
            for button in self._buttons:
                button.reset()

    # ------------------------------------------------------------------ #
    # LED send                                                             #
    # ------------------------------------------------------------------ #

    def send_value(self, value):
        """
        Update the LED display if the value has changed and the slider is active.

        Delegates to the appropriate display-mode method based on
        :attr:`_mode`.

        Args:
            value (int): MIDI value 0–127 representing the parameter position.
        """
        if not self._disabled:
            assert value is not None
            assert isinstance(value, int)
            assert value in range(128)
            if value != self._last_sent_value:
                if self._mode == SLIDER_MODE_SINGLE:
                    ButtonSliderElement.send_value(self, value)
                elif self._mode == SLIDER_MODE_VOLUME:
                    self._send_value_volume(value)
                elif self._mode == SLIDER_MODE_PAN:
                    self._send_value_pan(value)
                else:
                    assert False, "Unknown slider mode: {}".format(self._mode)
                self._last_sent_value = value

    def reset(self):
        """Turn all button LEDs off (call on disconnect or mode exit)."""
        if not self._disabled and self._buttons is not None:
            for button in self._buttons:
                if button is not None:
                    button.reset()

    # ------------------------------------------------------------------ #
    # Display mode implementations                                         #
    # ------------------------------------------------------------------ #

    def _send_value_volume(self, value):
        """
        Light buttons cumulatively from bottom up (volume bar-graph).

        Finds the highest button whose threshold is still ≤ the normalised
        value, lights it and all buttons below it, and darkens the rest.

        Args:
            value (int): MIDI value 0–127.
        """
        index_to_light = -1  # -1 means all buttons off (value == 0)
        normalised_value = float(value) / 127.0
        if normalised_value > 0.0:
            for index in range(len(self._value_map)):
                if normalised_value <= self._value_map[index]:
                    index_to_light = index
                    break
        # Build a boolean mask: True = lit, False = dark
        self._send_mask(
            tuple([index <= index_to_light for index in range(len(self._buttons))]))

    def _send_value_pan(self, value):
        """
        Light buttons outward from centre (pan indicator).

        Negative pan: lights buttons from the right side (high indices) toward
        the centre.  Positive pan: lights buttons from the left side (low
        indices) toward the centre.  Centre (values 63/64): all dark.

        Args:
            value (int): MIDI value 0–127 (64 = centre).
        """
        num_buttons = len(self._buttons)
        button_bits = [False for _ in range(num_buttons)]
        normalised_value = float(2 * value / 127.0) - 1.0
        # Treat 63/64 as exactly centre to avoid floating-point drift
        if value in (63, 64):
            normalised_value = 0.0

        if normalised_value < 0.0:
            # Left of centre: light buttons whose map value >= normalised_value
            for index in range(len(self._buttons)):
                button_bits[index] = self._value_map[index] >= normalised_value
                if self._value_map[index] >= 0:
                    break  # Stop at the centre point
        elif normalised_value > 0.0:
            # Right of centre: iterate from the top down
            for index in range(len(self._buttons)):
                r_index = len(self._buttons) - 1 - index
                button_bits[r_index] = self._value_map[r_index] <= normalised_value
                if self._value_map[r_index] <= 0:
                    break  # Stop at the centre point
        # else: normalised_value == 0.0 → all buttons remain False (off)

        self._send_mask(tuple(button_bits))

    def _send_mask(self, mask):
        """
        Apply a boolean mask to the button LEDs.

        Args:
            mask (tuple[bool]): One entry per button; ``True`` = turn on,
                ``False`` = turn off.
        """
        assert isinstance(mask, tuple)
        assert len(mask) == len(self._buttons)
        for index in range(len(self._buttons)):
            if mask[index]:
                self._buttons[index].turn_on()
            else:
                self._buttons[index].turn_off()

    # ------------------------------------------------------------------ #
    # Button and parameter change handlers                                 #
    # ------------------------------------------------------------------ #

    def _button_value(self, value, sender):
        """
        Handle a button press and write the corresponding value to the parameter.

        The button's position in ``_value_map`` is used directly as the
        normalised parameter value (bypassing the MIDI 0–127 mapping used by
        the base class).

        Args:
            value (int): MIDI velocity; non-zero = pressed.
            sender (ButtonElement): The button that was pressed.
        """
        assert isinstance(value, int)
        assert sender in self._buttons
        self._last_sent_value = -1  # Invalidate cache so LED refreshes

        if (self._parameter_to_map_to is not None
                and not self._disabled
                and (value != 0 or not sender.is_momentary())):
            index_of_sender = list(self._buttons).index(sender)
            if self._parameter_to_map_to.is_enabled:
                # Map button position directly via value_map
                self._parameter_to_map_to.value = self._value_map[index_of_sender]
            self.notify_value(value)

    def _on_parameter_changed(self):
        """
        Recompute and send the LED state when the parameter changes externally.

        Converts the current parameter value to the appropriate 0–127 MIDI
        value for the active display mode.
        """
        assert self._parameter_to_map_to is not None
        param_range = abs(self._parameter_to_map_to.max - self._parameter_to_map_to.min)
        param_value = self._parameter_to_map_to.value
        param_min = self._parameter_to_map_to.min
        param_mid = param_range / 2 + param_min
        midi_value = 0

        if self._mode == SLIDER_MODE_PAN:
            if param_value == param_mid:
                midi_value = 64  # Centre
            else:
                diff = abs(param_value - param_mid) / param_range * 127
                if param_value > param_mid:
                    midi_value = 64 + int(diff)
                else:
                    midi_value = 63 - int(diff)
        else:
            # Volume and single modes: linear 0–127
            midi_value = int(127 * abs(param_value - param_min) / param_range)

        self.send_value(midi_value)
