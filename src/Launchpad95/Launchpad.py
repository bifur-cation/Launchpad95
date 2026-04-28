"""
Launchpad.py — Main Ableton Live Remote Script entry point for Novation Launchpad.

This module contains the top-level ``Launchpad`` ControlSurface class.  It implements
a two-stage initialisation pattern:

1. ``__init__``: Minimal setup; sends challenge bytes for all hardware generations
   and waits for a SysEx identity response before continuing.
2. ``init()``: Called from ``handle_sysex()`` once the hardware model has been
   identified.  Builds the full button matrix, OSD bridge, note-repeat component,
   and ``MainSelectorComponent``.

Hardware detection uses MIDI SysEx challenge/response:
- **MK1 / Mini / S**: Four CC messages on channel 0, notes 17-20; response compared
  against ``Live.Application.encrypt_challenge2()``.
- **MK2**: SysEx ``(240, 0, 32, 41, 2, 24, 64, …)``.
- **MK3 Mini / Launchpad X**: Universal Device Inquiry (SysEx 0xF0 0x7E …) with
  family codes ``(19,1)`` for Mini MK3 and ``(3,1)`` for Launchpad X.

Module-level constants
----------------------
DO_COMBINE (bool): True when multi-APC session linking is supported (Live 8.2+).
LP_MINI_MK3_ID (int): SysEx device ID byte for Mini MK3 (13).
LP_X_ID (int): SysEx device ID byte for Launchpad X (12).
SYSEX_IDENTITY_REQUEST_MESSAGE (tuple): Standard MIDI Universal Device Inquiry bytes.
NOVATION_MANUFACTURER_ID (tuple): Novation SysEx manufacturer ID bytes ``(0, 32, 41)``.
FIRMWARE_MODE_COMMAND (int): SysEx sub-command to switch firmware mode (16).
STANDALONE_MODE (int): Value for standalone (non-DAW) firmware mode (0).
STD_MSG_HEADER (tuple): Common prefix for all Novation SysEx messages.
"""

from __future__ import with_statement

import traceback

import Live
from _Framework.ControlSurface import ControlSurface
from _Framework.InputControlElement import MIDI_CC_TYPE, MIDI_NOTE_TYPE
from _Framework.ButtonElement import ButtonElement
from _Framework.ButtonMatrixElement import ButtonMatrixElement
from .ConfigurableButtonElement import ConfigurableButtonElement
from .MainSelectorComponent import MainSelectorComponent
from .NoteRepeatComponent import NoteRepeatComponent
from .M4LInterface import M4LInterface
from .Log import log
try:
    from .Settings import Settings
except ImportError:
    from .Settings import *

#fix for python3
try:
    xrange
except NameError:
    xrange = range

DO_COMBINE = Live.Application.combine_apcs()  # requires 8.2 & higher

# Hardware family / device ID constants for SysEx identity response parsing
LP_MINI_MK3_FAMILY_CODE = (19, 1)  # Family code bytes in identity response for Mini MK3
LP_MINI_MK3_ID = 13                 # SysEx device ID for Mini MK3
LP_X_FAMILY_CODE = (3, 1)           # Family code bytes in identity response for Launchpad X
LP_X_ID = 12                        # SysEx device ID for Launchpad X

# SysEx protocol constants
SYSEX_START = 240                   # 0xF0 — MIDI SysEx start byte
SYSEX_END = 247                     # 0xF7 — MIDI SysEx end byte
SYSEX_GENERAL_INFO = 6              # Sub-ID 1 for Universal System Exclusive general info
SYSEX_NON_REALTIME = 126            # 0x7E — Non-Realtime Universal SysEx prefix
SYSEX_IDENTITY_REQUEST_ID = 1       # Sub-ID 2 for Identity Request
SYSEX_IDENTITY_REQUEST_MESSAGE = (SYSEX_START,SYSEX_NON_REALTIME,127,SYSEX_GENERAL_INFO,SYSEX_IDENTITY_REQUEST_ID,SYSEX_END)
NOVATION_MANUFACTURER_ID = (0, 32, 41)  # Novation manufacturer ID (0x00 0x20 0x29)
FIRMWARE_MODE_COMMAND = 16          # SysEx sub-command: switch firmware mode
STANDALONE_MODE = 0                 # Firmware mode value: standalone (non-DAW)

# Prefix common to all Novation-specific SysEx messages: F0 00 20 29 02
STD_MSG_HEADER = (SYSEX_START,) + NOVATION_MANUFACTURER_ID + (2, )


class Launchpad(ControlSurface):
    """
    Main Ableton Live Remote Script for Novation Launchpad hardware.

    Extends ``_Framework.ControlSurface`` to support all Launchpad generations
    (MK1/Mini/S, MK2, Mini MK3, Launchpad X) through runtime hardware detection.

    Initialisation is split into two stages because hardware identity is determined
    asynchronously via SysEx challenge/response:

    Stage 1 — ``__init__``: Sends challenge bytes to all hardware generations and
    suppresses MIDI output until the hardware responds.

    Stage 2 — ``init()``: Called from ``handle_sysex()`` once the model is known.
    Builds the button matrix, creates ``MainSelectorComponent``, and enables the
    surface.

    Class Attributes:
        _active_instances (list[Launchpad]): All live ``Launchpad`` instances; used
            for multi-launchpad session linking via ``_combine_active_instances()``.

    Instance Attributes:
        _live_major_version (int): Live application major version number.
        _live_minor_version (int): Live application minor version number.
        _live_bugfix_version (int): Live application bug-fix version number.
        _selector (MainSelectorComponent | None): Top-level mode switcher; ``None``
            until ``init()`` completes.
        _lpx (bool): ``True`` when connected hardware is a Launchpad X.
        _mk2_rgb (bool): ``True`` when connected hardware is a Launchpad MK2.
        _mk3_rgb (bool): ``True`` when connected hardware is a Mini MK3.
        _skin (Skin): Colour skin for the current hardware model.
        _side_notes (tuple[int]): MIDI note/CC numbers for the 8 side buttons.
        _drum_notes (tuple[int]): MIDI note numbers mapped in drum-rack layout.
        _osd (M4LInterface): On-Screen Display data bridge for Max for Live.
        _note_repeat (NoteRepeatComponent): Note-repeat sub-component.
        _suppress_send_midi (bool): When ``True`` all ``_send_midi`` calls are dropped.
        _suppress_session_highlight (bool): Suppresses the session highlight box.
        _challenge (int): Random integer sent to hardware for challenge/response auth.
        _init_done (bool): Guard flag preventing ``init()`` from running twice.
        _config_button (ButtonElement | None): CC 0 button used to send LP config msgs.
        _user_byte_write_button (ButtonElement | None): CC 16 button for user-byte mode.
        _wrote_user_byte (bool): Set to ``True`` after writing the user-byte value to
            suppress the echoed response.
    """

	_active_instances = []

	def __init__(self, c_instance):
		"""
		Stage-1 initialisation: set minimal state and send hardware challenge bytes.

		All MIDI output is suppressed until ``handle_sysex()`` receives a valid
		response from the hardware and calls ``init()``.

		Args:
			c_instance: The Ableton Live control surface instance provided by the host.
		"""
		ControlSurface.__init__(self, c_instance)
		live = Live.Application.get_application()
		self._live_major_version = live.get_major_version()
		self._live_minor_version = live.get_minor_version()
		self._live_bugfix_version = live.get_bugfix_version()
		self._selector = None #needed because update hardware is called.
		self._lpx = False
		self._mk2_rgb = False
		self._mk3_rgb = False
		with self.component_guard():
			self._suppress_send_midi = True
			self._suppress_session_highlight = True
			self._suggested_input_port = ("Launchpad", "Launchpad Mini", "Launchpad S", "Launchpad MK2", "Launchpad X", "Launchpad Mini MK3")
			self._suggested_output_port = ("Launchpad", "Launchpad Mini", "Launchpad S", "Launchpad MK2", "Launchpad X", "Launchpad Mini MK3")
			self._control_is_with_automap = False
			self._user_byte_write_button = None
			self._config_button = None
			self._wrote_user_byte = False
			# Random 28-bit challenge value masked to 7-bit bytes for SysEx
			self._challenge = Live.Application.get_random_int(0, 400000000) & 2139062143
			self._init_done = False
		# caller will send challenge and we will continue as challenge is received.
		
			
	def init(self):
		"""
		Stage-2 initialisation: build the full surface after hardware model is known.

		Called from ``handle_sysex()`` once the hardware challenge/response has been
		validated and ``_lpx``, ``_mk2_rgb``, or ``_mk3_rgb`` has been set.

		Selects the correct skin and MIDI note layout for the identified hardware,
		then constructs the button matrix, OSD, note-repeat component, and
		``MainSelectorComponent``.  Also triggers session highlight and MIDI map rebuild.
		"""
		#skip init if already done.
		if self._init_done:
			return
		self._init_done = True

		# second part of the __init__ after model has been identified using its challenge response
		if self._mk3_rgb or self._lpx:
			from .SkinMK2 import make_skin
			self._skin = make_skin()
			self._side_notes = (89, 79, 69, 59, 49, 39, 29, 19)
			self._drum_notes = (20, 30, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126)
		elif self._mk2_rgb:
			from .SkinMK2 import make_skin
			self._skin = make_skin()
			self._side_notes = (89, 79, 69, 59, 49, 39, 29, 19)
			#self._drum_notes = (20, 30, 31, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126)
			self._drum_notes = (20, 30, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126)
		else:
			from .SkinMK1 import make_skin # @Reimport
			self._skin = make_skin()
			self._side_notes = (8, 24, 40, 56, 72, 88, 104, 120)
			self._drum_notes = (41, 42, 43, 44, 45, 46, 47, 57, 58, 59, 60, 61, 62, 63, 73, 74, 75, 76, 77, 78, 79, 89, 90, 91, 92, 93, 94, 95, 105, 106, 107)
		
		with self.component_guard():
			is_momentary = True
			self._config_button = ButtonElement(is_momentary, MIDI_CC_TYPE, 0, 0, optimized_send_midi=False)
			self._config_button.add_value_listener(self._config_value)
			self._user_byte_write_button = ButtonElement(is_momentary, MIDI_CC_TYPE, 0, 16)
			self._user_byte_write_button.name = 'User_Byte_Button'
			self._user_byte_write_button.send_value(1)
			self._user_byte_write_button.add_value_listener(self._user_byte_value)
			matrix = ButtonMatrixElement()
			matrix.name = 'Button_Matrix'
			for row in range(8):
				button_row = []
				for column in range(8):
					if self._mk2_rgb or self._mk3_rgb or self._lpx:
						# for mk2 buttons are assigned "top to bottom"
						midi_note = (81 - (10 * row)) + column
					else:
						midi_note = row * 16 + column
					button = ConfigurableButtonElement(is_momentary, MIDI_NOTE_TYPE, 0, midi_note, skin = self._skin, control_surface = self)
					button.name = str(column) + '_Clip_' + str(row) + '_Button'
					button_row.append(button)
				matrix.add_row(tuple(button_row))

			if self._mk3_rgb or self._lpx :
				top_buttons = [ConfigurableButtonElement(is_momentary, MIDI_CC_TYPE, 0, 91 + index, skin = self._skin) for index in range(8)]
				side_buttons = [ConfigurableButtonElement(is_momentary, MIDI_CC_TYPE, 0, self._side_notes[index], skin = self._skin) for index in range(8)]
			else:
				top_buttons = [ConfigurableButtonElement(is_momentary, MIDI_CC_TYPE, 0, 104 + index, skin = self._skin) for index in range(8)]
				side_buttons = [ConfigurableButtonElement(is_momentary, MIDI_NOTE_TYPE, 0, self._side_notes[index], skin = self._skin) for index in range(8)]
				
			top_buttons[0].name = 'Bank_Select_Up_Button'
			top_buttons[1].name = 'Bank_Select_Down_Button'
			top_buttons[2].name = 'Bank_Select_Left_Button'
			top_buttons[3].name = 'Bank_Select_Right_Button'
			top_buttons[4].name = 'Session_Button'
			top_buttons[5].name = 'User1_Button'
			top_buttons[6].name = 'User2_Button'
			top_buttons[7].name = 'Mixer_Button'
			side_buttons[0].name = 'Vol_Button'
			side_buttons[1].name = 'Pan_Button'
			side_buttons[2].name = 'SndA_Button'
			side_buttons[3].name = 'SndB_Button'
			side_buttons[4].name = 'Stop_Button'
			side_buttons[5].name = 'Trk_On_Button'
			side_buttons[6].name = 'Solo_Button'
			side_buttons[7].name = 'Arm_Button'
			self._osd = M4LInterface()
			self._osd.name = "OSD"
			self._init_note_repeat()
			try:
				self._selector = MainSelectorComponent(matrix, tuple(top_buttons), tuple(side_buttons), self._config_button, self._osd, self, self._note_repeat, self._c_instance)
			except Exception as e:
				log("Could not create MainSelectorComponent: \n" + str(e))
				log(traceback.format_exc())
				raise e
			self._selector.name = 'Main_Modes'
			self._do_combine()
			for control in self.controls:
				if isinstance(control, ConfigurableButtonElement):
					control.add_value_listener(self._button_value)
		  
			self._suppress_session_highlight = False
			self.set_highlighting_session_component(self._selector.session_component())
			# due to our 2 stage init, we need to rebuild midi map 
			self.request_rebuild_midi_map()
			# and request update 
			self._selector.update()
			if self._lpx:
				self.log_message("LaunchPad95 (LPX) Loaded !")
			elif self._mk3_rgb:
				self.log_message("LaunchPad95 (mk3) Loaded !")
			elif self._mk2_rgb:
				self.log_message("LaunchPad95 (mk2) Loaded !")
			else:
				self.log_message("LaunchPad95 (classic) Loaded !")
				
	def disconnect(self):
		"""
		Clean up all listeners and put the hardware back into standalone mode.

		Sends hardware-specific SysEx to exit DAW/programmer mode and re-enable
		standalone firmware operation before delegating to the parent class.
		"""
		self._suppress_send_midi = True
		for control in self.controls:
			if isinstance(control, ConfigurableButtonElement):
				control.remove_value_listener(self._button_value)
		self._do_uncombine()
		if self._selector != None:
			self._user_byte_write_button.remove_value_listener(self._user_byte_value)
			self._config_button.remove_value_listener(self._config_value)
		ControlSurface.disconnect(self)
		self._suppress_send_midi = False
		if self._lpx:
			# lpx needs disconnect string sent
			self._send_midi(STD_MSG_HEADER + (LP_X_ID, 14, 0, SYSEX_END))
			self._send_midi(STD_MSG_HEADER + (LP_X_ID, FIRMWARE_MODE_COMMAND, STANDALONE_MODE, SYSEX_END))
		elif self._mk3_rgb:
			# launchpad mk2 needs disconnect string sent
			self._send_midi(STD_MSG_HEADER + (LP_MINI_MK3_ID, 14, 0, SYSEX_END))
			self._send_midi(STD_MSG_HEADER + (LP_MINI_MK3_ID, FIRMWARE_MODE_COMMAND, STANDALONE_MODE, SYSEX_END))
		elif self._mk2_rgb:
			# launchpad mk2 needs disconnect string sent
			self._send_midi((240, 0, 32, 41, 2, 24, 64, 247))
		if self._config_button != None:
			self._config_button.send_value(32)#Send enable flashing led config message to LP
			self._config_button.send_value(0)
			self._config_button = None
		if self._user_byte_write_button != None:
			self._user_byte_write_button.send_value(0)
			self._user_byte_write_button = None

	def _combine_active_instances():
		"""
		Static method: recalculate session track offsets for all active instances.

		Iterates ``_active_instances`` and calls ``_activate_combination_mode`` on
		each one, incrementing the cumulative track offset by each instance's session
		width so that side-by-side Launchpads show contiguous track columns.
		"""
		support_devices = False
		for instance in Launchpad._active_instances:
			support_devices |= (instance._device_component != None)
		offset = 0
		for instance in Launchpad._active_instances:
			instance._activate_combination_mode(offset, support_devices)
			offset += instance._selector._session.width()

	_combine_active_instances = staticmethod(_combine_active_instances)

	def _activate_combination_mode(self, track_offset, support_devices):
		"""
		Apply the multi-launchpad track offset to this instance's session/stepseq.

		Args:
			track_offset (int): Starting track index assigned to this instance.
			support_devices (bool): Whether any instance in the group has a device
				component (currently unused but kept for API compatibility).
		"""
		if(Settings.STEPSEQ__LINK_WITH_SESSION):
			self._selector._stepseq.link_with_step_offset(track_offset)
		if(Settings.SESSION__LINK):
			self._selector._session.link_with_track_offset(track_offset)

	def _do_combine(self):
		"""Register this instance and recombine all active instances."""
		if (DO_COMBINE and (self not in Launchpad._active_instances)):
			Launchpad._active_instances.append(self)
			Launchpad._combine_active_instances()

	def _do_uncombine(self):
		"""Unlink this instance from the combined session and recombine the rest."""
		if self in Launchpad._active_instances:
			Launchpad._active_instances.remove(self)
			if(Settings.SESSION__LINK):
				self._selector._session.unlink()
			if(Settings.STEPSEQ__LINK_WITH_SESSION):
				self._selector._stepseq.unlink()
			Launchpad._combine_active_instances()

	def refresh_state(self):
		"""Re-send hardware init bytes and rebuild the MIDI map after a reconnect."""
		ControlSurface.refresh_state(self)
		self.schedule_message(5, self._update_hardware)

	def handle_sysex(self, midi_bytes):
		"""
		Dispatch incoming SysEx messages to the appropriate hardware handler.

		Recognises three response formats:

		- **MK3/LPX identity response**: 10+ bytes starting with
		  ``(240, 126, 0, 6, 2, 0, 32, 41)``; family code bytes 8-9 distinguish
		  Mini MK3 ``(19,1)`` from Launchpad X ``(3,1)``.
		- **MK2 challenge response**: Exactly 10 bytes starting with
		  ``(240, 0, 32, 41, 2, 24, 64)``; response bytes 7-8 reassembled and
		  compared against the encrypted challenge.
		- **MK1 challenge response**: Exactly 8 bytes with manufacturer header at
		  bytes 1-4; response bytes 5-6 compared against the encrypted challenge.

		Calls ``init()`` on a successful match and enables MIDI output.

		Args:
			midi_bytes (tuple[int]): Raw SysEx bytes received from the hardware.
		"""
		if len(midi_bytes) >= 10 and midi_bytes[:8] == (240, 126, 0, 6, 2, 0, 32, 41): #0,32,41=novation
			if len(midi_bytes) >= 12 and midi_bytes[8:10] == (19,1):
				self._mk3_rgb = True
				#programmer mode
				self._send_midi(STD_MSG_HEADER + (LP_MINI_MK3_ID, 14, 1, SYSEX_END))
				#led feedback: internal off, external on
				self._send_midi(STD_MSG_HEADER + (LP_MINI_MK3_ID, 10, 0, 1, SYSEX_END))
				#disable sleep mode
				self._send_midi(STD_MSG_HEADER + (LP_MINI_MK3_ID, 9, 1, SYSEX_END))
				self._suppress_send_midi = False
				self.set_enabled(True)
				self.init()
			elif len(midi_bytes) >= 12 and midi_bytes[8:10] == (3,1):
				self._lpx = True
				#programmer mode
				self._send_midi(STD_MSG_HEADER + (LP_X_ID, 14, 1, SYSEX_END))
				#led feedback: internal off, external on
				self._send_midi(STD_MSG_HEADER + (LP_X_ID, 10, 0, 1, SYSEX_END))
				#disable sleep mode
				self._send_midi(STD_MSG_HEADER + (LP_X_ID, 9, 1, SYSEX_END))
				self._suppress_send_midi = False
				self.set_enabled(True)
				self.init()
			else:
				ControlSurface.handle_sysex(self,midi_bytes)
				#self.log_message("OTHER NOVATION")

		# MK2 has different challenge and params
		elif len(midi_bytes) == 10 and midi_bytes[:7] == (240, 0, 32, 41, 2, 24, 64):
			response = int(midi_bytes[7])
			response += int(midi_bytes[8]) << 8
			if response == Live.Application.encrypt_challenge2(self._challenge):
				self.log_message("Challenge Response ok (mk2)")
				self._mk2_rgb = True
				self._suppress_send_midi = False
				self.set_enabled(True)
				self.init()
		#MK1 Challenge
		elif len(midi_bytes) == 8 and midi_bytes[1:5] == (0, 32, 41, 6):
			response = int(midi_bytes[5])
			response += int(midi_bytes[6]) << 8
			if response == Live.Application.encrypt_challenge2(self._challenge):
				self.log_message("Challenge Response ok (mk1)")
				self._mk2_rgb = False
				self.init()
				self._suppress_send_midi = False
				self.set_enabled(True)
		else:
			ControlSurface.handle_sysex(self,midi_bytes)
		

	def build_midi_map(self, midi_map_handle):
		"""
		Build the MIDI map and add channel translations for drum/user modes.

		In User1/User2 modes that are not instrument mode, translates drum-rack
		note numbers from channel 0 to the mode-specific MIDI channel so that
		physical pads continue to send the correct notes.

		Args:
			midi_map_handle: Opaque handle passed by Live to ``ControlSurface``.
		"""
		ControlSurface.build_midi_map(self, midi_map_handle)
		if self._selector!=None:
			if self._selector._main_mode_index==1:
				mode = Settings.USER_MODES_1[self._selector._sub_mode_list[self._selector._main_mode_index] ]
				if mode != "instrument":
					new_channel = self._selector.channel_for_current_mode()
					for note in self._drum_notes:
						self._translate_message(MIDI_NOTE_TYPE, note, 0, note, new_channel)
			elif self._selector._main_mode_index==2:
				mode = Settings.USER_MODES_2[self._selector._sub_mode_list[self._selector._main_mode_index] ] 
				#self._selector.mode_index == 1:
				#if self._selector._sub_mode_list[self._selector._mode_index] > 0:  # disable midi map rebuild for instrument mode to prevent light feedback errors


	def _send_midi(self, midi_bytes, optimized=None):
		"""
		Send MIDI bytes to the hardware, suppressed when ``_suppress_send_midi`` is set.

		Args:
			midi_bytes (tuple[int]): MIDI message bytes to send.
			optimized: Passed through to parent ``ControlSurface._send_midi``.

		Returns:
			bool: ``True`` if the message was sent successfully.
		"""
		sent_successfully = False
		if not self._suppress_send_midi:
			sent_successfully = ControlSurface._send_midi(self, midi_bytes, optimized=optimized)
		return sent_successfully

	def _update_hardware(self):
		"""Re-enable MIDI, write the user-byte, then restart the challenge sequence."""
		self._suppress_send_midi = False
		if self._user_byte_write_button != None:
			self._user_byte_write_button.send_value(1)
			self._wrote_user_byte = True
		self._suppress_send_midi = True
		self.set_enabled(False)
		self._suppress_send_midi = False
		self._send_challenge()

	def _send_challenge(self):
		"""
		Send challenge bytes for all three hardware generations simultaneously.

		- MK3/LPX: Universal Device Inquiry SysEx.
		- MK2: Novation-specific SysEx with 4 challenge bytes.
		- MK1: Four CC messages on channel 0, notes 17-20.
		"""
		# send challenge for all models to allow to detect which one is actually plugged
		# mk3 and LPX
		self._send_midi(SYSEX_IDENTITY_REQUEST_MESSAGE)
		# mk2
		challenge_bytes = tuple([ self._challenge >> 8 * index & 127 for index in xrange(4) ])
		self._send_midi((240, 0, 32, 41, 2, 24, 64) + challenge_bytes + (247,))
		# mk1's
		for index in range(4):
			challenge_byte = self._challenge >> 8 * index & 127
			self._send_midi((176, 17 + index, challenge_byte))

	def _user_byte_value(self, value):
		"""
		Handle changes on the user-byte CC button (CC 16 on channel 0).

		When the Launchpad echoes back the byte we just wrote (``_wrote_user_byte``),
		the event is ignored.  Otherwise ``value == 1`` means the hardware is in
		Live/DAW mode; ``value == 0`` means Automap has taken control.

		Args:
			value (int): CC value in range 0-127.
		"""
		assert (value in range(128))
		if not self._wrote_user_byte:
			enabled = (value == 1)
			self._control_is_with_automap = not enabled
			self._suppress_send_midi = self._control_is_with_automap
			if not self._control_is_with_automap:
				for control in self.controls:
					if isinstance(control, ConfigurableButtonElement):
						control.force_next_send()

			self._selector.set_mode(0)
			self.set_enabled(enabled)
			self._suppress_send_midi = False
		else:
			self._wrote_user_byte = False

	def _button_value(self, value):
		"""No-op listener; keeps a global value-change subscription on all buttons."""
		assert value in range(128)

	def _config_value(self, value):
		"""No-op listener on the config CC button (CC 0 channel 0)."""
		assert value in range(128)

	def _set_session_highlight(self, track_offset, scene_offset, width, height, include_return_tracks):
		"""Draw the session highlight box only after ``init()`` has completed."""
		if not self._suppress_session_highlight:
			ControlSurface._set_session_highlight(self, track_offset, scene_offset, width, height, include_return_tracks)
			
	def _init_note_repeat(self):
		"""Create and disable the NoteRepeatComponent, wiring it to the Live note-repeat."""
		self._note_repeat = NoteRepeatComponent(name='Note_Repeat')
		self._note_repeat.set_enabled(False)
		self._note_repeat.set_note_repeat(self._c_instance.note_repeat)
