"""
ScaleComponent.py — Musical scale/key management for the Instrument Controller.

Provides three cooperating classes:

``Scale``
    A simple named container holding a list of note indices (0-11 chromatic offsets).

``Modus``
    A scale mode (e.g. "Major", "Dorian") that can generate root-transposed ``Scale``
    instances via ``scale(base_note)``.  All modes are loaded from
    ``Live.Song.get_all_scales_ordered()`` at import time.

``MelodicPattern``
    Translates a 2-D pad grid coordinate ``(x, y)`` into a ``NoteInfo`` tuple
    containing the MIDI note index, MIDI channel, and scale-membership flags.
    Supports five layout modes:
    - ``diatonic``         — Staggered scale tones (default).
    - ``diatonic_ns``      — Non-staggered diatonic (full scale-size step per row).
    - ``diatonic_chords``  — Vertical chord voicing.
    - ``chromatic``        — Chromatic semitone grid.
    - ``chromatic_gtr``    — Guitar-string chromatic with string break at row 4.

``ScaleComponent``
    A ``ControlSurfaceComponent`` that owns an 8×8 ``matrix`` and drives a
    scale/key editor UI.  The layout is:
    - Row 0: Layout mode buttons (absolute root, horizontal, chromatic_gtr, diatonic_ns,
      diatonic_chords, diatonic, chromatic, drumrack).
    - Row 1: Sharp/black keys + circle-of-fifths ← + relative scale + quick-scale toggle.
    - Row 2: Natural/white keys + circle-of-fifths →.
    - Row 3: Octave selector (0 to top_octave-1).
    - Rows 4-7: Modus (scale mode) selector; up to 32 modes across 4 rows of 8.

Module-level constants
----------------------
KEY_NAMES (list[str]): Chromatic note names ``["C", "C#", … "B"]``.
CIRCLE_OF_FIFTHS (list[int]): Note indices in circle-of-fifths order.
MUSICAL_MODES (list): Flat list alternating name/notes loaded from Live.
TOP_OCTAVE (dict[str, int]): Maximum octave index per layout mode.
"""

from _Framework.ControlSurfaceComponent import ControlSurfaceComponent
import Live
#fix for python3
try:
    xrange
except NameError:
    xrange = range

# Chromatic note names (index 0 = C)
KEY_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# Circle of fifths: each entry is (7*k) % 12, giving note indices in 5th-jump order
CIRCLE_OF_FIFTHS = [7 * k % 12 for k in range(12)]
# KEY_CENTERS = CIRCLE_OF_FIFTHS[0:6] + CIRCLE_OF_FIFTHS[-1:5:-1]


MUSICAL_MODES = []
for name,notes in Live.Song.get_all_scales_ordered():
	MUSICAL_MODES.append(name)
	MUSICAL_MODES.append(list(notes))

TOP_OCTAVE = {"chromatic_gtr": 7, "diatonic_ns": 2, "diatonic_chords": 7, "diatonic": 6,  
			"chromatic": 7}


class ScaleComponent(ControlSurfaceComponent):
	"""
	Scale/key editor component that drives an 8×8 button matrix.

	Listens to ``song().root_note`` and ``song().scale_name`` changes and keeps
	the pad grid in sync.  Also exposes ``get_pattern()`` which returns a
	:class:`MelodicPattern` for the ``InstrumentControllerComponent`` to use when
	laying out playable notes.

	Attributes:
		_layout_set (bool): Internal guard; currently unused.
		_modus_list (list[Modus]): All available scale modes loaded from Live.
		_modus_names (list[str]): Human-readable names matching ``_modus_list``.
		_control_surface (Launchpad): Owning control surface (for ``show_message``).
		_osd (M4LInterface | None): OSD bridge.
		_modus (int): Index of the currently selected scale mode.
		_key (int): Root note (0-11; 0=C).
		_octave (int): Current octave selector value (0 to _top_octave-1).
		_mode (str): Layout mode name; one of the ``TOP_OCTAVE`` keys.
		_is_drumrack (bool): ``True`` when pad layout is drumrack mode.
		_quick_scale (bool): ``True`` when quick-scale overlay is shown.
		_is_horizontal (bool): ``True`` for horizontal (row-major) layout.
		_is_absolute (bool): ``True`` to use absolute root note anchoring.
		_interval (int): Row interval (semi-tones or scale steps between rows).
		_matrix (ButtonMatrixElement | None): The 8×8 pad matrix.
		_top_octave (int): Maximum octave index for the current mode.
		_white_notes_index (list[int]): Chromatic indices of white keys [C,D,E,F,G,A,B].
		_current_minor_mode (int): Remembered minor modus index for relative scale jump.
		_minor_modes (list[int]): Modus indices for Natural/Harmonic/Melodic minor.
	"""

	def __init__(self, control_surface = None, enabled = False, mode = "diatonic", *a, **k):
		self._layout_set = False
		self._modus_list = [Modus(MUSICAL_MODES[v], MUSICAL_MODES[v + 1]) for v in xrange(0, len(MUSICAL_MODES), 2)]
		self._modus_names = [MUSICAL_MODES[v] for v in xrange(0, len(MUSICAL_MODES), 2)]
		self._control_surface = control_surface
		self._osd = None
		self._modus = 0
		self._key = 0
		self._octave = 3 
		self._mode = mode #diatonic
		self._is_drumrack = False
		self._quick_scale = False
		self._is_horizontal = True
		self._is_absolute = False
		self._interval = 3
		self._matrix = None
		self._top_octave = 6
		
		# C  D  E  F  G  A  B
		self._white_notes_index = [0, 2, 4, 5, 7, 9, 11]
		
		self._current_minor_mode = 1 #Natural
		self._minor_modes = [1, 13, 14]#Natural, Harmonic, Melodic
		
		super(ScaleComponent, self).__init__(*a, **k)
		self.set_enabled(enabled)

	def _remove_scale_listeners(self):
		try:
			self.song().remove_root_note_listener(self.handle_root_note_changed)
		except RuntimeError:
			pass
		try:
			self.song().remove_scale_name_listener(self.handle_scale_name_changed)
		except RuntimeError:
			pass
		
	
	def _register_scale_listeners(self):
		try:
			self.song().add_root_note_listener(self.handle_root_note_changed)
		except RuntimeError:
			pass
		try:
			self.song().add_scale_name_listener(self.handle_scale_name_changed)
		except RuntimeError:
			pass

	def handle_root_note_changed(self):
		self.set_key(self.song().root_note, False, True)
		self.update()


	def handle_scale_name_changed(self):
		self.set_modus(self._modus_names.index(self.song().scale_name), False, True)
		self.update()
		
		

	def set_enabled(self, enabled):
		ControlSurfaceComponent.set_enabled(self, enabled)
		if not enabled:
			self._remove_scale_listeners()
		else:
			self._register_scale_listeners()
		
	@property
	def notes(self):
		return self.modus.scale(self._key).notes

	@property
	def modus(self):
		return self._modus_list[self._modus]

	def set_key(self, key, message = True, listener_called = False):
		"""
		Set the root note and optionally sync back to the Live song.

		Args:
			key (int): Chromatic root note index (0-11).
			message (bool): Show a status message in Live.
			listener_called (bool): ``True`` when called from a song listener
				(avoids a recursive Live property write).
		"""
		if key>=0 and key<=11:
			self._key = key % 12
			if not listener_called:
				self.song().root_note=self._key
			if message:
				self._control_surface.show_message(str("Selected Scale: " + KEY_NAMES[self._key])+" "+str(self._modus_names[self._modus]))
		
	def set_octave(self, octave, message = True):
		if octave>=0 and octave<self._top_octave:
			self._octave = octave
			if message:
				self._control_surface.show_message("Selected octave: " + str(octave))
				
	def _set_top_octave(self, message = True):
		if(self.is_drumrack):
			self._top_octave = 8
		else:
			self._top_octave = TOP_OCTAVE[self._mode]
			
		if(self._octave>=self._top_octave):
			self._octave = self._top_octave -1
			if message:
				self._control_surface.show_message("Selected octave: " + str(self._octave))				

	def octave_up(self, message = True):
		self.set_octave(self._octave + 1, message) 
	
	def octave_down(self, message = True):
		self.set_octave(self._octave - 1, message) 
		
	def set_modus(self, index, message = True, listener_called = False):
		"""
		Select a scale mode by index.

		Args:
			index (int): Index into ``_modus_list`` (0 = Major/Ionian).
			message (bool): Show a status message in Live.
			listener_called (bool): ``True`` when called from a song listener.
		"""
		if index > -1 and index < len(self._modus_list):
			self._modus = index
			if not listener_called:
				self.song().scale_name = self._modus_names[self._modus]
			if message:
				self._control_surface.show_message(str("selected scale: " + KEY_NAMES[self._key])+" "+str(self._modus_names[self._modus]))
	
	def set_drumrack(self, drumrack):
		self._is_drumrack = drumrack
		self._set_top_octave(True)
		
	#def set_matrix(self, matrix):
	#	if not matrix or not self._layout_set:
	#		self._matrix = matrix
	#		#self._matrix.set_control_element(matrix)
	#		for index, button in enumerate(self._matrix):
	#			#button.set_playable(False)
	#			self._layout_set = bool(matrix)
	#		self.update()
	def set_matrix(self, matrix):
		self._matrix = matrix
		if matrix:
			matrix.reset()
		if (matrix != self._matrix):
			if (self._matrix != None):
				self._matrix.remove_value_listener(self._matrix_pressed)
		self._matrix = matrix
		if (self._matrix != None):
			self._matrix.add_value_listener(self._matrix_pressed)
		self.update()


	
	def set_osd(self, osd):
		self._osd = osd

	def _update_OSD(self):
		if self._osd != None:
			self._osd.attributes[0] = ""
			self._osd.attribute_names[0] = ""
			self._osd.attributes[1] = MUSICAL_MODES[self._modus * 2]
			self._osd.attribute_names[1] = "Scale"
			self._osd.attributes[2] = KEY_NAMES[self._key % 12]
			self._osd.attribute_names[2] = "Root Note"
			self._osd.attributes[3] = self._octave
			self._osd.attribute_names[3] = "Octave"
			self._osd.attributes[4] = " "
			self._osd.attribute_names[4] = " "
			self._osd.attributes[5] = " "
			self._osd.attribute_names[5] = " "
			self._osd.attributes[6] = " "
			self._osd.attribute_names[6] = " "
			self._osd.attributes[7] = " "
			self._osd.attribute_names[7] = " "
			self._osd.update()
			
	def update(self):
		if self.is_enabled() and self._matrix!=None:
			#self._control_surface.log_message("update scale: "+str(self._matrix))
			super(ScaleComponent, self).update()
			self._update_OSD()
			#for index, button in enumerate(self._matrix):
			for button, (col, row) in self._matrix.iterbuttons():
				#row, col = button.coordinate
				button.set_enabled(True)
				if row==0:
					if col == 0:
						if self._is_absolute:
							button.set_light("Scale.AbsoluteRoot.On")
						else:
							button.set_light("Scale.AbsoluteRoot.Off")
					elif col == 1:
						if self._is_horizontal:
							button.set_light("Scale.Horizontal.On")
						else:
							button.set_light("Scale.Horizontal.Off")
					elif col == 2:
						if not self.is_drumrack and self._mode == "chromatic_gtr":
							button.set_light("Scale.Mode.On")
						else:
							button.set_light("Scale.Mode.Off")
					elif col == 3:
						if not self.is_drumrack and self._mode == "diatonic_ns":
							button.set_light("Scale.Mode.On")
						else:
							button.set_light("Scale.Mode.Off")
					elif col == 4:
						if not self.is_drumrack and self._mode == "diatonic_chords":
							button.set_light("Scale.Mode.On")
						else:
							button.set_light("Scale.Mode.Off")
					elif col == 5:
						if not self.is_drumrack and self._mode == "diatonic":
							button.set_light("Scale.Mode.On")
						else:
							button.set_light("Scale.Mode.Off")
					elif col == 6:
						if not self.is_drumrack and self._mode == "chromatic":
							button.set_light("Scale.Mode.On")
						else:
							button.set_light("Scale.Mode.Off")
					elif col == 7:
						if self.is_drumrack:
							button.set_light("Scale.Mode.On")
						else:
							button.set_light("Scale.Mode.Off")
				
				elif row==1:
					if self.is_drumrack:
						if col==7:
							if self._quick_scale:
								button.set_light("Scale.QuickScale.On")
							else:
								button.set_light("Scale.QuickScale.Off")
						else:
							button.set_light("DefaultButton.Disabled")
					else:
						if col==0 or col==1 or col==3 or col==4 or col==5:
							if self._key == self._white_notes_index[col]+1:
								button.set_light("Scale.Key.On")
							else:
								button.set_light("Scale.Key.Off")
						elif col==2:
							button.set_light("Scale.RelativeScale")
						elif col==6:
							button.set_light("Scale.CircleOfFifths")
						elif col==7:
							if self._quick_scale:
								button.set_light("Scale.QuickScale.On")
							else:
								button.set_light("Scale.QuickScale.Off")
				elif row==2:
					if self.is_drumrack:
						button.set_light("DefaultButton.Disabled")
					else:
						if col<7:
							if self._key == self._white_notes_index[col]:
								button.set_light("Scale.Key.On")
							else:
								button.set_light("Scale.Key.Off")
						else:
							button.set_light("Scale.CircleOfFifths")
				elif row==3:
					if self._octave == col:
						button.set_light("Scale.Octave.On")
					else:
						if(col < self._top_octave):
							button.set_light("Scale.Octave.Off")
						else:
							button.set_light("DefaultButton.Disabled")
				elif row==4:
					if self.is_drumrack:
						button.set_light("DefaultButton.Disabled")
					else:
						if self._modus == col:
							button.set_light("Scale.Modus.On")
						else:
							button.set_light("Scale.Modus.Off")
				elif row==5:
					if self.is_drumrack:
						button.set_light("DefaultButton.Disabled")
					else:
						if self._modus == col+8:
							button.set_light("Scale.Modus.On")
						else:
							button.set_light("Scale.Modus.Off")
				elif row==6:
					if self.is_drumrack:
						button.set_light("DefaultButton.Disabled")
					else:
						if self._modus == col+16:
							button.set_light("Scale.Modus.On")
						else:
							button.set_light("Scale.Modus.Off")
				elif row==7:
					if self.is_drumrack:
						button.set_light("DefaultButton.Disabled")
					else:
						if col+24>len(self._modus_list):
							button.set_light("DefaultButton.Disabled")
						elif self._modus == col+24:
							button.set_light("Scale.Modus.On")
						else:
							button.set_light("Scale.Modus.Off")
				#button.set_enabled(False)
				#button.update()
			
		
		
	#@matrix.pressed
	def _matrix_pressed(self, value, x, y, is_momentary):
		message = True
		if self.is_enabled() and value>0:
			#y, x = pad.coordinate
			# modes
			if y == 0:
				#SCALE MODE SELECTION LOGIC
				if not self.is_drumrack:
					if x == 0:
						self._is_absolute = not self._is_absolute
						if self._is_absolute:
							self._control_surface.show_message("absolute root")
						else:
							self._control_surface.show_message("relative root")
					if x == 1:
						if self.is_diatonic:
							self._is_horizontal = not self._is_horizontal
							if self._is_horizontal:
								self._control_surface.show_message("Is Horizontal")
							else:
								self._control_surface.show_message("Is Vertical")
				if x == 2:
					self._mode = "chromatic_gtr"
					self._is_drumrack = False
					self._interval=3
					self._is_horizontal= True
					self._control_surface.show_message("mode: chromatic gtr")
				if x == 3:
					self._mode = "diatonic_ns"
					self._is_drumrack = False
					self._interval=3
					self._is_horizontal= True
					self._control_surface.show_message("mode: diatonic not staggered")
				if x == 4:
					self._mode="diatonic_chords"
					self._is_drumrack = False
					self._interval=2
					self._is_horizontal= False
					self._control_surface.show_message("mode: diatonic vertical (chords)")
				if x == 5:
					self._mode="diatonic"
					self._is_drumrack = False
					self._interval=3
					self._is_horizontal= True
					self._control_surface.show_message("mode: diatonic")
				if x == 6:
					self._mode="chromatic"
					self._is_drumrack = False
					self._interval=3
					self._is_horizontal=True
					self._control_surface.show_message("mode: chromatic")
				if x == 7:
					self.set_drumrack(True)
					self._control_surface.show_message("mode: drumrack")
				self._set_top_octave(True)	
			#ROOT/SCALE SELECTION LOGIC		
			keys = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
			# root note
			if not self.is_drumrack:
				root = -1
				selected_key = self._key
				selected_modus = self._modus
				if y == 1 and x in[0, 1, 3, 4, 5] or y == 2 and x < 7:
					root = [0, 2, 4, 5, 7, 9, 11, 12][x]
					if y == 1:
						root = root + 1

				# if root == selected_key:#alternate minor/major
				# 	if selected_modus==0:
				# 		selected_modus = self._current_minor_mode
				# 	elif selected_modus in [1,13,14]:
				# 		self._current_minor_mode = selected_modus
				# 		selected_modus = 0
				# 	elif selected_modus==11:
				# 		selected_modus = 12
				# 	elif selected_modus==12:
				# 		selected_modus = 11

				
				# nav circle of 5th right ->
				if y == 2 and x == 7:  
					root = CIRCLE_OF_FIFTHS[(CIRCLE_OF_FIFTHS.index(selected_key) + 1 + 12) % 12]
					self._control_surface.show_message("circle of 5ths -> "+keys[selected_key]+" "+str(self._modus_names[selected_modus])+" => "+keys[root]+" "+str(self._modus_names[selected_modus]))
					message = False
				
				# nav circle of 5th left <-
				if y == 1 and x == 6:  
					root = CIRCLE_OF_FIFTHS[(CIRCLE_OF_FIFTHS.index(selected_key) - 1 + 12) % 12]
					self._control_surface.show_message("circle of 5ths <- "+keys[selected_key]+" "+str(self._modus_names[selected_modus])+" => "+keys[root]+" "+str(self._modus_names[selected_modus]))
					message = False
				
				# relative major/minor scale	
				if y == 1 and x == 2:  
					if self._modus == 0: #Ionian Mode (Major)
						selected_modus = self._current_minor_mode
						root = CIRCLE_OF_FIFTHS[(CIRCLE_OF_FIFTHS.index(selected_key) + 3) % 12] # Jump up 3 steps in 5th Circle equals jumping a third minor down
					elif self._modus in [1, 13, 17]:#Natural (Aeolian), Harmonic, Melodic Minor
						self._current_minor_mode = selected_modus
						selected_modus = 0
						root = CIRCLE_OF_FIFTHS[(CIRCLE_OF_FIFTHS.index(selected_key) - 3 + 12) % 12] # Jump down 3 steps in 5th Circle equals jumping a third minor up
					elif self._modus == 11: #Minor Pentatonic
						selected_modus = 12
						root = CIRCLE_OF_FIFTHS[(CIRCLE_OF_FIFTHS.index(selected_key) - 3) % 12]
					elif self._modus == 12: #Major Pentatonic
						selected_modus = 11
						root = CIRCLE_OF_FIFTHS[(CIRCLE_OF_FIFTHS.index(selected_key) + 3 + 12) % 12]
					self._control_surface.show_message("Relative scale : "+keys[root]+" "+str(self._modus_names[selected_modus]))
					message = False
				if root != -1:
					self.set_modus(selected_modus, message)
					self.set_key(root, message)
			#QuickScale
			if y == 1 and x == 7: #and not self.is_drumrack:
				self._quick_scale = not self._quick_scale
				if self._quick_scale:
					self._control_surface.show_message("Quick scale ON")
				else:
					self._control_surface.show_message("Quick scale OFF")
			# octave
			if y == 3:
				self.set_octave(x)
				self._control_surface.show_message("octave : " + str(self._octave))
			# modus (Scale)
			if y > 3 and not self.is_drumrack:
				self.set_modus(((y - 4) * 8 + x),message)
				self._control_surface.show_message(str("Selected Scale: " + KEY_NAMES[self._key])+" "+str(self._modus_names[self._modus]))
			self.update()
	
		
	
	#@matrix.released
	def matrix_release(self, pad):
		pass
		# selected_drum_pad = self._coordinate_to_pad_map[pad.coordinate]
		# if selected_drum_pad in self._selected_pads:
		# 	self._selected_pads.remove(selected_drum_pad)
		# 	if not self._selected_pads:
		# 		self._update_control_from_script()
		# 	self.notify_pressed_pads()
		# self._update_led_feedback()			

			
	@property
	def is_drumrack(self):
		return self._is_drumrack
		
	@property
	def is_diatonic(self):
		return not self.is_drumrack and (self._mode == "diatonic" or self._mode == "diatonic_ns" or self._mode == "diatonic_chords")

	@property
	def is_chromatic(self):
		return not self.is_drumrack  and  (self._mode =="chromatic" or self._mode == "chromatic_gtr")

	@property
	def is_diatonic_ns(self):
		return self._mode == "diatonic_ns"
	
	@property	
	def is_chromatic_gtr(self):
		return self._mode == "chromatic_gtr"
		
	@property
	def is_quick_scale(self):
		return self._quick_scale
	
	
	def get_pattern(self):
		"""
		Build and return a ``MelodicPattern`` for the current scale/key/mode settings.

		Computes the correct origin offset, interval, and layout orientation, then
		returns a pattern object that the instrument controller can use to map each
		``(x, y)`` pad coordinate to a MIDI note.

		Returns:
			MelodicPattern: Configured pattern for the current scale state.
		"""
		notes = self.notes
		# origin
		if not self._is_absolute:
			origin = 0
		elif self.is_diatonic:
			origin = 0
			for k in xrange(len(notes)):
				if notes[k] >= 12:
					origin = k - len(notes)
					break
		else:
			origin = -notes[0]
			
		# interval
		if self._interval == None:
			interval = 8
		elif self.is_chromatic:
			interval = [0, 2, 4, 5, 7, 9, 10, 11][self._interval]
		else:
			interval = self._interval
		
		# layout
		if self._is_horizontal:
			steps = [1, interval]
			origin = [origin, 0]
		else:
			steps = [interval, 1]
			origin = [0, origin]
		
		return MelodicPattern(
			steps = steps, 
			scale = notes, 
			origin = origin, 
			base_note = (self._octave + 1) * 12, 
			chromatic_mode = self.is_chromatic, 
			chromatic_gtr_mode = self.is_chromatic_gtr, 
			diatonic_ns_mode = self.is_diatonic_ns
		)
		

class Scale(object):
	"""
	Simple named container for a set of MIDI note indices.

	Attributes:
		name (str): Human-readable name (e.g. ``"C"``, ``"Major"``).
		notes (list[int]): Sorted list of MIDI note indices in this scale.
	"""

	def __init__(self, name, notes, *a, **k):
		"""
		Args:
			name (str): Scale name.
			notes (list[int] | range): MIDI note indices that belong to this scale.
		"""
		super(Scale, self).__init__(*a, **k)
		self.name = name
		self.notes = notes


class Modus(Scale):
	"""
	A scale mode that can generate root-transposed ``Scale`` instances.

	Inherits ``name`` and ``notes`` from ``Scale``; ``notes`` here are relative
	chromatic offsets from the root (e.g. ``[0, 2, 4, 5, 7, 9, 11]`` for Major).
	"""

	def __init__(self, *a, **k):
		super(Modus, self).__init__(*a, **k)

	def scale(self, base_note):
		"""
		Return a ``Scale`` transposed to the given root note.

		Args:
			base_note (int): Root note chromatic index (0-11).

		Returns:
			Scale: Named scale with absolute MIDI note offsets.
		"""
		return Scale(KEY_NAMES[base_note], [base_note + x for x in self.notes])

	def scales(self, base_notes):
		"""
		Return a list of ``Scale`` instances for multiple root notes.

		Args:
			base_notes (iterable[int]): Root note indices to generate scales for.

		Returns:
			list[Scale]: One transposed scale per base note.
		"""
		return [self.scale(b) for b in base_notes]


class MelodicPattern(object):
	"""
	Maps a 2-D pad coordinate ``(x, y)`` to a MIDI note with scale metadata.

	Used by ``InstrumentControllerComponent`` to colour pads and generate MIDI
	note-on events.  Supports diatonic, chromatic, and guitar-string layouts.

	Attributes:
		steps (list[int, int]): ``[x_step, y_step]`` — how many scale steps to
		    advance per column/row.  For horizontal diatonic mode: ``[1, interval]``.
		scale (list[int] | range): Scale note offsets within one octave.
		base_note (int): MIDI note at the (0,0) origin.  Typically ``(octave+1)*12``.
		origin (list[int, int]): ``[x_origin, y_origin]`` — index offset applied
		    before stepping; used to implement absolute-root anchoring.
		valid_notes (range): MIDI note range considered playable (default 0-127).
		chromatic_mode (bool): Use full chromatic scale with fixed 5-semitone rows.
		chromatic_gtr_mode (bool): Chromatic with guitar-style string break at row 4
		    (row 4+ is one semitone lower than normal).
		diatonic_ns_mode (bool): Non-staggered diatonic; each row advances a full
		    scale octave.
	"""

	def __init__(self,
	 		steps=[0, 0],
			scale=range(12),
			base_note=0,
			origin=[0, 0],
			valid_notes=xrange(128),
			chromatic_mode=False,
			chromatic_gtr_mode=False,
			diatonic_ns_mode=False,
			*a, **k):
		super(MelodicPattern, self).__init__(*a, **k)
		self.steps = steps
		self.scale = scale
		self.base_note = base_note
		self.origin = origin
		self.valid_notes = valid_notes
		self.chromatic_mode = chromatic_mode
		self.chromatic_gtr_mode = chromatic_gtr_mode
		self.diatonic_ns_mode = diatonic_ns_mode

	class NoteInfo:
		"""
		Data class returned by ``MelodicPattern.note()``.

		Attributes:
			index (int): MIDI note number (0-127).
			channel (int): MIDI channel derived from the pad's x-coordinate.
			root (bool): ``True`` if this note is the scale root.
			highlight (bool): ``True`` if this is the 3rd or 5th scale degree.
			in_scale (bool): ``True`` if the note belongs to the current scale.
			valid (bool): ``True`` if the note falls within ``valid_notes``.
		"""

		def __init__(self, index, channel, root = False, highlight = False, in_scale = False, valid = False):
			self.index = index
			self.channel = channel
			self.root = root
			self.highlight = highlight
			self.in_scale = in_scale
			self.valid = valid

	@property
	def _extended_scale(self):
		if self.chromatic_mode:
			first_note = self.scale[0]
			return range(first_note, first_note + 12)
		else:
			return self.scale

	def _octave_and_note(self, x, y):
		scale = self._extended_scale
		scale_size = len(scale)
		if self.chromatic_mode:
			self.steps[1] = 5
		else:
			if self.diatonic_ns_mode:
				self.steps[1] = scale_size
		index = self.steps[0] * (self.origin[0] + x) + self.steps[1] * (self.origin[1] + y)
		if self.chromatic_gtr_mode and y > 3:
			index = index - 1
		octave = int(index / scale_size)
		note = scale[index % scale_size]
		return (octave, note)

	def note(self, x, y):
		"""
		Compute the ``NoteInfo`` for pad at column ``x``, row ``y``.

		Args:
			x (int): Pad column (0-7); also used as MIDI channel.
			y (int): Pad row (0-7).

		Returns:
			NoteInfo: MIDI note index and scale-membership flags for this pad.
		"""
		octave, note = self._octave_and_note(x, y)
		index = (self.base_note + 12 * octave + note) % 128 
		root = note == self.scale[0]
		highlight =  note == self.scale[2] or note == self.scale[4]
		in_scale = note in self.scale
		valid = index in self.valid_notes
		return self.NoteInfo(
			index, 
			x,
			root = root,
			highlight = highlight,
			in_scale = in_scale,
			valid = valid
		)


