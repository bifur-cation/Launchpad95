"""
DeviceControllerStrip.py — Single device parameter column for the device controller.

Each instance represents one column of the 8×8 matrix and controls one Live
device parameter.  The display mode is chosen automatically based on the
parameter type:

``SLIDER_MODE_OFF``            — No parameter mapped; all buttons disabled.
``SLIDER_MODE_TOGGLE``         — Quantized range == 1; single button toggles on/off.
``SLIDER_MODE_SMALL_ENUM``     — Quantized range ≤ 8; one lit button per option.
``SLIDER_MODE_BIG_ENUM``       — Quantized range > 8; buttons 3-4 decrement/increment.
``SLIDER_MODE_SLIDER``         — Continuous; filled bar graph proportional to value.
``SLIDER_MODE_PRECISION_SLIDER``— Continuous; buttons 3-4 nudge value by small steps.

This class is the *synchronous* implementation kept for reference.  In practice
``DeviceControllerStripServer`` (background thread) wrapped by
``DeviceControllerStripProxy`` is used instead, enabling smooth stepless animation.

When ``_stepless_mode`` is ``True`` and a button is pressed, the strip animates
the parameter from its current value to the target in a blocking loop with
``time.sleep(0.1)`` — this runs on the main thread and is the reason the proxy/
server pattern exists in the production path.
"""

from .ButtonSliderElement import ButtonSliderElement

import time

# Slider display mode constants
SLIDER_MODE_OFF = 0              # No parameter — all pads disabled
SLIDER_MODE_TOGGLE = 1           # Boolean on/off — single top button
SLIDER_MODE_SLIDER = 2           # Continuous bar graph
SLIDER_MODE_PRECISION_SLIDER = 3 # Nudge up/down buttons
SLIDER_MODE_SMALL_ENUM = 4       # Small enumeration — one pad per option
SLIDER_MODE_BIG_ENUM = 5         # Large enumeration — increment/decrement buttons

#TODO: repeat buttons.
# not exact / rounding values in slider and precision slider


class DeviceControllerStrip(ButtonSliderElement):
	"""
	Synchronous single-column device parameter controller (reference implementation).

	Inherits ``ButtonSliderElement`` for parameter binding; adds display-mode
	selection, toggle/enum/slider/precision LED update methods, and stepless
	animation (blocking).

	Note: This class is retained for reference but is superseded in production by
	``DeviceControllerStripServer`` + ``DeviceControllerStripProxy``.

	Attributes:
		_control_surface (Launchpad): Owning control surface.
		_column (int): Zero-based column index (0-7); used in skin key names.
		_parent (DeviceControllerComponent | None): Parent for OSD updates.
		_num_buttons (int): Number of buttons in this column (always 8).
		_value_map (tuple[float]): Normalised 0.0-1.0 thresholds per button row.
		_precision_mode (bool): ``True`` when precision nudge mode is active.
		_stepless_mode (bool): ``True`` when blocking smooth animation is active.
		_enabled (bool): Whether this strip processes button input.
	"""

	def __init__(self, buttons, control_surface, column, parent = None):
		"""
		Args:
			buttons (tuple[ButtonElement]): 8 buttons in the column (top-to-bottom).
			control_surface (Launchpad): Owning control surface.
			column (int): Column index used in ``"Device.CustomSlider<n>"`` skin keys.
			parent (DeviceControllerComponent | None): Parent for OSD callbacks.
		"""
		ButtonSliderElement.__init__(self, buttons)
		self._control_surface = control_surface
		self._column = column
		self._parent = parent
		self._num_buttons = len(buttons)
		self._value_map = tuple([float(index) / (self._num_buttons-1) for index in range(self._num_buttons)])
		self._precision_mode = False
		self._stepless_mode = False
		self._enabled = True
	def set_enabled(self,enabled):
		self._enabled = enabled
	
	def set_precision_mode(self, precision_mode):
		self._precision_mode = precision_mode
		self.update()

	def set_stepless_mode(self, stepless_mode):
		self._stepless_mode = stepless_mode
		self.update()

	def shutdown(self):
		self._control_surface = None
		self._parent = None
		self._column = None
		self._buttons = None
		self._slider_queue.put((self._column,"shutdown"))
		self._slider_queue_processor.join()


	@property
	def _value(self):
		if self._parameter_to_map_to is not None:
			return self._parameter_to_map_to.value
		else:
			return 0
			
	@property
	def _max(self):
		if self._parameter_to_map_to is not None:
			return self._parameter_to_map_to.max
		else:
			return 0
	
	@property
	def _min(self):
		if self._parameter_to_map_to != None:	
			return self._parameter_to_map_to.min
		else:
			return 0

	@property
	def _range(self):
		if self._parameter_to_map_to != None:	
			return self._parameter_to_map_to.max - self._parameter_to_map_to.min
		else:
			return 0

	@property
	def _default_value(self):
		if self._parameter_to_map_to != None:	
			return self._parameter_to_map_to._default_value
		else:
			return 0
				
	@property
	def _is_quantized(self):
		if self._parameter_to_map_to != None:	
			return self._parameter_to_map_to.is_quantized
		else:
			return False
					
	@property
	def _mode(self):
		if self._parameter_to_map_to != None:	
			if self._is_quantized:
				if self._range == 1:
					return SLIDER_MODE_TOGGLE
				elif self._range<=self._num_buttons:
					return SLIDER_MODE_SMALL_ENUM
				else:
					return SLIDER_MODE_BIG_ENUM
			else:
				if self._precision_mode:
					return SLIDER_MODE_PRECISION_SLIDER
				else:
					return SLIDER_MODE_SLIDER				
		else:
			return SLIDER_MODE_OFF
				

	def update(self):
		if self._enabled:
			if self._mode == SLIDER_MODE_TOGGLE:
				self._update_toggle()
			elif self._mode == SLIDER_MODE_SMALL_ENUM:
				self._update_small_enum()
			elif self._mode == SLIDER_MODE_BIG_ENUM:
				self._update_big_enum()
			elif (self._mode == SLIDER_MODE_SLIDER):
				self._update_slider()
			elif (self._mode == SLIDER_MODE_PRECISION_SLIDER):
				self._update_precision_slider()
			else:
				self._update_off()


	def reset(self):
		self._update_off()
		
	def reset_if_no_parameter(self):
		if self._parameter_to_map_to == None:
			self.reset()
			
	def _update_off(self):
		v =  ["DefaultButton.Disabled" for index in range(len(self._buttons))]
		self._update_buttons(tuple(v))
	
	def _update_toggle(self):
		v =  ["DefaultButton.Disabled" for index in range(len(self._buttons))]
		if self._value==self._max:
			v[0]="Device.Toggle.On"
		else:
			v[0]="Device.Toggle.Off"
		self._update_buttons(tuple(v))

	def _update_small_enum(self):
		v =  ["DefaultButton.Disabled" for index in range(len(self._buttons))]
		for index in range(int(self._range+1)):
			if self._value==index+self._min:
				v[index]="Device.Enum.On"
			else:
				v[index]="Device.Enum.Off"
		self._update_buttons(tuple(v))

	def _update_big_enum(self):
		v =  ["DefaultButton.Disabled" for index in range(len(self._buttons))]
		if self._value>self._min:
			v[3]="Device.BigEnum.On"
		else:
			v[3]="Device.BigEnum.Off"
		if self._value<self._max:
			v[4]="Device.BigEnum.On"
		else:
			v[4]="Device.BigEnum.Off"
		self._update_buttons(tuple(v))

	def _update_slider(self):
		v =  ["DefaultButton.Disabled" for index in range(len(self._buttons))]
		for index in range(len(self._buttons)):
			if self._value >=self._value_map[index]*self._range+self._min:
				v[index]="Device.Slider"+self._column+".On"
			else:
				v[index]="Device.Slider"+self._column+".Off"
		self._update_buttons(tuple(v))
		
	def _update_precision_slider(self):
		v =  ["DefaultButton.Disabled" for index in range(len(self._buttons))]
		if self._value>self._min:
			v[3]="Device.PrecisionSlider.On"
		else:
			v[3]="Device.PrecisionSlider.Off"
			
		if self._value<self._max:
			v[4]="Device.PrecisionSlider.On"
		else:
			v[4]="Device.PrecisionSlider.Off"
		self._update_buttons(tuple(v))
			
	def _update_buttons(self, buttons):
		assert isinstance(buttons, tuple)
		assert (len(buttons) == len(self._buttons))
		for index in range(len(self._buttons)):
			self._buttons[index].set_on_off_values(buttons[index], buttons[index])
			if buttons[index].endswith("On"):#buttons[index]>0:
				self._buttons[index].turn_on()
			else:
				self._buttons[index].turn_off()

	def _button_value(self, value, sender):
		assert isinstance(value, int)
		assert (sender in self._buttons)
		self._last_sent_value = -1
		if (self._parameter_to_map_to != None and self._enabled and ((value != 0) or (not sender.is_momentary()))):
			if (value != self._last_sent_value):
				target_value = None

				index_of_sender = list(self._buttons).index(sender)
				if (self._mode == SLIDER_MODE_TOGGLE) and index_of_sender==0:
					if self._value == self._max:
						target_value = self._min
						#self._parameter_to_map_to.value = self._min
					else:
						target_value = self._max
						#self._parameter_to_map_to.value = self._max

				elif self._mode == SLIDER_MODE_SMALL_ENUM:
					target_value = index_of_sender + self._min
					#self._parameter_to_map_to.value = index_of_sender + self._min

				elif self._mode == SLIDER_MODE_BIG_ENUM:
					if index_of_sender>=4:
						inc = 2**(index_of_sender - 3 -1)
						if self._value + inc <= self._max:
							target_value += inc
							#self._parameter_to_map_to.value += inc
						else:
							target_value = self._max
							#self._parameter_to_map_to.value = self._max
					else:
						inc = 2**(4 - index_of_sender -1)
						if self._value - inc >= self._min:
							target_value -= inc
							#self._parameter_to_map_to.value -= inc
						else:
							target_value = self._min
							#self._parameter_to_map_to.value = self._min

							
				elif (self._mode == SLIDER_MODE_SLIDER):
					target_value= self._value_map[index_of_sender]*self._range + self._min
					#self._parameter_to_map_to.value = self._value_map[index_of_sender]*self._range + self._min

					
				elif (self._mode == SLIDER_MODE_PRECISION_SLIDER):
					inc = float(self._range) / 128
					if self._range>7 and inc<1:
						inc=1
					if index_of_sender >= 4:
						inc = inc * 2**(index_of_sender - 3-1)
						if self._value + inc <= self._max:
							target_value += inc
							#self._parameter_to_map_to.value += inc
						else:
							target_value = self._max
							#self._parameter_to_map_to.value = self._max
					else:
						inc = inc * 2**(4 - index_of_sender-1)
						if self._value - inc >= self._min:
							target_value -= inc
							#self._parameter_to_map_to.value -= inc
						else:
							target_value = self._min
							#self._parameter_to_map_to.value = self._min
			if self._stepless_mode:
				value = max(value,10)
				#self._slider_queue.put(tuple(_target_value,value))

				current_value = round(self._parameter_to_map_to.value, 3)
				target_value = round(target_value, 3)
				while current_value != target_value:
					current_value = round(self._parameter_to_map_to.value, 3)
					velocity_factor = round(value /(4*127.0), 3)
					max_diff = abs(target_value - current_value)
					velocity_factor = min(velocity_factor, max_diff)
					new_value = current_value + velocity_factor if current_value < target_value else current_value - velocity_factor
					new_value = max(min(new_value, self._parameter_to_map_to.max), self._parameter_to_map_to.min)
					self._parameter_to_map_to.value = new_value
					self.notify_value(value)
					time.sleep(0.1)
			else:
				self._parameter_to_map_to.value = target_value
			self.notify_value(value)
			if self._parent is not None:
				self._parent._update_OSD()

	def _on_parameter_changed(self,trigger_osd= True):
		assert (self._parameter_to_map_to != None)
		if self._parent is not None:
			self._parent._update_OSD()
		self.update()
