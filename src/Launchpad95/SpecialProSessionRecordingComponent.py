# imported from https://github.com/poltow/Launchpad97
"""
SpecialProSessionRecordingComponent.py — Session recording for Pro Session mode.

Extends :class:`_Framework.SessionRecordingComponent.SessionRecordingComponent`
to hook into the Pro Session mode record behaviour used by
:class:`~SpecialProSessionComponent.SpecialProSessionComponent`.

In normal session record mode the record button simply starts/stops recording.
In Pro record mode (``_is_record_mode = True``) the component checks whether
the target track can record and, if so, triggers a fixed-length session record
if fixed length is enabled; otherwise it falls back to standard
start/stop behaviour.

The fixed-length and launch-quantisation settings are delegated to the parent
:class:`~SpecialProSessionComponent.SpecialProSessionComponent` via
:meth:`_is_fixed_length_on`, :meth:`_get_fixed_length`, and
:meth:`_get_launch_quant`.
"""

import Live
from _Framework.ClipCreator import ClipCreator
from _Framework.SessionRecordingComponent import (
    SessionRecordingComponent, track_playing_slot, track_is_recording
)

_Q = Live.Song.Quantization


class SpecialProSessionRecordingComponent(SessionRecordingComponent):
    """
    Session recording component with Pro Session mode support.

    Attributes:
        _control_surface: The owning Launchpad control surface used for
            status messages.
        _target_track_component (TargetTrackComponent): Provides the track
            that should receive the next recording.
        _is_record_mode (bool): When ``True``, the record button uses Pro mode
            logic (fixed-length / quantised triggers) rather than simple
            start/stop.
        _parent: The owning :class:`~SpecialProSessionComponent.SpecialProSessionComponent`;
            set via :meth:`_set_parent` after construction.
    """

    def __init__(self, target_track_component, control_surface, *a, **k):
        """
        Create the component and initialise the ClipCreator.

        Args:
            target_track_component (TargetTrackComponent): Provides the
                currently targeted Live track.
            control_surface: The owning Launchpad control surface.
        """
        self._control_surface = control_surface
        self._target_track_component = target_track_component
        super(SpecialProSessionRecordingComponent, self).__init__(
            ClipCreator(), True, *a, **k)
        self._is_record_mode = False

    def _set_parent(self, parent):
        """
        Inject the parent SpecialProSessionComponent reference.

        Called by :class:`~SpecialProSessionComponent.SpecialProSessionComponent`
        after both objects have been constructed.

        Args:
            parent (SpecialProSessionComponent): The owning session component.
        """
        self._parent = parent

    def set_record_mode(self, record_mode):
        """
        Toggle Pro record mode.

        Args:
            record_mode (bool): ``True`` to use Pro mode logic on record press.
        """
        self._is_record_mode = record_mode

    # ------------------------------------------------------------------ #
    # Settings delegated to the parent component                          #
    # ------------------------------------------------------------------ #

    def _is_fixed_length_on(self):
        """Delegate to the parent's fixed-length enabled state."""
        return self._parent._is_fixed_length_on()

    def set_enabled(self, enable):
        """Enable or disable this component."""
        super(SpecialProSessionRecordingComponent, self).set_enabled(enable)

    def _get_fixed_length(self):
        """Delegate to the parent's fixed-length value."""
        return self._parent._get_fixed_length()

    def _get_launch_quant(self):
        """Delegate to the parent's launch quantization setting."""
        return self._parent._get_launch_quant()

    # ------------------------------------------------------------------ #
    # Record button handler                                                #
    # ------------------------------------------------------------------ #

    def _on_record_button_value(self):
        """
        Handle a record button press.

        In normal mode: toggle session recording.
        In Pro mode: use :meth:`_handle_pro_mode_record_behavior`.
        """
        if self.is_enabled():
            if self._is_record_mode:
                self._handle_pro_mode_record_behavior()
            else:
                if not self._stop_recording():
                    self._start_recording()
                    self._control_surface.show_message("SESSION RECORD ON")
                else:
                    self._control_surface.show_message("SESSION RECORD OFF")

    def _handle_pro_mode_record_behavior(self):
        """
        Pro mode record logic.

        Triggers a fixed-length session record on the target track when it can
        record and session recording is not already active.  Falls back to
        normal start/stop toggling when the condition is not met.
        """
        track = self._target_track_component.target_track
        status = self.song().session_record_status
        was_recording = (status != Live.Song.SessionRecordStatus.off
                         or self.song().session_record)

        if self._track_can_record(track) and not was_recording:
            # Start a new fixed-length record if applicable
            if self._is_fixed_length_on():
                self.song().trigger_session_record(self._get_fixed_length())
            else:
                self.song().trigger_session_record()
        elif not self._stop_recording():
            self._start_recording()
            self._control_surface.show_message("SESSION RECORD ON")
        else:
            self._control_surface.show_message("SESSION RECORD OFF")
