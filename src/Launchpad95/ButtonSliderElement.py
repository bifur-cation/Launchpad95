"""
ButtonSliderElement.py — Virtual slider backed by a row of physical buttons.

Maps a column of 8 (or any number of) Launchpad buttons to a single
continuous or discrete parameter.  One button lights up to indicate the
current value; pressing any button immediately snaps the parameter to the
corresponding level.

The class inherits from both ``SliderElement`` (to participate in the
parameter-connection machinery) and ``SlotManager`` (to manage the button
value slots cleanly).

Because the slider has no real MIDI channel/identifier, the standard
``message_channel()``, ``message_identifier()``, and ``message_map_mode()``
methods raise ``NotImplementedError``; MIDI mapping goes through the individual
button elements instead.
"""

from __future__ import absolute_import, division, print_function, unicode_literals

try:
    from past.utils import old_div
except ImportError:
    def old_div(a, b):
        """Python 2 compatible integer division fallback."""
        return a / b

from _Framework.ButtonElement import ButtonElement
from _Framework.InputControlElement import MIDI_INVALID_TYPE, InputControlElement
from _Framework.SliderElement import SliderElement
from _Framework.SubjectSlot import SlotManager


class ButtonSliderElement(SliderElement, SlotManager):
    """
    A virtual slider composed of a fixed set of physical buttons.

    One button is lit to represent the current parameter value; pressing any
    button maps that button's position to a parameter value and applies it.

    Class Attributes:
        _last_sent_value (int): Tracks the last value sent to avoid redundant
            LED updates.  Initialised to ``-1`` (sentinel for "never sent").

    Instance Attributes:
        _buttons (tuple[ButtonElement]): The physical buttons forming this slider.
        _parameter_value_slot: SlotManager slot that listens to the mapped
            parameter's ``value`` property.
        _button_slots: SlotManager that holds value-listener slots for each button.
    """

    _last_sent_value = -1

    def __init__(self, buttons):
        """
        Initialise the slider and register value listeners on each button.

        Args:
            buttons (tuple[ButtonElement] | list[ButtonElement]): The ordered
                set of buttons representing the slider positions.  Index 0 is
                the bottom of the slider (minimum value).
        """
        SliderElement.__init__(self, MIDI_INVALID_TYPE, 0, 0)
        # Slot that tracks the connected parameter's value changes
        self._parameter_value_slot = self.register_slot(
            None, self._on_parameter_changed, 'value')
        self._buttons = buttons
        self._last_sent_value = -1
        # Manager for button press listeners
        self._button_slots = self.register_slot_manager()
        for button in self._buttons:
            self._button_slots.register_slot(
                button, self._button_value, 'value',
                extra_kws={'identify_sender': True})

    def disconnect(self):
        """Release button references and clean up parent resources."""
        SliderElement.disconnect(self)
        self._buttons = None

    # ------------------------------------------------------------------ #
    # Unsupported MIDI mapping methods                                     #
    # ------------------------------------------------------------------ #

    def message_channel(self):
        """Not supported — raises NotImplementedError."""
        raise NotImplementedError(
            'message_channel() should not be called directly on ButtonSliderElement')

    def message_identifier(self):
        """Not supported — raises NotImplementedError."""
        raise NotImplementedError(
            'message_identifier() should not be called directly on ButtonSliderElement')

    def message_map_mode(self):
        """Not supported — raises NotImplementedError."""
        raise NotImplementedError(
            'message_map_mode() should not be called directly on ButtonSliderElement')

    def install_connections(self, install_translation_callback,
                            install_mapping_callback, install_forwarding_callback):
        """
        Override to suppress normal MIDI mapping.

        The slider does not use Live's MIDI map; parameter changes are applied
        directly by :meth:`_button_value`.
        """
        pass

    def identifier_bytes(self):
        """Not meaningful for a button slider — raises RuntimeWarning."""
        raise RuntimeWarning(
            'identifier_bytes() should not be called on ButtonSliderElement')

    # ------------------------------------------------------------------ #
    # Parameter connection                                                 #
    # ------------------------------------------------------------------ #

    def connect_to(self, parameter):
        """
        Connect the slider to a Live device parameter.

        Registers the parameter value slot and triggers an initial LED update.

        Args:
            parameter: A ``Live.DeviceParameter.DeviceParameter`` instance.
        """
        InputControlElement.connect_to(self, parameter)
        self._parameter_value_slot.subject = parameter
        if self._parameter_to_map_to is not None:
            self._on_parameter_changed(trigger_osd=False)

    def release_parameter(self):
        """Disconnect from the current parameter and clear the value slot."""
        self._parameter_value_slot.subject = None
        InputControlElement.release_parameter(self)

    # ------------------------------------------------------------------ #
    # LED feedback                                                         #
    # ------------------------------------------------------------------ #

    def send_value(self, value):
        """
        Light the button that corresponds to ``value`` and turn all others off.

        Only sends LED updates when the value has actually changed since the
        last call.

        Args:
            value (int): MIDI value 0–127 representing the parameter position.
        """
        if value != self._last_sent_value:
            num_buttons = len(self._buttons)
            # Compute which button index should be lit
            if value > 0:
                index_to_light = int(old_div((num_buttons - 1) * value, 127))
            else:
                index_to_light = 0

            for index in range(num_buttons):
                if index == index_to_light:
                    self._buttons[index].turn_on()
                else:
                    self._buttons[index].turn_off()

            self._last_sent_value = value

    # ------------------------------------------------------------------ #
    # Button and parameter change handlers                                 #
    # ------------------------------------------------------------------ #

    def _button_value(self, value, sender):
        """
        Handle a button press and map it to a parameter value.

        Called when any of the slider's buttons is pressed.  The sender's
        position determines the target parameter value.

        Args:
            value (int): MIDI velocity (0–127); 0 means button released.
            sender (ButtonElement): The button that triggered the event.
        """
        self.clear_send_cache()
        # Act on button release for momentary buttons (value == 0) or
        # on press for non-momentary (toggle) buttons
        if not (value != 0 or sender.is_momentary()):
            index_of_sender = list(self._buttons).index(sender)
            # Linear mapping of button index to MIDI range 0–127
            midi_value = int(old_div(127 * index_of_sender, len(self._buttons) - 1))
            if self._parameter_to_map_to is not None:
                if self._parameter_to_map_to.is_enabled:
                    param_range = (self._parameter_to_map_to.max
                                   - self._parameter_to_map_to.min)
                    # Map button index to parameter range
                    param_value = (old_div(param_range * index_of_sender,
                                           len(self._buttons) - 1)
                                   + self._parameter_to_map_to.min)
                    # Add a small positive nudge to ensure the value lands
                    # inside the correct "step bucket" when quantized
                    if index_of_sender > 0:
                        param_value += old_div(param_range, 4 * len(self._buttons))
                        if param_value > self._parameter_to_map_to.max:
                            param_value = self._parameter_to_map_to.max
                    self._parameter_to_map_to.value = param_value
            self.notify_value(midi_value)

    def _on_parameter_changed(self):
        """
        Update the LED when the connected parameter changes externally.

        Converts the parameter's current position within its range to a
        0–127 MIDI value and calls :meth:`send_value`.
        """
        param_range = abs(self._parameter_to_map_to.max
                          - self._parameter_to_map_to.min)
        midi_value = int(old_div(
            127 * abs(self._parameter_to_map_to.value
                      - self._parameter_to_map_to.min),
            param_range))
        self.send_value(midi_value)
