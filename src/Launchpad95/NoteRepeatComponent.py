"""
NoteRepeatComponent.py — Note repeat (arpeggiator-style) component.

Wraps Ableton Live's built-in ``note_repeat`` object to provide quantised
note repeat at standard musical rates.  When enabled it temporarily disables
MIDI recording quantization to prevent double-quantisation of the repeated
notes, and restores the original setting when disabled.

Constants
---------
NOTE_REPEAT_FREQUENCIES : list[float]
    Multipliers (in beats per bar) for each of the 8 selectable rates:
    1/4, 1/4t, 1/8, 1/8t, 1/16, 1/16t, 1/32, 1/32t.

QUANTIZATION_NAMES : tuple[str]
    Human-readable names corresponding to ``NOTE_REPEAT_FREQUENCIES``.
"""

from _Framework import Task
from _Framework.CompoundComponent import CompoundComponent
import Live

# Triplet ratio: 3/2 = 1.5 (triplet notes are 2/3 of their straight counterparts)
t = 3.0 / 2.0

# Repeat rate multipliers indexed 0–7 (straight and triplet eighth-note subdivisions)
NOTE_REPEAT_FREQUENCIES = [4, 4 * t, 8, 8 * t, 16, 16 * t, 32, 32 * t]
del t  # clean up the temporary variable

# Display names shown in the OSD for each frequency index
QUANTIZATION_NAMES = ('1/4', '1/4t', '1/8', '1/8t', '1/16', '1/16t', '1/32', '1/32t')


class DummyNoteRepeat(object):
    """
    Null object replacement for the Live note_repeat object.

    Used when ``set_note_repeat(None)`` is called so the component never has
    to guard against a ``None`` reference.

    Attributes:
        repeat_rate (float): Ignored; always 1.0.
        enabled (bool): Ignored; always False.
    """
    repeat_rate = 1.0
    enabled = False


class NoteRepeatComponent(CompoundComponent):
    """
    Control surface component that configures Ableton Live's note repeat.

    When enabled the component:
      1. Saves the current MIDI recording quantization setting.
      2. Disables recording quantization to avoid double-quantizing the output.
      3. Sets the repeat rate on the Live ``note_repeat`` object.

    When disabled it restores the saved quantization setting.

    Attributes:
        _last_record_quantization: The MIDI recording quantization value in
            effect before note repeat was enabled; restored on disable.
        _note_repeat: Reference to the Live note_repeat object (or a
            :class:`DummyNoteRepeat` if none is provided).
        _freq_index (int): Index into :data:`NOTE_REPEAT_FREQUENCIES` for the
            currently selected repeat rate (default: 2 → 1/8 note).
    """

    def __init__(self, *a, **k):
        super(NoteRepeatComponent, self).__init__(*a, **k)
        self._last_record_quantization = None
        self._note_repeat = None
        self._freq_index = 2  # Default to 1/8 note repeat
        self.set_note_repeat(None)

    def on_enabled_changed(self):
        """Enable or disable note repeat when the component is toggled."""
        if self.is_enabled():
            self._enable_note_repeat()
        else:
            self._disable_note_repeat()

    # ------------------------------------------------------------------ #
    # Frequency selection                                                  #
    # ------------------------------------------------------------------ #

    def set_freq_index(self, index):
        """
        Select a new repeat rate by index.

        Args:
            index (int): Index into :data:`NOTE_REPEAT_FREQUENCIES` (0–7).
        """
        self._freq_index = index
        self._update_note_repeat(self.is_enabled())

    def freq_index(self):
        """
        Return the current frequency index.

        Returns:
            int: Current index into :data:`NOTE_REPEAT_FREQUENCIES`.
        """
        return self._freq_index

    def freq_name(self):
        """
        Return the human-readable name of the current repeat rate.

        Returns:
            str: E.g. ``"1/16"`` for index 4.
        """
        return QUANTIZATION_NAMES[self._freq_index]

    def update(self):
        """Refresh component state (delegates to parent)."""
        super(NoteRepeatComponent, self).update()

    # ------------------------------------------------------------------ #
    # Note repeat object assignment                                        #
    # ------------------------------------------------------------------ #

    def set_note_repeat(self, note_repeat):
        """
        Assign the Live note_repeat object to control.

        Passing ``None`` installs a :class:`DummyNoteRepeat` so the rest of
        the component never needs to check for ``None``.

        Args:
            note_repeat: Live note_repeat instance or ``None``.
        """
        if not note_repeat:
            note_repeat = DummyNoteRepeat()
        if self._note_repeat is not None:
            self._note_repeat.enabled = False
        self._note_repeat = note_repeat
        self._update_note_repeat(enabled=self.is_enabled())

    def set_pad_parameters(self, element):
        """
        Reset a pad element when note repeat mode changes.

        Args:
            element: A button/pad element with a ``reset()`` method, or None.
        """
        if element:
            element.reset()

    # ------------------------------------------------------------------ #
    # Internal enable/disable helpers                                      #
    # ------------------------------------------------------------------ #

    def _enable_note_repeat(self):
        """Save quantization setting, disable it, and start repeat."""
        self._last_record_quantization = self.song().midi_recording_quantization
        self._set_recording_quantization(False)
        self._update_note_repeat(enabled=True)

    def _disable_note_repeat(self):
        """Stop repeat and restore the previously saved quantization setting."""
        if not self.song().midi_recording_quantization and self._last_record_quantization:
            self._set_recording_quantization(self._last_record_quantization)
        self._update_note_repeat(enabled=False)

    def _set_recording_quantization(self, value):
        """
        Schedule a task to update Live's MIDI recording quantization.

        The change is deferred via the task scheduler to avoid modifying song
        state inside a listener callback.

        Args:
            value: The quantization value to set, or ``False`` to disable.
        """
        def doit():
            self.song().midi_recording_quantization = value

        self._tasks.parent_task.add(Task.run(doit))

    def _on_selected_option_changed(self, option):
        """
        Update the note_repeat rate when the selected frequency option changes.

        The Live note_repeat.repeat_rate is measured in beats per bar so we
        divide 4.0 (beats per bar at 4/4) by the frequency multiplier.

        Args:
            option (int): Index into :data:`NOTE_REPEAT_FREQUENCIES`.
        """
        frequency = NOTE_REPEAT_FREQUENCIES[option]
        self._note_repeat.repeat_rate = 1.0 / frequency * 4.0

    def _update_note_repeat(self, enabled=False):
        """
        Synchronise the note_repeat object to the current rate and enable state.

        Args:
            enabled (bool): Whether note repeat should be active.
        """
        self._on_selected_option_changed(self._freq_index)
        self._note_repeat.enabled = self.is_enabled()
