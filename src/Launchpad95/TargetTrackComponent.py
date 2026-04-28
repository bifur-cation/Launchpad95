#Embedded file name: /Users/versonator/Jenkins/live/output/mac_64_static/Release/python-bundle/MIDI Remote Scripts/Launchpad_Pro/TargetTrackComponent.py
"""
TargetTrackComponent.py — Track targeting for note-mode components.

Determines which track should receive MIDI input from the Instrument
Controller (and other note-mode components).  The targeting logic follows
these rules in order:

1. If one or more MIDI tracks are record-armed, the *most recently armed*
   track is the target.
2. If no MIDI tracks are armed, the currently *selected* track is the target.

The component listens for arm-state and freeze-state changes on all arme-able
MIDI tracks and fires the ``target_track`` subject event whenever the target
changes, letting subscribers update their state accordingly.

Adapted from the Ableton Launchpad Pro factory script.
"""

from _Framework.SubjectSlot import Subject, subject_slot, subject_slot_group
from _Framework.ControlSurfaceComponent import ControlSurfaceComponent


class TargetTrackComponent(ControlSurfaceComponent, Subject):
    """
    Determines and publishes the "target" track for note-mode input.

    Subscribes to:
      - ``song().tracks``      via :meth:`_on_tracks_changed`
      - Each armable MIDI track's ``arm`` state via :meth:`_on_arm_changed`
      - Each armable MIDI track's ``is_frozen`` state via
        :meth:`_on_frozen_state_changed`

    Fires the ``"target_track"`` subject event when the target changes.

    Class Attributes:
        __subject_events__ (tuple[str]): Names of events this component fires.

    Attributes:
        _target_track: The currently targeted :class:`Live.Track.Track`,
            or ``None`` before the first update.
        _armed_track_stack (list): Ordered list of tracks that are currently
            armed (most recently armed last).
    """

    __subject_events__ = ('target_track',)
    _target_track = None
    _armed_track_stack = []

    def __init__(self, *a, **k):
        super(TargetTrackComponent, self).__init__(*a, **k)
        # Start listening for track list changes immediately
        self._on_tracks_changed.subject = self.song()
        self._on_tracks_changed()

    @property
    def target_track(self):
        """
        The currently targeted Live track.

        Returns:
            Live.Track.Track | None: The track receiving note-mode input.
        """
        return self._target_track

    def on_selected_track_changed(self):
        """
        Called by the framework when the user changes the selected track.

        If no tracks are armed, the selected track becomes the new target.
        """
        if not self._armed_track_stack:
            self._set_target_track()

    # ------------------------------------------------------------------ #
    # Subject slot listeners                                               #
    # ------------------------------------------------------------------ #

    @subject_slot('tracks')
    def _on_tracks_changed(self):
        """
        Rebuild arm/freeze listeners whenever the track list changes.

        Filters to only armable MIDI tracks since those are the only
        candidates for the target.
        """
        tracks = filter(lambda t: t.can_be_armed and t.has_midi_input, self.song().tracks)
        self._on_arm_changed.replace_subjects(tracks)
        self._on_frozen_state_changed.replace_subjects(tracks)
        self._refresh_armed_track_stack(tracks)

    @subject_slot_group('arm')
    def _on_arm_changed(self, track):
        """
        Update the armed-track stack when a track's arm state changes.

        When a track is armed it is pushed onto the stack; when disarmed it
        is removed.  The most recently armed track is always used as target.

        Args:
            track (Live.Track.Track): The track whose arm state changed.
        """
        if track in self._armed_track_stack:
            self._armed_track_stack.remove(track)
        if track.arm:
            self._armed_track_stack.append(track)
            self._set_target_track(track)
        else:
            self._set_target_track()

    @subject_slot_group('is_frozen')
    def _on_frozen_state_changed(self, track):
        """
        Remove a frozen track from the target candidates.

        Frozen tracks cannot be armed or receive MIDI, so they are dropped
        from the stack.

        Args:
            track (Live.Track.Track): The track whose freeze state changed.
        """
        if track in self._armed_track_stack:
            self._armed_track_stack.remove(track)
        if track == self._target_track:
            self._set_target_track()

    # ------------------------------------------------------------------ #
    # Target selection helpers                                             #
    # ------------------------------------------------------------------ #

    def _set_target_track(self, target=None):
        """
        Set the target track and notify listeners if it changed.

        Args:
            target (Live.Track.Track | None): If provided, use this track
                directly.  If ``None``, derive the target from the armed
                stack or the current selection.
        """
        new_target = self._target_track
        if target is None:
            if self._armed_track_stack:
                # Most recently armed track is at the top of the stack
                new_target = self._armed_track_stack[-1]
            else:
                new_target = self.song().view.selected_track
        else:
            new_target = target

        if self._target_track != new_target:
            self._target_track = new_target
        self.notify_target_track()

    def _refresh_armed_track_stack(self, all_tracks):
        """
        Synchronise the armed-track stack with the actual arm state of all tracks.

        Removes stale entries for tracks that are no longer in the track list
        or are no longer armed, and adds any newly armed tracks.

        Args:
            all_tracks (iterable): Current set of armable MIDI tracks.
        """
        # Remove tracks that no longer exist
        for track in self._armed_track_stack:
            if track not in all_tracks:
                self._armed_track_stack.remove(track)

        # Add any armed tracks not already tracked
        for track in all_tracks:
            if track.arm and track not in self._armed_track_stack:
                self._armed_track_stack.append(track)

        self._set_target_track()
