"""
SpecialSessionComponent.py — Session component with OSD and MK2 RGB support.

Extends the standard ``_Framework`` ``SessionComponent`` to:
  - Use :class:`~ClipSlotMK2.ClipSlotMK2` for MK2/MK3/LPX hardware so that
    clip LEDs can use the full RGB palette with blink and pulse effects.
  - Push track names to the OSD whenever the session view changes.
  - Support multi-launchpad session linking via :meth:`link_with_track_offset`.
"""

from _Framework.SessionComponent import SessionComponent
from .ClipSlotMK2 import ClipSlotMK2
from _Framework.SceneComponent import SceneComponent
import Live


class SpecialSessionComponent(SessionComponent):
    """
    Session component with OSD integration and MK2 clip-colour support.

    On MK2/MK3/LPX hardware the ``SceneComponent.clip_slot_component_type``
    is patched to :class:`~ClipSlotMK2.ClipSlotMK2` before calling the parent
    constructor so that all clip slots created for this session use the
    enhanced feedback class.

    Attributes:
        _stop_clip_buttons: Passed in at construction; kept for reference.
        _control_surface: The owning Launchpad control surface.
        _main_selector (MainSelectorComponent): Used to check the current mode
            index so OSD updates only fire in session mode (index 0).
        _osd (M4LInterface | None): On-Screen Display bridge.
    """

    def __init__(self, num_tracks, num_scenes, stop_clip_buttons,
                 control_surface, main_selector):
        """
        Initialise the session component.

        For MK2/MK3/LPX hardware, patches the clip slot type and enables
        RGB clip colour mapping.

        Args:
            num_tracks (int): Number of track columns in the session grid.
            num_scenes (int): Number of scene rows in the session grid.
            stop_clip_buttons: Stop-clip button row (or None).
            control_surface: The owning Launchpad control surface.
            main_selector (MainSelectorComponent): Mode selector reference.
        """
        self._stop_clip_buttons = stop_clip_buttons
        self._control_surface = control_surface
        self._main_selector = main_selector
        self._osd = None

        # Use enhanced MK2 clip slots on colour-capable hardware
        if (self._control_surface._lpx
                or self._control_surface._mk3_rgb
                or self._control_surface._mk2_rgb):
            SceneComponent.clip_slot_component_type = ClipSlotMK2

        SessionComponent.__init__(
            self,
            num_tracks=num_tracks,
            num_scenes=num_scenes,
            enable_skinning=True,
            name='Session',
            is_root=True)

        # Register clip-colour tables so Live shows matching colours in clips
        if (self._control_surface._lpx
                or self._control_surface._mk3_rgb
                or self._control_surface._mk2_rgb):
            from .ColorsMK2 import CLIP_COLOR_TABLE, RGB_COLOR_TABLE
            self.set_rgb_mode(CLIP_COLOR_TABLE, RGB_COLOR_TABLE)

    # ------------------------------------------------------------------ #
    # Multi-launchpad session linking                                      #
    # ------------------------------------------------------------------ #

    def link_with_track_offset(self, track_offset):
        """
        Link this session to a shared horizontal position.

        Used when multiple Launchpad95 instances are combined side-by-side so
        they each show a different track window.

        Args:
            track_offset (int): Starting track index for this session.
        """
        assert track_offset >= 0
        if self._is_linked():
            self._unlink()
        self.set_offsets(track_offset, 0)
        self._link()

    def unlink(self):
        """Unlink from a combined multi-launchpad session."""
        if self._is_linked():
            self._unlink()

    # ------------------------------------------------------------------ #
    # Stop-clip LED                                                        #
    # ------------------------------------------------------------------ #

    def _update_stop_clips_led(self, index):
        """
        Update the stop-clip button LED for a given track column.

        Shows a triggered, playing, or empty state based on the track's
        fired slot index.

        Args:
            index (int): Zero-based track column index.
        """
        if (self.is_enabled()
                and self._stop_track_clip_buttons is not None
                and index < len(self._stop_track_clip_buttons)):
            button = self._stop_track_clip_buttons[index]
            tracks_to_use = self.tracks_to_use()
            track_index = index + self.track_offset()
            if 0 <= track_index < len(tracks_to_use):
                track = tracks_to_use[track_index]
                if track.fired_slot_index == -2:
                    # Clip is queued to stop
                    button.send_value(self._stop_clip_triggered_value)
                elif track.playing_slot_index >= 0:
                    # A clip is currently playing
                    button.send_value(self._stop_clip_value)
                else:
                    button.turn_off()
            else:
                # Track index is out of range — dim the button
                button.send_value(4)

    # ------------------------------------------------------------------ #
    # OSD integration                                                      #
    # ------------------------------------------------------------------ #

    def set_osd(self, osd):
        """
        Attach the OSD data bridge.

        Args:
            osd (M4LInterface): Shared OSD container.
        """
        self._osd = osd

    def _update_OSD(self):
        """
        Push current session track names to the OSD.

        Writes up to ``_num_tracks`` track names into ``osd.attribute_names``.
        """
        if self._osd is not None:
            self._osd.mode = "Session"
            for i in range(self._num_tracks):
                self._osd.attribute_names[i] = " "
                self._osd.attributes[i] = " "

            tracks = self.tracks_to_use()
            idx = 0
            for i in range(len(tracks)):
                if idx < self._num_tracks and len(tracks) > i + self._track_offset:
                    track = tracks[i + self._track_offset]
                    self._osd.attribute_names[idx] = (str(track.name)
                                                       if track is not None else " ")
                    self._osd.attributes[idx] = " "
                idx += 1

            self._osd.info[0] = " "
            self._osd.info[1] = " "
            self._osd.update()

    # ------------------------------------------------------------------ #
    # Overrides that conditionally update the OSD                         #
    # ------------------------------------------------------------------ #

    def update(self):
        """Refresh session display and OSD when in session mode."""
        SessionComponent.update(self)
        if self._main_selector._main_mode_index == 0:
            self._update_OSD()

    def set_enabled(self, enabled):
        """Enable/disable and refresh OSD in session mode."""
        SessionComponent.set_enabled(self, enabled)
        if self._main_selector._main_mode_index == 0:
            self._update_OSD()

    def _reassign_tracks(self):
        """Reassign tracks and refresh OSD after track-list changes."""
        SessionComponent._reassign_tracks(self)
        if self._main_selector._main_mode_index == 0:
            self._update_OSD()
