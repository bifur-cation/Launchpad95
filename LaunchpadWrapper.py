"""
LaunchpadWrapper.py — Standalone Python wrapper for Novation Launchpad controllers.

Provides LED control, scale-grid instrument layout, and mixer bar-graph display
for all four supported hardware generations WITHOUT requiring Ableton Live.

Dependencies:
    pip install mido python-rtmidi

Supported hardware:
    - Launchpad MK1 / Mini / S  (2-bit amber/green/red, no RGB)
    - Launchpad MK2             (128-colour palette)
    - Launchpad Mini MK3        (128-colour palette + blink/pulse)
    - Launchpad X               (128-colour palette + blink/pulse)

Quick start:
    lp = LaunchpadWrapper.connect()          # auto-detect hardware
    lp.set_led(0, 0, Mk2Color.RED)           # top-left pad = red
    lp.on_button_press(lambda r, c: print(f"Pressed {r},{c}"))
    lp.run()                                  # blocking MIDI loop

Scale grid:
    grid = ScaleGrid()
    grid.set_scale("Major", root=0, octave=4)
    lp.color_scale_grid(grid)

Mixer bars:
    lp.draw_mixer([0.2, 0.5, 0.8, 1.0, 0.6, 0.3, 0.7, 0.4])
"""

import threading
import time
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

try:
    import mido
except ImportError:
    raise ImportError("mido is required: pip install mido python-rtmidi")


# ---------------------------------------------------------------------------
# Hardware model constants
# ---------------------------------------------------------------------------

class HardwareModel:
    """Supported hardware model identifiers."""
    MK1 = "mk1"
    MK2 = "mk2"
    MK3 = "mk3"
    LPX = "lpx"


# ---------------------------------------------------------------------------
# Colour palettes
# ---------------------------------------------------------------------------

class Mk1Color:
    """
    2-bit colour constants for Launchpad MK1 / Mini / S.

    Colours are encoded as a MIDI velocity byte:
        bits 4-5 = green intensity (0-3)
        bits 0-1 = red intensity (0-3)
    """
    OFF    = 0x0C   # 0b00001100  (clear flag set, full brightness mode)
    RED    = 0x0F   # red=3, green=0
    AMBER  = 0x1F   # red=3, green=1 (approximately amber)
    YELLOW = 0x3E   # red=2, green=3
    GREEN  = 0x3C   # red=0, green=3
    # Convenience aliases
    LOW_RED    = 0x0D
    LOW_GREEN  = 0x1C
    LOW_AMBER  = 0x1D


class Mk2Color:
    """
    128-colour palette indices for Launchpad MK2 / Mini MK3 / X.

    Pass any integer 0-127 as a colour index.  Selected common colours listed
    here; a full swatch can be found in the Novation Programmer Reference.
    """
    OFF         = 0
    WHITE       = 3
    RED         = 5
    ORANGE      = 9
    AMBER       = 9
    YELLOW      = 13
    LIME        = 17
    GREEN       = 17
    MINT        = 21
    CYAN        = 25
    LIGHT_BLUE  = 41
    BLUE        = 45
    PURPLE      = 49
    PINK        = 57
    WARM_WHITE  = 63
    DIM_WHITE   = 1
    DIM_RED     = 7
    DIM_GREEN   = 19
    DIM_BLUE    = 47


# ---------------------------------------------------------------------------
# SysEx constants
# ---------------------------------------------------------------------------

# Novation manufacturer ID prefix (no F0/F7 — mido adds those)
_NOVATION_HDR: Tuple[int, ...] = (0x00, 0x20, 0x29, 0x02)

# Device family codes used in Universal Device Inquiry response
_LP_MK3_FAMILY = (19, 1)
_LP_LPX_FAMILY = (3, 1)

# MIDI port name fragments for auto-detection.
# More-specific patterns are listed before the MK1 catch-all so that
# "Launchpad MK2 0", "Launchpad X 0", etc. are matched correctly even when
# Windows appends a trailing port index like " 0".
_PORT_PATTERNS: Dict[str, List[str]] = {
    HardwareModel.MK2: ["launchpad mk2"],
    HardwareModel.MK3: ["launchpad mini mk3", "launchpad mini mk 3"],
    HardwareModel.LPX: ["launchpad x"],
    # MK1 / Mini / S — bare "launchpad" also catches "Launchpad 0" style names
    HardwareModel.MK1: ["launchpad mini", "launchpad s", "launchpad mk1",
                        "launchpad"],
}


# ---------------------------------------------------------------------------
# MIDI layout helpers
# ---------------------------------------------------------------------------

def _mk1_note(row: int, col: int) -> Tuple[str, int]:
    """
    Return the ``(msg_type, number)`` for a grid pad on MK1/Mini/S.

    The MK1 grid uses note = ``row * 16 + col``.  Side buttons (col == 8)
    use the same formula, giving notes 8, 24, 40, 56, 72, 88, 104, 120.
    Top buttons are CC 104-111.

    Args:
        row: Grid row 0 (top) to 7 (bottom).
        col: Grid column 0 (left) to 8 (right side button).

    Returns:
        Tuple of ``('note', note_number)`` for grid/side or
        ``('cc', cc_number)`` for top buttons (row == -1).
    """
    if row == -1:
        return ('cc', 104 + col)
    return ('note', row * 16 + col)


def _mk2_note(row: int, col: int, model: str = HardwareModel.MK2) -> Tuple[str, int]:
    """
    Return the ``(msg_type, number)`` for a grid pad on MK2 / MK3 / LPX.

    Grid note = ``(81 - 10 * row) + col``.
    Side buttons:
        - MK2: note type,  notes 89, 79, 69, 59, 49, 39, 29, 19
        - MK3 / LPX: CC type, same numbers
    Top buttons: CC 91-98 for MK3/LPX, CC 104-111 for MK2.

    Args:
        row: Grid row 0 (top) to 7 (bottom).
        col: Grid column 0 (left) to 8 (right side button).
        model: One of ``HardwareModel.*`` constants.

    Returns:
        Tuple of ``('note', n)`` or ``('cc', n)``.
    """
    if row == -1:
        # Top buttons
        if model == HardwareModel.MK2:
            return ('cc', 104 + col)
        else:
            return ('cc', 91 + col)
    if col == 8:
        # Side buttons
        note_num = 89 - row * 10
        if model == HardwareModel.MK2:
            return ('note', note_num)
        else:
            return ('cc', note_num)
    # Grid pads
    return ('note', (81 - 10 * row) + col)


# ---------------------------------------------------------------------------
# Scale / instrument grid
# ---------------------------------------------------------------------------

# Built-in scale definitions: name -> list of semitone intervals within an octave
BUILTIN_SCALES: Dict[str, List[int]] = {
    "Chromatic":          [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11],
    "Major":              [0, 2, 4, 5, 7, 9, 11],
    "Minor":              [0, 2, 3, 5, 7, 8, 10],
    "Dorian":             [0, 2, 3, 5, 7, 9, 10],
    "Phrygian":           [0, 1, 3, 5, 7, 8, 10],
    "Lydian":             [0, 2, 4, 6, 7, 9, 11],
    "Mixolydian":         [0, 2, 4, 5, 7, 9, 10],
    "Locrian":            [0, 1, 3, 5, 6, 8, 10],
    "Major Pentatonic":   [0, 2, 4, 7, 9],
    "Minor Pentatonic":   [0, 3, 5, 7, 10],
    "Blues":              [0, 3, 5, 6, 7, 10],
    "Whole Tone":         [0, 2, 4, 6, 8, 10],
    "Harmonic Minor":     [0, 2, 3, 5, 7, 8, 11],
    "Melodic Minor":      [0, 2, 3, 5, 7, 9, 11],
}

# Interval between adjacent rows in horizontal diatonic layout (scale degrees per row)
_DIATONIC_ROW_INTERVAL = 2


@dataclass
class NoteInfo:
    """
    Information about the note assigned to a single pad in a ``ScaleGrid``.

    Attributes:
        note:       MIDI note number (0-127), or -1 if out of range.
        in_scale:   True if the note belongs to the active scale.
        is_root:    True if the note is the root of the scale in any octave.
        is_highlight: True if the note is the pad's highlighted position.
        valid:      True if the note is within the playable MIDI range (0-127).
    """
    note:         int
    in_scale:     bool
    is_root:      bool
    is_highlight: bool
    valid:        bool


class ScaleGrid:
    """
    Maps an 8x8 pad grid to MIDI notes using a diatonic scale layout.

    Ported from ``ScaleComponent.MelodicPattern`` (which itself is used by
    ``InstrumentControllerComponent``).  The layout is ``horizontal``:
    columns advance by 1 scale degree; rows advance by ``row_interval``
    scale degrees (default 2, a diatonic third).

    Layout formula::

        index = col + row_interval * row
        octave_shift = index // scale_size
        scale_degree = index % scale_size
        note = base_note + scale[scale_degree] + octave_shift * 12

    where ``base_note = (octave + 1) * 12 + root``.

    Attributes:
        _scale_name (str): Active scale name from ``BUILTIN_SCALES``.
        _root (int): Root note semitone 0-11 (0=C, 1=C#, …, 11=B).
        _octave (int): Base octave (4 = middle C octave).
        _row_interval (int): Scale degrees per row step.
        _scale (list[int]): Active semitone intervals list.
        _highlight (int | None): Scale degree index to highlight (or None).
    """

    def __init__(self, scale_name: str = "Major", root: int = 0, octave: int = 4,
                 row_interval: int = _DIATONIC_ROW_INTERVAL):
        """
        Initialise the scale grid.

        Args:
            scale_name: Key into ``BUILTIN_SCALES``.  Defaults to ``"Major"``.
            root:       Root semitone 0-11 (0=C).  Defaults to 0.
            octave:     Base octave number.  Defaults to 4 (middle C).
            row_interval: Scale degrees between adjacent rows.  Defaults to 2.
        """
        self._row_interval = row_interval
        self._highlight: Optional[int] = None
        self.set_scale(scale_name, root, octave)

    def set_scale(self, scale_name: str, root: int = 0, octave: int = 4) -> None:
        """
        Change the active scale, root, and octave.

        Args:
            scale_name: Key into ``BUILTIN_SCALES``.
            root:       Root semitone 0-11.
            octave:     Base octave number.
        """
        if scale_name not in BUILTIN_SCALES:
            raise ValueError(f"Unknown scale '{scale_name}'. "
                             f"Available: {list(BUILTIN_SCALES)}")
        self._scale_name = scale_name
        self._scale = BUILTIN_SCALES[scale_name]
        self._root = root % 12
        self._octave = octave

    def set_highlight(self, scale_degree: Optional[int]) -> None:
        """
        Highlight a particular scale degree index across all octaves.

        Args:
            scale_degree: Index into the scale (0 = root, 1 = second, …),
                          or ``None`` to clear the highlight.
        """
        self._highlight = scale_degree

    @property
    def scale_notes(self) -> List[int]:
        """Return all MIDI note numbers that belong to the active scale (all octaves)."""
        result = []
        for octave in range(11):
            base = (octave + 1) * 12 + self._root
            for interval in self._scale:
                n = base + interval
                if 0 <= n <= 127:
                    result.append(n)
        return result

    def note_at(self, row: int, col: int) -> NoteInfo:
        """
        Return the ``NoteInfo`` for pad at ``(row, col)``.

        Args:
            row: Pad row 0 (top) to 7 (bottom).
            col: Pad column 0 (left) to 7 (right).

        Returns:
            ``NoteInfo`` describing the MIDI note and its scale membership.
        """
        scale = self._scale
        scale_size = len(scale)
        index = col + self._row_interval * (7 - row)  # row 7 = bottom = lowest pitch
        base_note = (self._octave + 1) * 12 + self._root
        octave_shift = index // scale_size
        degree = index % scale_size
        note = base_note + scale[degree] + octave_shift * 12
        valid = 0 <= note <= 127
        # Determine root: note == root mod 12
        is_root = valid and (note % 12 == self._root % 12)
        is_in_scale = valid  # by construction all notes in grid are in-scale
        is_highlight = (self._highlight is not None and degree == self._highlight)
        return NoteInfo(
            note=note if valid else -1,
            in_scale=is_in_scale,
            is_root=is_root,
            is_highlight=is_highlight,
            valid=valid,
        )


# ---------------------------------------------------------------------------
# Main wrapper class
# ---------------------------------------------------------------------------

class LaunchpadWrapper:
    """
    Standalone Python interface for Novation Launchpad controllers.

    Provides LED control, hardware auto-detection, button callbacks, scale-grid
    colouring, and mixer bar-graph display.  Uses ``mido`` + ``python-rtmidi``
    for MIDI I/O and does NOT require Ableton Live.

    Attributes:
        model (str): Hardware model constant from ``HardwareModel``.
        _inport (mido.ports.BaseInput): Open MIDI input port.
        _outport (mido.ports.BaseOutput): Open MIDI output port.
        _press_callbacks (list): Functions called on any button press.
        _release_callbacks (list): Functions called on any button release.
        _pad_press_callbacks (dict): ``{(row, col): [callback, ...]}``.
        _pad_release_callbacks (dict): ``{(row, col): [callback, ...]}``.
        _reverse_map (dict): ``{(msg_type, number): (row, col)}`` lookup.
        _running (bool): Whether the MIDI listener loop is active.
        _thread (threading.Thread | None): Background listener thread, or None.
    """

    def __init__(self, model: str, inport, outport):
        """
        Low-level constructor.  Prefer ``LaunchpadWrapper.connect()`` instead.

        Args:
            model:   Hardware model constant (``HardwareModel.*``).
            inport:  Open ``mido`` input port.
            outport: Open ``mido`` output port.
        """
        self.model = model
        self._inport = inport
        self._outport = outport
        self._press_callbacks: List[Callable] = []
        self._release_callbacks: List[Callable] = []
        self._pad_press_callbacks: Dict[Tuple[int, int], List[Callable]] = {}
        self._pad_release_callbacks: Dict[Tuple[int, int], List[Callable]] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._reverse_map: Dict[Tuple[str, int], Tuple[int, int]] = {}
        self._build_reverse_map()
        self._init_hardware()

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------

    @classmethod
    def connect(cls, model: Optional[str] = None,
                input_port: Optional[str] = None,
                output_port: Optional[str] = None) -> "LaunchpadWrapper":
        """
        Open a connection to a Launchpad and return a ready ``LaunchpadWrapper``.

        Port selection priority:
        1. ``input_port`` / ``output_port`` if provided (exact name match).
        2. Auto-detect by ``model`` using known port name patterns.
        3. If ``model`` is also None, try all known patterns in order
           MK2 → MK3 → LPX → MK1 and use the first match.

        Args:
            model:       ``HardwareModel.*`` constant, or ``None`` for auto.
            input_port:  Exact MIDI input port name, or ``None`` for auto.
            output_port: Exact MIDI output port name, or ``None`` for auto.

        Returns:
            Connected ``LaunchpadWrapper`` instance with programmer mode active.

        Raises:
            RuntimeError: If no matching MIDI port is found.
        """
        in_names = mido.get_input_names()
        out_names = mido.get_output_names()

        def _find_port(names: List[str], patterns: List[str]) -> Optional[str]:
            for name in names:
                for pat in patterns:
                    if pat in name.lower():
                        return name
            return None

        if input_port and output_port:
            # Exact names provided
            detected_model = model or cls._detect_model_from_name(input_port)
            return cls(detected_model or HardwareModel.MK2,
                       mido.open_input(input_port),
                       mido.open_output(output_port))

        # Auto-detect
        search_order = (
            [model] if model
            else [HardwareModel.MK2, HardwareModel.MK3, HardwareModel.LPX, HardwareModel.MK1]
        )

        for m in search_order:
            patterns = _PORT_PATTERNS[m]
            inp = _find_port(in_names, patterns)
            out = _find_port(out_names, patterns)
            if inp and out:
                return cls(m, mido.open_input(inp), mido.open_output(out))

        available = "\n  ".join(in_names) or "(none)"
        raise RuntimeError(
            f"No Launchpad MIDI port found.\nAvailable inputs:\n  {available}"
        )

    @staticmethod
    def _detect_model_from_name(port_name: str) -> Optional[str]:
        """
        Guess the hardware model from a MIDI port name string.

        Args:
            port_name: MIDI port name string.

        Returns:
            ``HardwareModel.*`` constant or ``None`` if unrecognised.
        """
        low = port_name.lower()
        for model, patterns in _PORT_PATTERNS.items():
            for pat in patterns:
                if pat in low:
                    return model
        return None

    def _build_reverse_map(self) -> None:
        """
        Populate ``_reverse_map`` mapping ``(msg_type, number)`` to ``(row, col)``.

        This map is used in ``_handle_message`` to translate incoming MIDI into
        logical ``(row, col)`` coordinates.  The mapping differs per hardware
        generation because note numbers and CC/note type assignments vary.
        """
        self._reverse_map = {}
        if self.model == HardwareModel.MK1:
            # Top buttons: CC 104-111 -> row=-1, col=0-7
            for col in range(8):
                self._reverse_map[('cc', 104 + col)] = (-1, col)
            # Grid + side: note = row*16 + col
            for row in range(8):
                for col in range(9):  # 0-7 grid, 8 side
                    self._reverse_map[('note', row * 16 + col)] = (row, col)
        elif self.model == HardwareModel.MK2:
            # Top buttons: CC 104-111
            for col in range(8):
                self._reverse_map[('cc', 104 + col)] = (-1, col)
            # Grid: note = (81 - 10*row) + col
            for row in range(8):
                for col in range(8):
                    self._reverse_map[('note', (81 - 10 * row) + col)] = (row, col)
            # Side buttons: note type, 89, 79, ...
            for row in range(8):
                self._reverse_map[('note', 89 - row * 10)] = (row, 8)
        else:
            # MK3 / LPX
            # Top buttons: CC 91-98
            for col in range(8):
                self._reverse_map[('cc', 91 + col)] = (-1, col)
            # Grid: note = (81 - 10*row) + col
            for row in range(8):
                for col in range(8):
                    self._reverse_map[('note', (81 - 10 * row) + col)] = (row, col)
            # Side buttons: CC type, same numbers as MK2
            for row in range(8):
                self._reverse_map[('cc', 89 - row * 10)] = (row, 8)

    def _init_hardware(self) -> None:
        """
        Send the SysEx message to put the device into Programmer mode.

        In Programmer mode all pads are individually addressable and the host
        controls all LEDs directly.  MK1 requires no SysEx (always in direct
        mode); MK2/MK3/LPX use a Novation-specific ``0x0E 0x01`` message.
        """
        if self.model == HardwareModel.MK1:
            return  # MK1 has no programmer-mode SysEx
        if self.model == HardwareModel.MK2:
            device_id = 0x18  # MK2 device byte
        elif self.model == HardwareModel.MK3:
            device_id = 0x0D
        else:
            device_id = 0x0C  # LPX
        self._send_sysex(_NOVATION_HDR + (device_id, 0x0E, 0x01))

    # ------------------------------------------------------------------
    # LED control
    # ------------------------------------------------------------------

    def _led_address(self, row: int, col: int) -> Tuple[str, int]:
        """
        Return the ``(msg_type, number)`` that addresses the LED at ``(row, col)``.

        Args:
            row: Pad row 0-7, or -1 for top automap buttons.
            col: Pad column 0-7, or 8 for right side buttons.

        Returns:
            ``('note', n)`` or ``('cc', n)``.
        """
        if self.model == HardwareModel.MK1:
            return _mk1_note(row, col)
        return _mk2_note(row, col, self.model)

    def set_led(self, row: int, col: int, color: int) -> None:
        """
        Set a single pad LED to a static colour.

        Args:
            row:   Pad row 0 (top) to 7 (bottom), or -1 for top buttons.
            col:   Pad column 0 (left) to 7 (right), or 8 for side buttons.
            color: Colour index (``Mk1Color.*`` for MK1, ``Mk2Color.*`` for others).
        """
        msg_type, number = self._led_address(row, col)
        if msg_type == 'note':
            self._send_note_on(number, color, channel=0)
        else:
            self._send_cc(number, color)

    def blink(self, row: int, col: int, color: int) -> None:
        """
        Set a pad LED to blink between ``color`` and off (MK2/MK3/LPX only).

        Blink is achieved by sending note-on on MIDI channel 2 (0-indexed: 1).
        Has no effect on MK1 hardware.

        Args:
            row:   Pad row 0-7.
            col:   Pad column 0-7 (or 8 for side).
            color: Colour index (``Mk2Color.*``).
        """
        if self.model == HardwareModel.MK1:
            return
        _, number = self._led_address(row, col)
        self._send_note_on(number, color, channel=1)

    def pulse(self, row: int, col: int, color: int) -> None:
        """
        Set a pad LED to pulse (fade in/out) in ``color`` (MK2/MK3/LPX only).

        Pulse is achieved by sending note-on on MIDI channel 3 (0-indexed: 2).
        Has no effect on MK1 hardware.

        Args:
            row:   Pad row 0-7.
            col:   Pad column 0-7 (or 8 for side).
            color: Colour index (``Mk2Color.*``).
        """
        if self.model == HardwareModel.MK1:
            return
        _, number = self._led_address(row, col)
        self._send_note_on(number, color, channel=2)

    def set_row(self, row: int, colors: List[int]) -> None:
        """
        Set all 8 grid pads in a row to the given colours.

        Args:
            row:    Row index 0-7.
            colors: List of exactly 8 colour values (one per column).
        """
        for col, color in enumerate(colors[:8]):
            self.set_led(row, col, color)

    def set_grid(self, colors: List[List[int]]) -> None:
        """
        Set all 64 grid pads in a single call.

        Args:
            colors: 8x8 nested list of colour values.  ``colors[row][col]``.
        """
        for row, row_colors in enumerate(colors[:8]):
            self.set_row(row, row_colors)

    def clear(self) -> None:
        """Turn off all 64 grid pads, all 8 side buttons, and all 8 top buttons."""
        off = Mk1Color.OFF if self.model == HardwareModel.MK1 else Mk2Color.OFF
        for row in range(8):
            for col in range(9):  # 0-7 grid + 8 side
                self.set_led(row, col, off)
        for col in range(8):
            self.set_led(-1, col, off)

    # ------------------------------------------------------------------
    # Instrument / scale grid
    # ------------------------------------------------------------------

    def color_scale_grid(
        self,
        scale_grid: ScaleGrid,
        root_color: Optional[int] = None,
        in_scale_color: Optional[int] = None,
        off_color: Optional[int] = None,
    ) -> None:
        """
        Colour the 8x8 grid according to scale membership from ``scale_grid``.

        Default colours (MK2/MK3/LPX):
            - Root notes: blue (``Mk2Color.BLUE``)
            - In-scale notes: light blue (``Mk2Color.LIGHT_BLUE``)
            - Out-of-scale / invalid: off (``Mk2Color.OFF``)

        Default colours (MK1):
            - Root notes: amber (``Mk1Color.AMBER``)
            - In-scale notes: green (``Mk1Color.GREEN``)
            - Out-of-scale / invalid: off (``Mk1Color.OFF``)

        Args:
            scale_grid:    ``ScaleGrid`` instance defining the note layout.
            root_color:    Override colour for root notes.
            in_scale_color: Override colour for non-root in-scale notes.
            off_color:     Override colour for out-of-scale notes.
        """
        if self.model == HardwareModel.MK1:
            root_color     = root_color     or Mk1Color.AMBER
            in_scale_color = in_scale_color or Mk1Color.GREEN
            off_color      = off_color      or Mk1Color.OFF
        else:
            root_color     = root_color     or Mk2Color.BLUE
            in_scale_color = in_scale_color or Mk2Color.LIGHT_BLUE
            off_color      = off_color      or Mk2Color.OFF

        for row in range(8):
            for col in range(8):
                info = scale_grid.note_at(row, col)
                if not info.valid:
                    color = off_color
                elif info.is_root:
                    color = root_color
                else:
                    color = in_scale_color
                self.set_led(row, col, color)

    # ------------------------------------------------------------------
    # Mixer / bar graph display
    # ------------------------------------------------------------------

    def draw_bar(
        self,
        col: int,
        value: float,
        min_val: float = 0.0,
        max_val: float = 1.0,
        color_on: Optional[int] = None,
        color_off: Optional[int] = None,
    ) -> None:
        """
        Draw a vertical bar graph in a single column.

        The bar fills from row 7 (bottom) upward.  The number of lit pads is
        proportional to ``(value - min_val) / (max_val - min_val)``.

        Args:
            col:       Column index 0-7.
            value:     Current value to display.
            min_val:   Value that corresponds to an empty bar.  Default 0.0.
            max_val:   Value that corresponds to a full bar.  Default 1.0.
            color_on:  Colour for lit pads.  Defaults to green.
            color_off: Colour for unlit pads.  Defaults to off.
        """
        if color_on is None:
            color_on  = Mk1Color.GREEN if self.model == HardwareModel.MK1 else Mk2Color.GREEN
        if color_off is None:
            color_off = Mk1Color.OFF   if self.model == HardwareModel.MK1 else Mk2Color.OFF

        span = max_val - min_val
        ratio = (value - min_val) / span if span != 0 else 0.0
        ratio = max(0.0, min(1.0, ratio))
        lit_count = round(ratio * 8)

        for row in range(8):
            # row 7 = bottom = first to light
            lit = (7 - row) < lit_count
            self.set_led(row, col, color_on if lit else color_off)

    def draw_mixer(
        self,
        values: List[float],
        min_val: float = 0.0,
        max_val: float = 1.0,
        color_on: Optional[int] = None,
        color_off: Optional[int] = None,
    ) -> None:
        """
        Draw 8 vertical bar graphs across all columns.

        Args:
            values:    List of up to 8 float values, one per column.
            min_val:   Value mapping to an empty bar.  Default 0.0.
            max_val:   Value mapping to a full bar.  Default 1.0.
            color_on:  Colour for lit pads.  Defaults to green.
            color_off: Colour for unlit pads.  Defaults to off.
        """
        for col, val in enumerate(values[:8]):
            self.draw_bar(col, val, min_val, max_val, color_on, color_off)

    # ------------------------------------------------------------------
    # Button callbacks
    # ------------------------------------------------------------------

    def on_button_press(self, callback: Callable[[int, int], None]) -> None:
        """
        Register a callback fired whenever any pad is pressed.

        Args:
            callback: ``callback(row, col)`` — row/col of the pressed pad.
        """
        self._press_callbacks.append(callback)

    def on_button_release(self, callback: Callable[[int, int], None]) -> None:
        """
        Register a callback fired whenever any pad is released.

        Args:
            callback: ``callback(row, col)`` — row/col of the released pad.
        """
        self._release_callbacks.append(callback)

    def on_pad_press(self, row: int, col: int,
                     callback: Callable[[], None]) -> None:
        """
        Register a callback fired when a specific pad is pressed.

        Args:
            row:      Target pad row.
            col:      Target pad column.
            callback: Zero-argument callable.
        """
        key = (row, col)
        self._pad_press_callbacks.setdefault(key, []).append(callback)

    def on_pad_release(self, row: int, col: int,
                       callback: Callable[[], None]) -> None:
        """
        Register a callback fired when a specific pad is released.

        Args:
            row:      Target pad row.
            col:      Target pad column.
            callback: Zero-argument callable.
        """
        key = (row, col)
        self._pad_release_callbacks.setdefault(key, []).append(callback)

    def clear_callbacks(self) -> None:
        """Remove all registered press and release callbacks."""
        self._press_callbacks.clear()
        self._release_callbacks.clear()
        self._pad_press_callbacks.clear()
        self._pad_release_callbacks.clear()

    # ------------------------------------------------------------------
    # MIDI listener
    # ------------------------------------------------------------------

    def run(self, blocking: bool = True) -> None:
        """
        Start the MIDI input listener.

        Args:
            blocking: If ``True`` (default), block the calling thread until
                      ``disconnect()`` is called or a ``KeyboardInterrupt`` is
                      raised.  If ``False``, start a daemon background thread
                      and return immediately.
        """
        self._running = True
        if blocking:
            try:
                self._listen_loop()
            except KeyboardInterrupt:
                pass
        else:
            self._thread = threading.Thread(target=self._listen_loop, daemon=True)
            self._thread.start()

    def _listen_loop(self) -> None:
        """Internal: poll the MIDI input port until ``_running`` is False."""
        for msg in self._inport:
            if not self._running:
                break
            self._handle_message(msg)

    def _handle_message(self, msg) -> None:
        """
        Decode an incoming MIDI message and fire the appropriate callbacks.

        Note-on with velocity > 0 and CC with value > 0 are treated as presses;
        note-off or velocity/value == 0 are treated as releases.

        Args:
            msg: A ``mido.Message`` instance.
        """
        if msg.type == 'note_on':
            key = ('note', msg.note)
            pressed = msg.velocity > 0
        elif msg.type == 'note_off':
            key = ('note', msg.note)
            pressed = False
        elif msg.type == 'control_change':
            key = ('cc', msg.control)
            pressed = msg.value > 0
        else:
            return

        pad = self._reverse_map.get(key)
        if pad is None:
            return

        row, col = pad
        if pressed:
            self._fire_press(row, col)
        else:
            self._fire_release(row, col)

    def _fire_press(self, row: int, col: int) -> None:
        """Invoke all registered press callbacks for ``(row, col)``."""
        for cb in self._press_callbacks:
            cb(row, col)
        for cb in self._pad_press_callbacks.get((row, col), []):
            cb()

    def _fire_release(self, row: int, col: int) -> None:
        """Invoke all registered release callbacks for ``(row, col)``."""
        for cb in self._release_callbacks:
            cb(row, col)
        for cb in self._pad_release_callbacks.get((row, col), []):
            cb()

    # ------------------------------------------------------------------
    # Disconnect
    # ------------------------------------------------------------------

    def disconnect(self) -> None:
        """
        Stop the listener, restore standalone mode, and close MIDI ports.

        Sends a ``0x0E 0x00`` SysEx to return MK2/MK3/LPX to Live mode.
        Then closes the MIDI input and output ports.
        """
        self._running = False
        # Restore to standalone/Live mode (not programmer mode)
        if self.model != HardwareModel.MK1:
            if self.model == HardwareModel.MK2:
                device_id = 0x18
            elif self.model == HardwareModel.MK3:
                device_id = 0x0D
            else:
                device_id = 0x0C
            self._send_sysex(_NOVATION_HDR + (device_id, 0x0E, 0x00))
        self._inport.close()
        self._outport.close()

    # ------------------------------------------------------------------
    # Low-level MIDI send helpers
    # ------------------------------------------------------------------

    def _send_note_on(self, note: int, velocity: int, channel: int = 0) -> None:
        """
        Send a MIDI note-on message.

        Args:
            note:     MIDI note number 0-127.
            velocity: Velocity / colour index 0-127.
            channel:  MIDI channel 0-15 (0-indexed).  Channel 0 = static colour;
                      channel 1 = blink; channel 2 = pulse (MK2/MK3/LPX).
        """
        self._outport.send(mido.Message('note_on', note=note,
                                        velocity=velocity, channel=channel))

    def _send_cc(self, control: int, value: int) -> None:
        """
        Send a MIDI control-change message on channel 0.

        Args:
            control: CC number 0-127.
            value:   CC value 0-127 (used as colour index for top/side buttons).
        """
        self._outport.send(mido.Message('control_change', control=control,
                                        value=value, channel=0))

    def _send_sysex(self, data: Tuple[int, ...]) -> None:
        """
        Send a SysEx message.  The F0 / F7 framing bytes are added by mido.

        Args:
            data: Tuple of bytes to send between F0 and F7.
        """
        self._outport.send(mido.Message('sysex', data=data))


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def _run_demo() -> None:
    """
    Interactive demo: scale-grid colouring, note feedback, animated mixer.

    Run with:  python LaunchpadWrapper.py
    Press Ctrl+C to stop.
    """
    print("Connecting to Launchpad...")
    lp = LaunchpadWrapper.connect(input_port="Launchpad 0")
    print(f"Connected: {lp.model}")
    lp.clear()

    # Build a C Major scale grid
    grid = ScaleGrid("Major", root=0, octave=4)
    lp.color_scale_grid(grid)
    print("Scale grid drawn (C Major).  Press pads to see notes.")

    # On press: blink the pad and print the note
    def on_press(row: int, col: int) -> None:
        if row >= 0 and col < 8:
            info = grid.note_at(row, col)
            note_names = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
            name = note_names[info.note % 12] if info.valid else "?"
            print(f"  Pad ({row},{col}) -> MIDI {info.note} ({name})")
            lp.blink(row, col, Mk2Color.WHITE)

    def on_release(row: int, col: int) -> None:
        if row >= 0 and col < 8:
            # Restore scale colour
            info = grid.note_at(row, col)
            if info.is_root:
                color = Mk2Color.BLUE
            elif info.valid:
                color = Mk2Color.LIGHT_BLUE
            else:
                color = Mk2Color.OFF
            lp.set_led(row, col, color)

    lp.on_button_press(on_press)
    lp.on_button_release(on_release)

    # Animate a sine-wave mixer in the background
    stop_event = threading.Event()

    def animate_mixer() -> None:
        phase = 0.0
        while not stop_event.is_set():
            values = [
                0.5 + 0.5 * math.sin(phase + col * 0.8)
                for col in range(8)
            ]
            lp.draw_mixer(values)
            phase += 0.15
            time.sleep(0.05)

    mixer_thread = threading.Thread(target=animate_mixer, daemon=True)
    mixer_thread.start()

    try:
        lp.run(blocking=True)
    finally:
        stop_event.set()
        lp.disconnect()
        print("Disconnected.")


if __name__ == "__main__":
    _run_demo()
