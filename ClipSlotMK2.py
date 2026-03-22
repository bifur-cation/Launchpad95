"""
ClipSlotMK2.py — Enhanced clip-slot component for MK2/MK3/LPX hardware.

Overrides the standard ``ClipSlotComponent`` so that clip LED feedback can
use the full MK2 RGB palette including the :class:`~ColorsMK2.Blink` and
:class:`~ColorsMK2.Pulse` colour types.

The base ``ClipSlotComponent.update()`` sends integer velocity values and
does not understand the channel-based blink/pulse protocol.  This subclass
intercepts the feedback value, distinguishing between:
  - ``None`` / ``-1``     → LED off.
  - Integer 0–127         → direct MIDI note-on with optional channel override
                             (used for blink on ch.1 and pulse on ch.2).
  - Skin colour string    → resolved through ``button.set_light()``.
"""

from _Framework.ClipSlotComponent import ClipSlotComponent
from _Framework.Util import in_range


class ClipSlotMK2(ClipSlotComponent):
    """
    Clip slot with MK2-aware LED feedback.

    Replaces the default ``update()`` method to handle the dictionary-style
    feedback value returned by :meth:`_feedback_value`, which carries both a
    MIDI value and a MIDI channel so that blink/pulse effects can be sent.

    No new public attributes are added beyond those of the base class.
    """

    def update(self):
        """
        Refresh the clip slot LED based on the clip's current playback state.

        Reads :meth:`_feedback_value` and sends the appropriate MIDI message:
          - If the value is ``None`` or ``-1``, the button is turned off.
          - If the value is an integer in 0–127, it is sent with the given
            channel (0 = solid, 1 = blink, 2 = pulse).
          - Otherwise the value is treated as a skin colour key string.
        """
        super(ClipSlotComponent, self).update()
        self._has_fired_slot = False
        button = self._launch_button_value.subject

        if self._allow_updates:
            if self.is_enabled() and button is not None:
                value_to_send = self._feedback_value()
                if value_to_send in (None, -1) or value_to_send["value"] in (None, -1):
                    button.turn_off()
                elif in_range(value_to_send["value"], 0, 128):
                    # Integer value: send with explicit channel for blink/pulse
                    button.force_next_send()
                    button.send_value(value_to_send["value"], channel=value_to_send["channel"])
                else:
                    # Skin colour key: delegate to set_light
                    button.force_next_send()
                    button.set_light(value_to_send["value"])
        else:
            self._update_requests += 1

    def _feedback_value(self):
        """
        Compute the LED feedback state for the current clip slot.

        Returns a dict with keys:
          - ``"value"`` (int | str): MIDI velocity (0–127) or skin colour key.
          - ``"channel"`` (int): MIDI channel (0 = solid, 1 = blink, 2 = pulse).

        Priority order (highest first):
          1. Triggered-to-record  → ``_triggered_to_record_value``
          2. Triggered-to-play    → ``_triggered_to_play_value``
          3. Recording            → ``_recording_value``
          4. Playing              → ``_started_value``
          5. Clip colour          → ``_color_value(slot.color)``
          6. Stopped              → ``_stopped_value``
          7. Record-button armed  → ``_record_button_value``

        Returns:
            dict | None: Feedback dict, or ``None`` if no clip slot is assigned.
        """
        if self._clip_slot is None:
            return None

        ret = {"value": 0, "channel": 0}
        track = self._clip_slot.canonical_parent
        slot_or_clip = self._clip_slot.clip if self.has_clip() else self._clip_slot

        # Default: show "stopped" colour if the slot controls other clips
        if getattr(slot_or_clip, 'controls_other_clips', True) and self._stopped_value is not None:
            ret["value"] = self._stopped_value

        # Armed track with stop button → show record-button colour
        if self._track_is_armed(track) and self._clip_slot.has_stop_button and self._record_button_value is not None:
            ret["value"] = self._record_button_value

        if slot_or_clip.color is not None:
            # Clip has an explicit colour — use it and overlay playback states
            ret["value"] = self._color_value(slot_or_clip.color)
            if slot_or_clip.is_triggered:
                if slot_or_clip.will_record_on_start:
                    ret["value"] = self._triggered_to_record_value
                else:
                    ret["value"] = self._triggered_to_play_value
            elif slot_or_clip.is_playing:
                if slot_or_clip.is_recording:
                    ret["value"] = self._recording_value
                else:
                    ret["value"] = self._started_value
        else:
            # No clip colour — overlay playback states only
            if slot_or_clip.is_triggered:
                if slot_or_clip.will_record_on_start:
                    ret["value"] = self._triggered_to_record_value
                else:
                    ret["value"] = self._triggered_to_play_value
            elif slot_or_clip.is_playing:
                if slot_or_clip.is_recording:
                    ret["value"] = self._recording_value
                else:
                    ret["value"] = self._started_value

        return ret
