"""
SubSelectorComponent.py — Mixer mode sub-selector component.

Manages the four mixer sub-modes available when the Mixer button is active:

  0. **Overview** — each column shows Vol/Pan/Send/Send/Stop/Mute/Solo/Arm
     buttons.  Side buttons provide Stop All, Unmute, Unsolo, and Unarm.
  1. **Volume** — columns become 8-button volume sliders (bar-graph).
  2. **Pan** — columns become 8-button pan sliders (centred indicator).
  3. **Send A** — columns become 8-button send-A sliders.
  4. **Send B** — columns become 8-button send-B sliders.

The first four side buttons select the sub-mode; the remaining four side
buttons carry stop/mute/solo/arm actions in overview mode.

Value maps
----------
``PAN_VALUE_MAP``
    Normalised (−1.0 to +1.0) breakpoints for the 8-button pan slider.

``VOL_VALUE_MAP``
    Non-linear dB breakpoints for the 8-button volume slider, derived from
    the dB levels in :data:`Settings.VOLUME_LEVELS` via ``level_to_value()``.

``SEND_VALUE_MAP``
    Normalised (0.0 to 1.0) breakpoints for send sliders.
"""

import math
from _Framework.ModeSelectorComponent import ModeSelectorComponent
from _Framework.ButtonElement import ButtonElement
from _Framework.ButtonMatrixElement import ButtonMatrixElement
from _Framework.SessionComponent import SessionComponent
from .SpecialMixerComponent import SpecialMixerComponent
from .PreciseButtonSliderElement import (
    PreciseButtonSliderElement, SLIDER_MODE_VOLUME, SLIDER_MODE_PAN
)
try:
    from .Settings import Settings
except ImportError:
    from .Settings import *


def level_to_value(level):
    """
    Convert a dB level to a normalised (0.0–1.0) parameter value for the
    Ableton mixer volume parameter range.

    Uses a piecewise formula:
      - For ``level >= -18 dB``: linear segment ``(level + 34) / 40``
      - For ``level < -18 dB``: exponential curve matching the Live fader taper.

    Args:
        level (float): Volume level in dB (negative values only; 0 dB = unity).

    Returns:
        float: Normalised value in the range 0.0–1.0.
    """
    if level >= -18:
        return (level + 34) / 40.0
    else:
        return math.e ** (level / 23.4573) / 1.17234


# Pan slider breakpoints: 8 positions symmetric around centre
PAN_VALUE_MAP = (-1.0, -0.634921, -0.31746, 0.0, 0.0, 0.31746, 0.634921, 1.0)

# Volume slider breakpoints derived from the user-configurable dB levels.
# The lowest button is always 0.0 (silent/−∞).
VOL_VALUE_MAP = tuple(sorted(
    [0.0] + [level_to_value(level) for level in Settings.VOLUME_LEVELS]))

# Send slider breakpoints: 8 non-linear positions covering 0.0–1.0
SEND_VALUE_MAP = (0.0, 0.103536, 0.164219, 0.238439, 0.343664, 0.55, 0.774942, 1.0)


class SubSelectorComponent(ModeSelectorComponent):
    """
    Sub-mode selector for Mixer mode.

    Manages mixer sub-modes (overview, volume, pan, send A, send B) and wires
    the 8-button slider columns to the appropriate mixer parameter.

    Attributes:
        _control_surface: The owning Launchpad control surface.
        _session (SpecialSessionComponent | SpecialProSessionComponent):
            Reference to the session component so stop-clip buttons can be
            cleared when entering volume/pan/send modes.
        _mixer (SpecialMixerComponent): The mixer component controlling 8 tracks.
        _matrix (ButtonMatrixElement): The 8×8 button grid.
        _sliders (list[PreciseButtonSliderElement]): One slider per column (8 total).
        _side_buttons (tuple): The lower 4 side buttons (stop/mute/solo/arm).
        _update_callback (callable | None): Optional callback invoked after
            every mode change; used by MainSelectorComponent to refresh MIDI
            channel assignments.
    """

    def __init__(self, matrix, side_buttons, session, control_surface):
        """
        Initialise the mixer and create one slider per matrix column.

        Args:
            matrix (ButtonMatrixElement): 8×8 button grid.
            side_buttons (tuple[ButtonElement]): 8 side buttons; the first 4
                select the sub-mode and the last 4 carry mixer actions.
            session (SessionComponent): The active session component.
            control_surface: The owning Launchpad control surface.
        """
        assert isinstance(matrix, ButtonMatrixElement)
        assert (matrix.width() == 8) and (matrix.height() == 8)
        assert isinstance(side_buttons, tuple) and len(side_buttons) == 8
        assert isinstance(session, SessionComponent)
        ModeSelectorComponent.__init__(self)

        self._control_surface = control_surface
        self._session = session
        self._mixer = SpecialMixerComponent(matrix.width())
        self._matrix = matrix
        self._sliders = []
        self._mixer.name = 'Mixer'
        self._mixer.master_strip().name = 'Master_Channel_strip'
        self._mixer.selected_strip().name = 'Selected_Channel_strip'

        # Create one slider per column; buttons run bottom-up (row 7 → row 0)
        for column in range(matrix.width()):
            self._mixer.channel_strip(column).name = 'Channel_Strip_' + str(column)
            self._sliders.append(PreciseButtonSliderElement(
                tuple([matrix.get_button(column, 7 - row) for row in range(8)])))
            self._sliders[-1].name = 'Button_Slider_' + str(column)

        # Lower 4 side buttons carry mode-specific actions (stop/mute/solo/arm)
        self._side_buttons = side_buttons[4:]
        self._update_callback = None

        # Connect the mixer to the session so clip-stop LEDs work
        self._session.set_mixer(self._mixer)

        # Upper 4 side buttons select the 4 mixer sub-modes
        self.set_modes_buttons(side_buttons[:4])

    def disconnect(self):
        """Release all controls and remove value listeners."""
        for button in self._modes_buttons:
            button.remove_value_listener(self._mode_value)
        self._session = None
        self._mixer = None
        for slider in self._sliders:
            slider.release_parameter()
            slider.set_disabled(True)
        self._sliders = None
        self._matrix = None
        self._side_buttons = None
        self._update_callback = None
        ModeSelectorComponent.disconnect(self)

    # ------------------------------------------------------------------ #
    # Configuration                                                        #
    # ------------------------------------------------------------------ #

    def set_update_callback(self, callback):
        """
        Register a callback to call after every mode update.

        Args:
            callback (callable): Zero-argument function.
        """
        self._update_callback = callback

    def set_modes_buttons(self, buttons):
        """
        Replace the mode-select buttons.

        Args:
            buttons (tuple[ButtonElement] | None): Exactly 4 buttons.
        """
        assert buttons is None or isinstance(buttons, tuple)
        assert len(buttons) == self.number_of_modes()
        identify_sender = True
        for button in self._modes_buttons:
            button.remove_value_listener(self._mode_value)
        self._modes_buttons = []
        if buttons is not None:
            for button in buttons:
                assert isinstance(button, ButtonElement)
                self._modes_buttons.append(button)
                button.add_value_listener(self._mode_value, identify_sender)

    def set_mode(self, mode):
        """
        Switch to a specific sub-mode index.

        ``-1`` re-enters overview mode (no slider active).

        Args:
            mode (int): Sub-mode index (−1 to 3).
        """
        assert isinstance(mode, int)
        assert mode in range(-1, self.number_of_modes())
        if self._mode_index != mode or mode == -1:
            self._mode_index = mode
            self.update()

    def mode(self):
        """
        Return the current sub-mode index offset by 1 (for MIDI channel calcs).

        Returns:
            int: 0 when disabled; 1–4 for the four active sub-modes.
        """
        result = 0
        if self.is_enabled():
            result = self._mode_index + 1
        return result

    def number_of_modes(self):
        """Return the number of mixer sub-modes (4)."""
        return 4

    # ------------------------------------------------------------------ #
    # Enable / disable                                                     #
    # ------------------------------------------------------------------ #

    def on_enabled_changed(self):
        """Enable/disable all sliders and the mixer when this component toggles."""
        enabled = self.is_enabled()
        for index in range(self._matrix.width()):
            self._sliders[index].set_disabled(not enabled)
        self._mixer.set_enabled(enabled)
        self.set_mode(-1)

    def release_controls(self):
        """
        Release all matrix buttons and strip controls.

        Called when leaving Mixer mode so every button can be reclaimed by
        another mode.
        """
        for track in range(self._matrix.width()):
            for row in range(self._matrix.height()):
                self._matrix.get_button(track, row).set_on_off_values(
                    127, "DefaultButton.Disabled")
            strip = self._mixer.channel_strip(track)
            strip.set_default_buttons(None, None, None, None)
            strip.set_mute_button(None)
            strip.set_solo_button(None)
            strip.set_arm_button(None)
            strip.set_send_controls((None, None))
            strip.set_pan_control(None)
            strip.set_volume_control(None)
        self._session.set_stop_track_clip_buttons(None)
        self._mixer.set_global_buttons(None, None, None)
        self._session.set_stop_all_clips_button(None)

    # ------------------------------------------------------------------ #
    # Update                                                               #
    # ------------------------------------------------------------------ #

    def update(self):
        """
        Refresh all buttons and re-wire controls for the current sub-mode.

        Dispatches to the appropriate ``_setup_*`` method and then invokes
        the optional update callback.
        """
        super(SubSelectorComponent, self).update()
        assert self._modes_buttons is not None
        if self.is_enabled():
            if self._modes_buttons is not None:
                # Update mode-select button colours
                for index in range(len(self._modes_buttons)):
                    button = self._modes_buttons[index]
                    if index == 0:
                        button.set_on_off_values("Mixer.Volume")
                    elif index == 1:
                        button.set_on_off_values("Mixer.Pan")
                    elif index == 2:
                        button.set_on_off_values("Mixer.Sends")
                    elif index == 3:
                        button.set_on_off_values("Mixer.Sends")
                    # Active mode button = turn_off (inverted convention)
                    if index == self._mode_index:
                        button.turn_off()
                    else:
                        button.turn_on()

            # Action side buttons: always off in mixer mode
            for button in self._side_buttons:
                button.set_on_off_values(127, "DefaultButton.Disabled")
                button.turn_off()

            # Disable sliders in overview mode (mode_index == -1)
            for index in range(self._matrix.width()):
                self._sliders[index].set_disabled(self._mode_index == -1)

            self._mixer.set_allow_update(False)
            self._session.set_allow_update(False)

            if self._mode_index == -1:
                self._setup_mixer_overview()
            elif self._mode_index == 0:
                self._setup_volume_mode()
            elif self._mode_index == 1:
                self._setup_pan_mode()
            elif self._mode_index == 2:
                self._setup_send1_mode()
            elif self._mode_index == 3:
                self._setup_send2_mode()
            else:
                assert False

            if self._update_callback is not None:
                self._update_callback()

            self._mixer.set_allow_update(True)
            self._session.set_allow_update(True)
        else:
            self.release_controls()

    # ------------------------------------------------------------------ #
    # Sub-mode setups                                                      #
    # ------------------------------------------------------------------ #

    def _setup_mixer_overview(self):
        """
        Set up the overview layout.

        Each column shows 8 buttons: Vol/Pan/Send1/Send2/Stop/Mute/Solo/Arm.
        Side buttons: Stop All, Unmute All, Unsolo All, Unarm All.
        """
        stop_buttons = []
        for track in range(self._matrix.width()):
            strip = self._mixer.channel_strip(track)
            # Clear all controls before reassigning
            strip.set_send_controls((None, None))
            strip.set_pan_control(None)
            strip.set_volume_control(None)
            self._sliders[track].release_parameter()

            # Assign button colours row by row
            for row in range(self._matrix.height()):
                colours = ["Mixer.Volume", "Mixer.Pan", "Mixer.Sends",
                           "Mixer.Sends", "Mixer.Stop", "Mixer.Mute",
                           "Mixer.Solo", "Mixer.Arm"]
                self._matrix.get_button(track, row).set_on_off_values(colours[row])

            # Wire the per-track buttons
            strip.set_default_buttons(
                self._matrix.get_button(track, 0),  # Vol default
                self._matrix.get_button(track, 1),  # Pan default
                self._matrix.get_button(track, 2),  # Send1 default
                self._matrix.get_button(track, 3))  # Send2 default
            stop_buttons.append(self._matrix.get_button(track, 4))
            strip.set_mute_button(self._matrix.get_button(track, 5))
            strip.set_solo_button(self._matrix.get_button(track, 6))
            strip.set_arm_button(self._matrix.get_button(track, 7))

            # Side buttons: Stop All, Unmute All, Unsolo All, Unarm All
            for button in self._side_buttons:
                idx = list(self._side_buttons).index(button)
                labels = ["Mixer.Stop", "Mixer.Mute", "Mixer.Solo", "Mixer.Arm"]
                button.set_on_off_values(labels[idx])

            button.force_next_send()
            button.turn_off()

        self._session.set_stop_track_clip_buttons(tuple(stop_buttons))
        self._session.set_stop_all_clips_button(self._side_buttons[0])
        self._mixer.set_global_buttons(
            self._side_buttons[3],   # Unarm All
            self._side_buttons[2],   # Unsolo All
            self._side_buttons[1])   # Unmute All

    def _setup_volume_mode(self):
        """
        Wire all columns as volume sliders.

        Uses SLIDER_MODE_VOLUME (cumulative bar graph) with VOL_VALUE_MAP.
        """
        for track in range(self._matrix.width()):
            strip = self._mixer.channel_strip(track)
            strip.set_default_buttons(None, None, None, None)
            strip.set_mute_button(None)
            strip.set_solo_button(None)
            strip.set_arm_button(None)
            strip.set_send_controls((None, None))
            strip.set_pan_control(None)
            for row in range(self._matrix.height()):
                self._matrix.get_button(track, row).set_on_off_values("Mixer.VolumeSlider")
            self._sliders[track].set_mode(SLIDER_MODE_VOLUME)
            self._sliders[track].set_value_map(VOL_VALUE_MAP)
            strip.set_volume_control(self._sliders[track])
        self._session.set_stop_track_clip_buttons(None)
        self._session.set_stop_all_clips_button(None)
        self._mixer.set_global_buttons(None, None, None)

    def _setup_pan_mode(self):
        """
        Wire all columns as pan sliders.

        Uses SLIDER_MODE_PAN (centred indicator) with PAN_VALUE_MAP.
        """
        for track in range(self._matrix.width()):
            strip = self._mixer.channel_strip(track)
            strip.set_default_buttons(None, None, None, None)
            strip.set_mute_button(None)
            strip.set_solo_button(None)
            strip.set_arm_button(None)
            strip.set_send_controls((None, None))
            strip.set_volume_control(None)
            for row in range(self._matrix.height()):
                self._matrix.get_button(track, row).set_on_off_values("Mixer.PanSlider")
            self._sliders[track].set_mode(SLIDER_MODE_PAN)
            self._sliders[track].set_value_map(PAN_VALUE_MAP)
            strip.set_pan_control(self._sliders[track])
        self._session.set_stop_track_clip_buttons(None)
        self._session.set_stop_all_clips_button(None)
        self._mixer.set_global_buttons(None, None, None)

    def _setup_send1_mode(self):
        """Wire all columns as Send A sliders using SEND_VALUE_MAP."""
        for track in range(self._matrix.width()):
            strip = self._mixer.channel_strip(track)
            strip.set_default_buttons(None, None, None, None)
            strip.set_mute_button(None)
            strip.set_solo_button(None)
            strip.set_arm_button(None)
            strip.set_volume_control(None)
            strip.set_pan_control(None)
            for row in range(self._matrix.height()):
                self._matrix.get_button(track, row).set_on_off_values("Mixer.SendsSlider_1")
            self._sliders[track].set_mode(SLIDER_MODE_VOLUME)
            self._sliders[track].set_value_map(SEND_VALUE_MAP)
            strip.set_send_controls((self._sliders[track], None))
        self._session.set_stop_track_clip_buttons(None)
        self._session.set_stop_all_clips_button(None)
        self._mixer.set_global_buttons(None, None, None)

    def _setup_send2_mode(self):
        """Wire all columns as Send B sliders using SEND_VALUE_MAP."""
        for track in range(self._matrix.width()):
            strip = self._mixer.channel_strip(track)
            strip.set_default_buttons(None, None, None, None)
            strip.set_mute_button(None)
            strip.set_solo_button(None)
            strip.set_arm_button(None)
            strip.set_volume_control(None)
            strip.set_pan_control(None)
            for row in range(self._matrix.height()):
                self._matrix.get_button(track, row).set_on_off_values("Mixer.SendsSlider_2")
            self._sliders[track].set_mode(SLIDER_MODE_VOLUME)
            self._sliders[track].set_value_map(SEND_VALUE_MAP)
            strip.set_send_controls((None, self._sliders[track]))
        self._session.set_stop_track_clip_buttons(None)
        self._session.set_stop_all_clips_button(None)
        self._mixer.set_global_buttons(None, None, None)
