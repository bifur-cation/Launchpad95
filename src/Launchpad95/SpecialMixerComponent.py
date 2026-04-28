"""
SpecialMixerComponent.py — Extended mixer component with global track actions.

Extends the standard ``_Framework`` ``MixerComponent`` to add three
"global action" buttons:

- **Unarm all**: Disarms every armable track in the song.
- **Unsolo all**: Clears solo on every regular and return track.
- **Unmute all**: Unmutes every regular and return track.

Also connects the On-Screen Display (OSD) and overrides the channel strip
factory so that the custom :class:`~DefChannelStripComponent.DefChannelStripComponent`
(which includes default-value reset buttons) is used instead of the plain
framework strip.
"""

from _Framework.MixerComponent import MixerComponent
from .DefChannelStripComponent import DefChannelStripComponent
from _Framework.ButtonElement import ButtonElement


class SpecialMixerComponent(MixerComponent):
    """
    Mixer component with global unarm/unsolo/unmute action buttons and OSD.

    Attributes:
        _osd (M4LInterface | None): On-Screen Display bridge used to push
            track name info to a Max for Live patch.
        _unarm_all_button (ButtonElement | None): Button that disarms all tracks.
        _unsolo_all_button (ButtonElement | None): Button that unsolos all tracks.
        _unmute_all_button (ButtonElement | None): Button that unmutes all tracks.
    """

    def __init__(self, num_tracks, num_returns=0):
        """
        Initialise the mixer.

        Args:
            num_tracks (int): Number of visible track strips to create.
            num_returns (int): Number of return track strips (usually 0).
        """
        self._osd = None
        MixerComponent.__init__(self, num_tracks, num_returns)
        self._unarm_all_button = None
        self._unsolo_all_button = None
        self._unmute_all_button = None

    def disconnect(self):
        """Remove global-button listeners and delegate to parent."""
        if self._unarm_all_button is not None:
            self._unarm_all_button.remove_value_listener(self._unarm_all_value)
            self._unarm_all_button = None
        if self._unsolo_all_button is not None:
            self._unsolo_all_button.remove_value_listener(self._unsolo_all_value)
            self._unsolo_all_button = None
        if self._unmute_all_button is not None:
            self._unmute_all_button.remove_value_listener(self._unmute_all_value)
            self._unmute_all_button = None
        MixerComponent.disconnect(self)

    # ------------------------------------------------------------------ #
    # Global action buttons                                                #
    # ------------------------------------------------------------------ #

    def set_global_buttons(self, unarm_all, unsolo_all, unmute_all):
        """
        Assign (or clear) the three global action buttons.

        Passing ``None`` for any argument removes the corresponding listener
        and hides the button.

        Args:
            unarm_all (ButtonElement | None): Disarms all tracks on press.
            unsolo_all (ButtonElement | None): Unsolos all tracks on press.
            unmute_all (ButtonElement | None): Unmutes all tracks on press.
        """
        assert isinstance(unarm_all, (ButtonElement, type(None)))
        assert isinstance(unsolo_all, (ButtonElement, type(None)))
        assert isinstance(unmute_all, (ButtonElement, type(None)))

        # Unarm all button
        if self._unarm_all_button is not None:
            self._unarm_all_button.remove_value_listener(self._unarm_all_value)
        self._unarm_all_button = unarm_all
        if self._unarm_all_button is not None:
            self._unarm_all_button.add_value_listener(self._unarm_all_value)
            self._unarm_all_button.turn_off()

        # Unsolo all button
        if self._unsolo_all_button is not None:
            self._unsolo_all_button.remove_value_listener(self._unsolo_all_value)
        self._unsolo_all_button = unsolo_all
        if self._unsolo_all_button is not None:
            self._unsolo_all_button.add_value_listener(self._unsolo_all_value)
            self._unsolo_all_button.turn_off()

        # Unmute all button
        if self._unmute_all_button is not None:
            self._unmute_all_button.remove_value_listener(self._unmute_all_value)
        self._unmute_all_button = unmute_all
        if self._unmute_all_button is not None:
            self._unmute_all_button.add_value_listener(self._unmute_all_value)
            self._unmute_all_button.turn_off()

    # ------------------------------------------------------------------ #
    # Channel strip factory                                                #
    # ------------------------------------------------------------------ #

    def _create_strip(self):
        """
        Factory method: create a DefChannelStripComponent for each mixer column.

        Returns:
            DefChannelStripComponent: Strip with default-value reset buttons.
        """
        return DefChannelStripComponent()

    # ------------------------------------------------------------------ #
    # OSD integration                                                      #
    # ------------------------------------------------------------------ #

    def set_osd(self, osd):
        """
        Attach the On-Screen Display bridge.

        Args:
            osd (M4LInterface): Shared OSD data container.
        """
        self._osd = osd

    def update(self):
        """Refresh the mixer and push track names to the OSD."""
        MixerComponent.update(self)
        if self._is_enabled:
            self._update_OSD()

    def set_enabled(self, enabled):
        """Enable or disable the mixer and update the OSD."""
        MixerComponent.set_enabled(self, enabled)
        if enabled:
            self._update_OSD()

    def _reassign_tracks(self):
        """Reassign tracks and refresh OSD after track list changes."""
        MixerComponent._reassign_tracks(self)
        if self._is_enabled:
            self._update_OSD()

    def _update_OSD(self):
        """
        Push current mixer track names to the OSD.

        Writes up to 8 track names into ``osd.attribute_names`` and clears
        the info lines.  Calls ``osd.update()`` to notify any M4L listener.
        """
        if self._osd is not None:
            self._osd.mode = "Mixer"
            for i in range(8):
                self._osd.attribute_names[i] = " "
                self._osd.attributes[i] = " "

            tracks = self.tracks_to_use()
            idx = 0
            for i in range(len(tracks)):
                if idx < 8 and len(tracks) > i + self._track_offset:
                    track = tracks[i + self._track_offset]
                    self._osd.attribute_names[idx] = str(track.name) if track is not None else " "
                    self._osd.attributes[idx] = " "
                idx += 1

            self._osd.info[0] = " "
            self._osd.info[1] = " "
            self._osd.update()

    # ------------------------------------------------------------------ #
    # Global action value handlers                                         #
    # ------------------------------------------------------------------ #

    def _unarm_all_value(self, value):
        """
        Disarm every armable track in the song.

        Args:
            value (int): MIDI velocity; non-zero = button pressed.
        """
        assert self._unarm_all_button is not None
        assert value in range(128)
        if self.is_enabled():
            if value != 0 or not self._unarm_all_button.is_momentary():
                for track in self.song().tracks:
                    if track.can_be_armed and track.arm:
                        track.arm = False

    def _unsolo_all_value(self, value):
        """
        Clear solo on every regular and return track.

        Args:
            value (int): MIDI velocity; non-zero = button pressed.
        """
        assert self._unsolo_all_button is not None
        assert value in range(128)
        if self.is_enabled():
            if value != 0 or not self._unsolo_all_button.is_momentary():
                for track in tuple(self.song().tracks) + tuple(self.song().return_tracks):
                    if track.solo:
                        track.solo = False

    def _unmute_all_value(self, value):
        """
        Unmute every regular and return track.

        Args:
            value (int): MIDI velocity; non-zero = button pressed.
        """
        assert self._unmute_all_button is not None
        assert value in range(128)
        if self.is_enabled():
            if value != 0 or not self._unmute_all_button.is_momentary():
                for track in tuple(self.song().tracks) + tuple(self.song().return_tracks):
                    if track.mute:
                        track.mute = False
