"""
DefChannelStripComponent.py — Channel strip with "default value" buttons.

Extends the standard ``_Framework`` ``ChannelStripComponent`` to add four
extra buttons — one each for volume, panning, send 1, and send 2 — that reset
the corresponding mixer parameter to its default value when pressed.

A lit button indicates the parameter is already at its default; a dark button
means it has been moved.  This gives the user instant visual feedback about
which parameters are at default and allows one-touch reset.

The component also inverts mute-button feedback convention (lit = muted)
and ensures solo/arm buttons reflect the correct track state including return
tracks.
"""

import Live
from _Framework.ChannelStripComponent import ChannelStripComponent
from .ConfigurableButtonElement import ConfigurableButtonElement
from itertools import chain


class DefChannelStripComponent(ChannelStripComponent):
    """
    Channel strip with default-value reset buttons for mixer parameters.

    Inherits all standard channel strip functionality (volume control,
    pan control, send controls, mute, solo, arm buttons) and adds four
    "default" buttons.

    Attributes:
        _default_volume_button (ConfigurableButtonElement | None):
            Button that resets track volume to default.  Lit when volume == default.
        _default_panning_button (ConfigurableButtonElement | None):
            Button that resets panning to default.  Lit when pan == default.
        _default_send1_button (ConfigurableButtonElement | None):
            Button that resets Send A to default.  Lit when send 1 == default.
        _default_send2_button (ConfigurableButtonElement | None):
            Button that resets Send B to default.  Lit when send 2 == default.
        _invert_mute_feedback (bool): When ``True`` (default) the mute button
            lights when the track IS muted (inverted from the framework default).
    """

    def __init__(self):
        ChannelStripComponent.__init__(self)
        self._default_volume_button = None
        self._default_panning_button = None
        self._default_send1_button = None
        self._default_send2_button = None
        # Invert mute feedback: button lit = track muted (more intuitive)
        self._invert_mute_feedback = True

    def disconnect(self):
        """Remove all value listeners and release parameter references."""
        # Remove parameter listeners on the current track
        if self._track is not None:
            volume = self._track.mixer_device.volume
            panning = self._track.mixer_device.panning
            sends = self._track.mixer_device.sends
            if volume.value_has_listener(self._on_volume_changed):
                volume.remove_value_listener(self._on_volume_changed)
            if panning.value_has_listener(self._on_panning_changed):
                panning.remove_value_listener(self._on_panning_changed)
            if len(sends) > 0 and sends[0].value_has_listener(self._on_send1_changed):
                sends[0].remove_value_listener(self._on_send1_changed)
            if len(sends) > 1 and sends[1].value_has_listener(self._on_send2_changed):
                sends[1].remove_value_listener(self._on_send2_changed)

        # Remove default-button listeners
        if self._default_volume_button is not None:
            self._default_volume_button.remove_value_listener(self._default_volume_value)
            self._default_volume_button = None
        if self._default_panning_button is not None:
            self._default_panning_button.remove_value_listener(self._default_panning_value)
            self._default_panning_button = None
        if self._default_send1_button is not None:
            self._default_send1_button.remove_value_listener(self._default_send1_value)
            self._default_send1_button = None
        if self._default_send2_button is not None:
            self._default_send2_button.remove_value_listener(self._default_send2_value)
            self._default_send2_button = None

        ChannelStripComponent.disconnect(self)

    # ------------------------------------------------------------------ #
    # Track assignment                                                     #
    # ------------------------------------------------------------------ #

    def set_track(self, track):
        """
        Assign a Live track to this channel strip.

        Removes listeners from the old track before installing them on the
        new one.  If the same track is assigned again, just refreshes the UI.

        Args:
            track (Live.Track.Track | None): The track to control, or ``None``
                to clear the strip.
        """
        assert track is None or isinstance(track, Live.Track.Track)
        if track != self._track:
            if self._track is not None:
                # Remove listeners from old track
                volume = self._track.mixer_device.volume
                panning = self._track.mixer_device.panning
                sends = self._track.mixer_device.sends
                if volume.value_has_listener(self._on_volume_changed):
                    volume.remove_value_listener(self._on_volume_changed)
                if panning.value_has_listener(self._on_panning_changed):
                    panning.remove_value_listener(self._on_panning_changed)
                if len(sends) > 0 and sends[0].value_has_listener(self._on_send1_changed):
                    sends[0].remove_value_listener(self._on_send1_changed)
                if len(sends) > 1 and sends[1].value_has_listener(self._on_send2_changed):
                    sends[1].remove_value_listener(self._on_send2_changed)
            ChannelStripComponent.set_track(self, track)
        else:
            self.update()

    # ------------------------------------------------------------------ #
    # Default buttons                                                      #
    # ------------------------------------------------------------------ #

    def set_default_buttons(self, volume, panning, send1, send2):
        """
        Assign the four default-value reset buttons.

        Passing ``None`` for any button removes the corresponding listener.

        Args:
            volume (ConfigurableButtonElement | None): Resets track volume.
            panning (ConfigurableButtonElement | None): Resets panning.
            send1 (ConfigurableButtonElement | None): Resets Send A.
            send2 (ConfigurableButtonElement | None): Resets Send B.
        """
        assert volume is None or isinstance(volume, ConfigurableButtonElement)
        assert panning is None or isinstance(panning, ConfigurableButtonElement)
        assert send1 is None or isinstance(send1, ConfigurableButtonElement)
        assert send2 is None or isinstance(send2, ConfigurableButtonElement)

        if volume != self._default_volume_button:
            if self._default_volume_button is not None:
                self._default_volume_button.remove_value_listener(self._default_volume_value)
            self._default_volume_button = volume
            if self._default_volume_button is not None:
                self._default_volume_button.add_value_listener(self._default_volume_value)

        if panning != self._default_panning_button:
            if self._default_panning_button is not None:
                self._default_panning_button.remove_value_listener(self._default_panning_value)
            self._default_panning_button = panning
            if self._default_panning_button is not None:
                self._default_panning_button.add_value_listener(self._default_panning_value)

        if send1 != self._default_send1_button:
            if self._default_send1_button is not None:
                self._default_send1_button.remove_value_listener(self._default_send1_value)
            self._default_send1_button = send1
            if self._default_send1_button is not None:
                self._default_send1_button.add_value_listener(self._default_send1_value)

        if send2 != self._default_send2_button:
            if self._default_send2_button is not None:
                self._default_send2_button.remove_value_listener(self._default_send2_value)
            self._default_send2_button = send2
            if self._default_send2_button is not None:
                self._default_send2_button.add_value_listener(self._default_send2_value)

        self.update()

    def set_send_controls(self, controls):
        """
        Assign send controls and reset them on change.

        Args:
            controls (tuple | None): A tuple of control elements for sends.
        """
        assert controls is None or isinstance(controls, tuple)
        if controls != self._send_controls:
            self._send_controls = controls
            if self._send_controls is not None:
                for control in self._send_controls:
                    if control is not None:
                        control.reset()
            self.update()

    # ------------------------------------------------------------------ #
    # UI update                                                            #
    # ------------------------------------------------------------------ #

    def update(self):
        """
        Refresh all button LEDs to reflect the current track state.

        Installs parameter change listeners on the new track and immediately
        queries the current values.  Resets all controls if no track is
        assigned.
        """
        ChannelStripComponent.update(self)
        if self._allow_updates:
            if self.is_enabled():
                if self._track is not None:
                    volume = self._track.mixer_device.volume
                    panning = self._track.mixer_device.panning
                    sends = self._track.mixer_device.sends

                    # Register value listeners for continuous feedback
                    if not volume.value_has_listener(self._on_volume_changed):
                        volume.add_value_listener(self._on_volume_changed)
                    if not panning.value_has_listener(self._on_panning_changed):
                        panning.add_value_listener(self._on_panning_changed)
                    if len(sends) > 0:
                        if not sends[0].value_has_listener(self._on_send1_changed):
                            sends[0].add_value_listener(self._on_send1_changed)
                        self._on_send1_changed()
                    elif self._default_send1_button is not None:
                        self._default_send1_button.turn_off()
                    if len(sends) > 1:
                        if not sends[1].value_has_listener(self._on_send2_changed):
                            sends[1].add_value_listener(self._on_send2_changed)
                        self._on_send2_changed()
                    elif self._default_send2_button is not None:
                        self._default_send2_button.turn_off()

                    self._on_volume_changed()
                    self._on_panning_changed()
                else:
                    # No track — reset everything
                    for btn in (self._default_volume_button,
                                self._default_panning_button,
                                self._default_send1_button,
                                self._default_send2_button,
                                self._mute_button,
                                self._arm_button,
                                self._solo_button,
                                self._volume_control,
                                self._pan_control):
                        if btn is not None:
                            btn.reset()
                    if self._send_controls is not None:
                        for send_control in self._send_controls:
                            if send_control is not None:
                                send_control.reset()

    # ------------------------------------------------------------------ #
    # Default button handlers                                              #
    # ------------------------------------------------------------------ #

    def _default_volume_value(self, value):
        """Reset track volume to default when button is pressed."""
        assert self._default_volume_button is not None
        assert value in range(128)
        if self.is_enabled() and self._track is not None:
            if value != 0 or not self._default_volume_button.is_momentary():
                volume = self._track.mixer_device.volume
                if volume.is_enabled:
                    volume.value = volume.default_value

    def _default_panning_value(self, value):
        """Reset track panning to default when button is pressed."""
        assert self._default_panning_button is not None
        assert value in range(128)
        if self.is_enabled() and self._track is not None:
            if value != 0 or not self._default_panning_button.is_momentary():
                panning = self._track.mixer_device.panning
                if panning.is_enabled:
                    panning.value = panning.default_value

    def _default_send1_value(self, value):
        """Reset Send A to default when button is pressed."""
        assert self._default_send1_button is not None
        assert value in range(128)
        if (self.is_enabled() and self._track is not None
                and len(self._track.mixer_device.sends) > 0):
            if value != 0 or not self._default_send1_button.is_momentary():
                send1 = self._track.mixer_device.sends[0]
                if send1.is_enabled:
                    send1.value = send1.default_value

    def _default_send2_value(self, value):
        """Reset Send B to default when button is pressed."""
        assert self._default_send2_button is not None
        assert value in range(128)
        if (self.is_enabled() and self._track is not None
                and len(self._track.mixer_device.sends) > 1):
            if value != 0 or not self._default_send2_button.is_momentary():
                send2 = self._track.mixer_device.sends[1]
                if send2.is_enabled:
                    send2.value = send2.default_value

    # ------------------------------------------------------------------ #
    # Parameter change handlers (LED feedback)                             #
    # ------------------------------------------------------------------ #

    def _on_mute_changed(self):
        """Lit when the track is muted (inverted feedback convention)."""
        if self.is_enabled() and self._mute_button is not None:
            if self._track is not None:
                if (self._track in chain(self.song().tracks, self.song().return_tracks)
                        and self._track.mute != self._invert_mute_feedback):
                    self._mute_button.turn_on()
                else:
                    self._mute_button.turn_off()
            else:
                self._mute_button.send_value(0)

    def _on_solo_changed(self):
        """Lit when the track is soloed."""
        if self.is_enabled() and self._solo_button is not None:
            if self._track is not None:
                if (self._track in chain(self.song().tracks, self.song().return_tracks)
                        and self._track.solo):
                    self._solo_button.turn_on()
                else:
                    self._solo_button.turn_off()
            else:
                self._solo_button.send_value(0)

    def _on_arm_changed(self):
        """Lit when the track is record-armed."""
        if self.is_enabled() and self._arm_button is not None:
            if self._track is not None:
                if (self._track in self.song().tracks
                        and self._track.can_be_armed
                        and self._track.arm):
                    self._arm_button.turn_on()
                else:
                    self._arm_button.turn_off()
            else:
                self._arm_button.send_value(0)

    def _on_volume_changed(self):
        """Lit when volume equals its default value."""
        assert self._track is not None
        if self.is_enabled() and self._default_volume_button is not None:
            volume = self._track.mixer_device.volume
            if volume.value == volume.default_value:
                self._default_volume_button.turn_on()
            else:
                self._default_volume_button.turn_off()

    def _on_panning_changed(self):
        """Lit when panning equals its default value."""
        assert self._track is not None
        if self.is_enabled() and self._default_panning_button is not None:
            panning = self._track.mixer_device.panning
            if panning.value == panning.default_value:
                self._default_panning_button.turn_on()
            else:
                self._default_panning_button.turn_off()

    def _on_send1_changed(self):
        """Lit when Send A equals its default value."""
        assert self._track is not None
        sends = self._track.mixer_device.sends
        assert len(sends) > 0
        if self.is_enabled() and self._default_send1_button is not None:
            send1 = sends[0]
            if send1.value == send1.default_value:
                self._default_send1_button.turn_on()
            else:
                self._default_send1_button.turn_off()

    def _on_send2_changed(self):
        """Lit when Send B equals its default value."""
        assert self._track is not None
        sends = self._track.mixer_device.sends
        assert len(sends) > 1
        if self.is_enabled() and self._default_send2_button is not None:
            send2 = sends[1]
            if send2.value == send2.default_value:
                self._default_send2_button.turn_on()
            else:
                self._default_send2_button.turn_off()
