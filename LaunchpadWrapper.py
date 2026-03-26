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

import json
import os
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
                 row_interval: int = _DIATONIC_ROW_INTERVAL,
                 intervals: Optional[List[int]] = None):
        """
        Initialise the scale grid.

        Args:
            scale_name:   Key into ``BUILTIN_SCALES``.  Defaults to ``"Major"``.
                          Ignored when ``intervals`` is provided.
            root:         Root semitone 0-11 (0=C).  Defaults to 0.
            octave:       Base octave number.  Defaults to 4 (middle C).
            row_interval: Scale degrees between adjacent rows.  Defaults to 2.
            intervals:    Optional explicit semitone-interval list (e.g.
                          ``[0, 2, 4, 5, 7, 9, 11]``).  When provided,
                          ``scale_name`` is ignored and the grid is built
                          directly from these intervals.
        """
        self._row_interval = row_interval
        self._highlight: Optional[int] = None
        if intervals is not None:
            self._scale_name = "Custom"
            self._scale      = intervals
            self._root       = root % 12
            self._octave     = octave
        else:
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
# Temperament / tuning system
# ---------------------------------------------------------------------------

# Chromatic note names (index 0 = C)
NOTE_NAMES: List[str] = [
    "C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"
]

# Reference pitch: A4 = MIDI note 69
_A4_MIDI = 69
_A4_FREQ = 440.0

# Just Intonation ratios (5-limit, relative to the root of each octave)
_JUST_RATIOS: List[float] = [
    1/1,      # unison
    16/15,    # minor second
    9/8,      # major second
    6/5,      # minor third
    5/4,      # major third
    4/3,      # perfect fourth
    45/32,    # augmented fourth / tritone
    3/2,      # perfect fifth
    8/5,      # minor sixth
    5/3,      # major sixth
    9/5,      # minor seventh
    15/8,     # major seventh
]

# Vallotti temperament: cent offsets from 12-TET for each pitch class (C=0..B=11).
# Vallotti is a well-temperament with pure fifths on F-C-G-D-A-E and
# tempered fifths on B-F#-C#-G#-D#-A#.
_VALLOTTI_CENTS: List[float] = [
    0.0,      # C
    -5.9,     # C#
    -3.9,     # D
    -2.0,     # D#
    -7.8,     # E
    +2.0,     # F
    -3.9,     # F#
    -2.0,     # G
    -3.9,     # G#
    -5.9,     # A
    0.0,      # A#
    -5.9,     # B
]

# Default path for the custom temperament JSON file
_CUSTOM_TEMPERAMENT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "custom_temperament.json"
)


class Temperament:
    """
    Maps MIDI note numbers to frequencies using a chosen tuning system.

    Supported built-in temperaments:
        - ``"equal"``  — 12-tone equal temperament (default)
        - ``"just"``   — 5-limit just intonation (relative to A4=440 Hz)
        - ``"vallotti"`` — Vallotti well-temperament
        - ``"custom"`` — Loaded from a JSON file (see ``custom_temperament.json``)

    Usage::

        t = Temperament("equal")
        t.frequency(69)          # 440.0
        t.note_display(69)       # "A4, 440.00Hz"

        t = Temperament("just")
        t.frequency(60)          # ~261.63 (C4 in just intonation)

        t = Temperament("custom", path="my_tuning.json")
    """

    BUILTIN = ("equal", "just", "vallotti", "custom")

    def __init__(self, name: str = "equal", *,
                 reference_freq: float = _A4_FREQ,
                 custom_path: Optional[str] = None):
        """
        Args:
            name:           Temperament name (one of ``BUILTIN``).
            reference_freq: Reference frequency for A4 in Hz.  Defaults to 440.
            custom_path:    Path to custom temperament JSON file.  Only used
                            when ``name="custom"``.  Defaults to
                            ``custom_temperament.json`` beside this script.
        """
        self.name = name.lower()
        self.reference_freq = reference_freq
        self._custom_path = custom_path or _CUSTOM_TEMPERAMENT_PATH

        if self.name not in self.BUILTIN:
            raise ValueError(
                f"Unknown temperament '{name}'. Available: {self.BUILTIN}")

        # Pre-compute cent offsets for each pitch class (0-11) relative to 12-TET
        self._cent_offsets: List[float] = [0.0] * 12
        if self.name == "just":
            self._cent_offsets = self._just_cents()
        elif self.name == "vallotti":
            self._cent_offsets = list(_VALLOTTI_CENTS)
        elif self.name == "custom":
            self._cent_offsets = self._load_custom()

    @staticmethod
    def _just_cents() -> List[float]:
        """Convert just-intonation ratios to cent deviations from 12-TET."""
        cents = []
        for i, ratio in enumerate(_JUST_RATIOS):
            just_cents = 1200.0 * math.log2(ratio)
            equal_cents = i * 100.0
            cents.append(just_cents - equal_cents)
        return cents

    def _load_custom(self) -> List[float]:
        """Load cent offsets from the custom temperament JSON file."""
        path = self._custom_path
        if not os.path.isfile(path):
            raise FileNotFoundError(
                f"Custom temperament file not found: {path}\n"
                f"Create one from the template with Temperament.write_custom_template()")
        with open(path, "r") as f:
            data = json.load(f)
        # Allow the custom file to override the reference frequency
        if "reference_freq" in data:
            self.reference_freq = float(data["reference_freq"])
        offsets = data.get("cent_offsets", {})
        result = [0.0] * 12
        for i, name in enumerate(NOTE_NAMES):
            result[i] = float(offsets.get(name, 0.0))
        return result

    def frequency(self, midi_note: int) -> float:
        """
        Return the frequency in Hz for a MIDI note number.

        Args:
            midi_note: MIDI note 0-127.

        Returns:
            Frequency in Hz.
        """
        pitch_class = midi_note % 12
        # 12-TET frequency, then apply temperament cent offset
        equal_freq = self.reference_freq * (2.0 ** ((midi_note - _A4_MIDI) / 12.0))
        cent_offset = self._cent_offsets[pitch_class]
        return equal_freq * (2.0 ** (cent_offset / 1200.0))

    def note_display(self, midi_note: int) -> str:
        """
        Return a human-readable string like ``"A4, 440.00Hz"``.

        Args:
            midi_note: MIDI note 0-127.

        Returns:
            String in the format ``"<name><octave>, <freq>Hz"``.
        """
        name = NOTE_NAMES[midi_note % 12]
        octave = (midi_note // 12) - 1
        freq = self.frequency(midi_note)
        return f"{name}{octave}, {freq:.2f}Hz"

    @staticmethod
    def write_custom_template(path: Optional[str] = None) -> str:
        """
        Write a template ``custom_temperament.json`` file.

        The file contains cent offsets for each pitch class (deviation from
        12-TET).  Edit the values to create your own temperament.

        Args:
            path: Output file path.  Defaults to ``custom_temperament.json``
                  beside this script.

        Returns:
            The path that was written.
        """
        path = path or _CUSTOM_TEMPERAMENT_PATH
        template = {
            "_comment": (
                "Custom temperament definition. "
                "Each value is a cent offset from 12-tone equal temperament. "
                "Positive values sharpen the note; negative values flatten it. "
                "A4 reference frequency can also be changed."
            ),
            "reference_freq": 440.0,
            "cent_offsets": {name: 0.0 for name in NOTE_NAMES},
        }
        with open(path, "w") as f:
            json.dump(template, f, indent=4)
        return path

    def __repr__(self) -> str:
        return f"Temperament({self.name!r}, reference_freq={self.reference_freq})"


# Default temperament instance (12-TET)
DEFAULT_TEMPERAMENT = Temperament("equal")


# ---------------------------------------------------------------------------
# Scale editor — Launchpad95 scale/key/mode UI emulation
# ---------------------------------------------------------------------------

# Legacy alias kept for internal use by the scale editor
_SE_KEY_NAMES = NOTE_NAMES

# Circle of fifths: step by a perfect fifth (7 semitones) each time
_SE_CIRCLE_OF_FIFTHS: List[int] = [7 * k % 12 for k in range(12)]

# White-key semitone offsets for C D E F G A B (indices 0–6)
_SE_WHITE_KEYS: List[int] = [0, 2, 4, 5, 7, 9, 11]

# Maximum octave index for each layout mode (mirrors ScaleComponent.TOP_OCTAVE)
_SE_TOP_OCTAVE: Dict[str, int] = {
    "chromatic_gtr":   7,
    "diatonic_ns":     2,
    "diatonic_chords": 7,
    "diatonic":        6,
    "chromatic":       7,
}

# Scale mode table: (name, semitone-interval list).
# Index ordering mirrors Ableton Live's ``get_all_scales_ordered()`` so that
# indices 1, 11, 12, 13, 14 match the relative-scale logic in ScaleComponent.
SCALE_MODES: List[Tuple[str, List[int]]] = [
    ("Major",             [0, 2, 4, 5, 7, 9, 11]),                      # 0  Ionian
    ("Minor",             [0, 2, 3, 5, 7, 8, 10]),                      # 1  Aeolian / Natural Minor
    ("Dorian",            [0, 2, 3, 5, 7, 9, 10]),                      # 2
    ("Phrygian",          [0, 1, 3, 5, 7, 8, 10]),                      # 3
    ("Lydian",            [0, 2, 4, 6, 7, 9, 11]),                      # 4
    ("Mixolydian",        [0, 2, 4, 5, 7, 9, 10]),                      # 5
    ("Locrian",           [0, 1, 3, 5, 6, 8, 10]),                      # 6
    ("Diminished",        [0, 2, 3, 5, 6, 8, 9, 11]),                   # 7  whole-half
    ("Whole Tone",        [0, 2, 4, 6, 8, 10]),                         # 8
    ("Half-Whole Dim",    [0, 1, 3, 4, 6, 7, 9, 10]),                   # 9
    ("Blues",             [0, 3, 5, 6, 7, 10]),                         # 10
    ("Minor Pentatonic",  [0, 3, 5, 7, 10]),                            # 11
    ("Major Pentatonic",  [0, 2, 4, 7, 9]),                             # 12
    ("Harmonic Minor",    [0, 2, 3, 5, 7, 8, 11]),                      # 13
    ("Melodic Minor",     [0, 2, 3, 5, 7, 9, 11]),                      # 14
    ("Chromatic",         [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]),     # 15
    # --- Row 6 (pad positions (6,0)–(6,7)) ---
    ("Bhairav",           [0, 1, 4, 5, 7, 8, 11]),                    # 16
    ("Hunga. Minor",      [0, 2, 3, 6, 7, 8, 11]),                    # 17  Hungarian Minor
    ("Minor Gypsy",       [0, 1, 4, 5, 7, 8, 10]),                    # 18
    ("Hirojoshi",         [0, 2, 3, 7, 8]),                            # 19
    ("In-Sen",            [0, 1, 5, 7, 10]),                           # 20
    ("Iwato",             [0, 1, 5, 6, 10]),                           # 21
    ("Kumoi",             [0, 2, 3, 7, 9]),                            # 22
    ("Pelog",             [0, 1, 3, 7, 8]),                            # 23
    # --- Row 7 (pad positions (7,0)–(7,1)) ---
    ("Spanish",           [0, 1, 3, 4, 5, 7, 8, 10]),                 # 24  Spanish Phrygian / Jewish
    ("IonEol",            [0, 2, 4, 5, 7, 8, 9, 11]),                 # 25  Ionian / Aeolian mixed
]


class ScaleEditorColorsMK2:
    """
    Mk2Color palette indices for each scale-editor UI element.

    Mirrors ``Colors.Scale`` in ``SkinMK2.py``.

    Colour reference (MK2 palette index → hue):
        5  = RED, 7  = RED_THIRD, 9  = AMBER, 11 = AMBER_THIRD,
        21 = GREEN, 23 = GREEN_THIRD, 45 = BLUE, 47 = BLUE_THIRD.
    """
    KEY_ON          = 21   # GREEN
    KEY_OFF         = 23   # GREEN_THIRD
    ABS_ROOT_ON     = 5    # RED
    ABS_ROOT_OFF    = 7    # RED_THIRD
    HORIZONTAL_ON   = 21   # GREEN
    HORIZONTAL_OFF  = 23   # GREEN_THIRD
    MODE_ON         = 5    # RED
    MODE_OFF        = 7    # RED_THIRD
    CIRCLE_5THS     = 45   # BLUE
    RELATIVE_SCALE  = 45   # BLUE
    OCTAVE_ON       = 5    # RED
    OCTAVE_OFF      = 7    # RED_THIRD
    MODUS_ON        = 45   # BLUE
    MODUS_OFF       = 47   # BLUE_THIRD
    QUICK_SCALE_ON  = 9    # AMBER
    QUICK_SCALE_OFF = 11   # AMBER_THIRD
    DISABLED        = 0    # BLACK


class ScaleEditorColorsMK1:
    """
    Mk1Color velocity-byte values for each scale-editor UI element.

    Mirrors ``Colors.Scale`` in ``SkinMK1.py``.

    Encoding: ``bits[5:4]`` = green intensity (0–3),
              ``bits[1:0]`` = red intensity (0–3),
              ``bits[3:2]`` = 0b11 (copy/clear flag).
    """
    KEY_ON          = 0x1F  # AMBER        (green=1, red=3)
    KEY_OFF         = 0x1D  # LOW_AMBER    (green=1, red=1)
    ABS_ROOT_ON     = 0x1F  # AMBER
    ABS_ROOT_OFF    = 0x1D  # LOW_AMBER
    HORIZONTAL_ON   = 0x3C  # GREEN        (LIME proxy; green=3, red=0)
    HORIZONTAL_OFF  = 0x1F  # AMBER        (MANDARIN proxy)
    MODE_ON         = 0x0F  # RED          (green=0, red=3)
    MODE_OFF        = 0x0D  # LOW_RED      (green=0, red=1)
    CIRCLE_5THS     = 0x0F  # RED
    RELATIVE_SCALE  = 0x0F  # RED
    OCTAVE_ON       = 0x0F  # RED
    OCTAVE_OFF      = 0x0D  # LOW_RED
    MODUS_ON        = 0x3C  # GREEN
    MODUS_OFF       = 0x1C  # LOW_GREEN    (green=1, red=0)
    QUICK_SCALE_ON  = 0x1F  # AMBER
    QUICK_SCALE_OFF = 0x1D  # LOW_AMBER
    DISABLED        = 0x0C  # OFF


class ScaleEditorMode:
    """
    Emulates the Launchpad95 Ableton scale-editor UI on a standalone Launchpad.

    The 8×8 grid becomes a scale / key / mode selector identical to the
    ``ScaleComponent`` in the Ableton Remote Script::

        Row 0: [abs_root][horizontal][chromatic_gtr][diatonic_ns]
               [diatonic_chords][diatonic][chromatic][drumrack]
        Row 1: [C#][D#][rel_scale][F#][G#][A#][<-5ths][quick_scale]
        Row 2: [C][D][E][F][G][A][B][5ths->]
        Row 3: [oct0][oct1]...[oct{top-1}]  (disabled beyond top_octave)
        Row 4: [mode 0][mode 1]...[mode 7]
        Row 5: [mode 8]...[mode 15]
        Row 6: [mode 16]...[mode 23]
        Row 7: [mode 24]...[mode 31]

    **Typical usage**::

        editor = ScaleEditorMode(key=0, octave=3, modus=0)
        lp.run_scale_editor(editor)        # draws + blocks; Ctrl-C to stop

        # After returning, use the result to light the instrument grid:
        grid = editor.get_scale_grid()
        lp.color_scale_grid(grid)

    Attributes:
        key (int):            Root note 0–11 (0 = C).
        octave (int):         Octave register index (0 to top_octave − 1).
        modus (int):          Index into :data:`SCALE_MODES`.
        mode (str):           Layout mode; one of the :data:`_SE_TOP_OCTAVE`
                              keys or ``"drumrack"``.
        is_absolute (bool):   Absolute root-anchoring toggle.
        is_horizontal (bool): Horizontal layout toggle.
        quick_scale (bool):   Quick-scale overlay toggle.
        on_change (callable): Optional ``callback(editor)`` fired on every
                              state change (key, octave, modus, mode, toggles).
    """

    def __init__(
        self,
        key: int = 0,
        octave: int = 3,
        modus: int = 0,
        mode: str = "diatonic",
        is_absolute: bool = False,
        is_horizontal: bool = True,
        on_change: Optional[Callable] = None,
    ):
        """
        Args:
            key:           Root note semitone 0–11 (0 = C).
            octave:        Initial octave register (0 to top_octave − 1).
            modus:         Initial scale mode index into :data:`SCALE_MODES`.
            mode:          Initial layout mode (see :data:`_SE_TOP_OCTAVE`).
            is_absolute:   Start with absolute root anchoring enabled.
            is_horizontal: Start with horizontal layout enabled.
            on_change:     Optional ``callback(editor)`` called after any
                           state change.
        """
        self.key            = key % 12
        self.modus          = modus
        self.mode           = mode
        self.is_absolute    = is_absolute
        self.is_horizontal  = is_horizontal
        self.quick_scale    = False
        self.on_change      = on_change

        self._top_octave    = _SE_TOP_OCTAVE.get(mode, 6)
        self.octave         = max(0, min(octave, self._top_octave - 1))

        # State for relative-scale button (row 1, col 2)
        self._current_minor_mode = 1          # Natural Minor by default
        self._minor_modes        = [1, 13, 14]  # Natural, Harmonic, Melodic

    # ------------------------------------------------------------------
    # Read-only convenience properties
    # ------------------------------------------------------------------

    @property
    def scale_name(self) -> str:
        """Name of the currently selected scale mode (e.g. ``"Major"``)."""
        return SCALE_MODES[self.modus][0]

    @property
    def scale_intervals(self) -> List[int]:
        """Semitone intervals for the current scale mode."""
        return SCALE_MODES[self.modus][1]

    @property
    def key_name(self) -> str:
        """Name of the root note (e.g. ``"C#"``)."""
        return _SE_KEY_NAMES[self.key]

    @property
    def _is_drumrack(self) -> bool:
        return self.mode == "drumrack"

    @property
    def _is_diatonic(self) -> bool:
        return self.mode in ("diatonic", "diatonic_ns", "diatonic_chords")

    # ------------------------------------------------------------------
    # State mutators
    # ------------------------------------------------------------------

    def set_key(self, key: int) -> None:
        """Set the root note (0–11)."""
        if 0 <= key <= 11:
            self.key = key
            self._notify()

    def set_octave(self, octave: int) -> None:
        """Set the octave register (clamped to valid range for current mode)."""
        if 0 <= octave < self._top_octave:
            self.octave = octave
            self._notify()

    def octave_up(self) -> None:
        """Shift the register up by one octave."""
        self.set_octave(self.octave + 1)

    def octave_down(self) -> None:
        """Shift the register down by one octave."""
        self.set_octave(self.octave - 1)

    def set_modus(self, index: int) -> None:
        """Select a scale mode by index into :data:`SCALE_MODES`."""
        if 0 <= index < len(SCALE_MODES):
            self.modus = index
            self._notify()

    def set_mode(self, mode: str) -> None:
        """
        Set the layout mode and update the valid octave range.

        Args:
            mode: One of ``"diatonic"``, ``"diatonic_ns"``,
                  ``"diatonic_chords"``, ``"chromatic"``,
                  ``"chromatic_gtr"``, or ``"drumrack"``.
        """
        self.mode        = mode
        self._top_octave = _SE_TOP_OCTAVE.get(mode, 6)
        if self.octave >= self._top_octave:
            self.octave = self._top_octave - 1
        self._notify()

    def shift_fifth_up(self) -> None:
        """Move one step clockwise on the circle of fifths (+7 semitones)."""
        idx      = _SE_CIRCLE_OF_FIFTHS.index(self.key)
        self.key = _SE_CIRCLE_OF_FIFTHS[(idx + 1) % 12]
        self._notify()

    def shift_fifth_down(self) -> None:
        """Move one step counter-clockwise on the circle of fifths (−7 semitones)."""
        idx      = _SE_CIRCLE_OF_FIFTHS.index(self.key)
        self.key = _SE_CIRCLE_OF_FIFTHS[(idx - 1 + 12) % 12]
        self._notify()

    def _notify(self) -> None:
        if self.on_change:
            self.on_change(self)

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, lp: "LaunchpadWrapper") -> None:
        """
        Render the scale-editor UI onto the Launchpad 8×8 grid.

        Mirrors ``ScaleComponent.update()`` from the Ableton Remote Script.
        Call after any state change, or use :meth:`LaunchpadWrapper.run_scale_editor`
        which wires this automatically.

        Args:
            lp: Connected :class:`LaunchpadWrapper` instance.
        """
        c         = ScaleEditorColorsMK1 if lp.model == HardwareModel.MK1 else ScaleEditorColorsMK2
        num_modes = len(SCALE_MODES)
        for row in range(8):
            for col in range(8):
                lp.set_led(row, col, self._cell_color(row, col, c, num_modes))

    def _cell_color(self, row: int, col: int, c, num_modes: int) -> int:
        """Return the LED color index for pad ``(row, col)`` given current state."""

        # --- Row 0: layout-mode toggle buttons ---
        if row == 0:
            if col == 0:
                return c.ABS_ROOT_ON    if self.is_absolute   else c.ABS_ROOT_OFF
            if col == 1:
                return c.HORIZONTAL_ON  if self.is_horizontal else c.HORIZONTAL_OFF
            if col == 2:
                return c.MODE_ON if (not self._is_drumrack and self.mode == "chromatic_gtr")   else c.MODE_OFF
            if col == 3:
                return c.MODE_ON if (not self._is_drumrack and self.mode == "diatonic_ns")     else c.MODE_OFF
            if col == 4:
                return c.MODE_ON if (not self._is_drumrack and self.mode == "diatonic_chords") else c.MODE_OFF
            if col == 5:
                return c.MODE_ON if (not self._is_drumrack and self.mode == "diatonic")        else c.MODE_OFF
            if col == 6:
                return c.MODE_ON if (not self._is_drumrack and self.mode == "chromatic")       else c.MODE_OFF
            # col == 7: drumrack button
            return c.MODE_ON if self._is_drumrack else c.MODE_OFF

        # --- Row 1: black keys / circle-of-5ths ← / relative-scale / quick-scale ---
        if row == 1:
            if self._is_drumrack:
                return c.QUICK_SCALE_ON if (col == 7 and self.quick_scale) else (
                    c.QUICK_SCALE_OFF if col == 7 else c.DISABLED
                )
            if col in (0, 1, 3, 4, 5):   # C#  D#  [gap]  F#  G#  A#
                return c.KEY_ON if self.key == _SE_WHITE_KEYS[col] + 1 else c.KEY_OFF
            if col == 2:
                return c.RELATIVE_SCALE
            if col == 6:
                return c.CIRCLE_5THS
            # col == 7
            return c.QUICK_SCALE_ON if self.quick_scale else c.QUICK_SCALE_OFF

        # --- Row 2: white keys / circle-of-5ths → ---
        if row == 2:
            if self._is_drumrack:
                return c.DISABLED
            if col < 7:               # C  D  E  F  G  A  B
                return c.KEY_ON if self.key == _SE_WHITE_KEYS[col] else c.KEY_OFF
            return c.CIRCLE_5THS      # col == 7

        # --- Row 3: octave selector ---
        if row == 3:
            if self.octave == col:
                return c.OCTAVE_ON
            return c.OCTAVE_OFF if col < self._top_octave else c.DISABLED

        # --- Rows 4–7: scale mode (modus) selector, 8 per row ---
        if not self._is_drumrack:
            mode_idx = (row - 4) * 8 + col
            if mode_idx < num_modes:
                return c.MODUS_ON if self.modus == mode_idx else c.MODUS_OFF
        return c.DISABLED

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def handle_press(self, lp: "LaunchpadWrapper", row: int, col: int) -> None:
        """
        Process a single pad press and update internal state.

        Mirrors ``ScaleComponent._matrix_pressed()`` from the Ableton Remote
        Script.  Called automatically when the editor is active via
        :meth:`LaunchpadWrapper.run_scale_editor`; also callable directly.

        Args:
            lp:  :class:`LaunchpadWrapper` used for LED feedback after update.
            row: Pressed pad row 0–7.
            col: Pressed pad column 0–7.
        """
        # --- Row 0: layout-mode selection ---
        if row == 0:
            if not self._is_drumrack:
                if col == 0:
                    self.is_absolute   = not self.is_absolute
                if col == 1 and self._is_diatonic:
                    self.is_horizontal = not self.is_horizontal
            if   col == 2:
                self.mode          = "chromatic_gtr"
                self.is_horizontal = True
            elif col == 3:
                self.mode          = "diatonic_ns"
                self.is_horizontal = True
            elif col == 4:
                self.mode          = "diatonic_chords"
                self.is_horizontal = False
            elif col == 5:
                self.mode          = "diatonic"
                self.is_horizontal = True
            elif col == 6:
                self.mode          = "chromatic"
                self.is_horizontal = True
            elif col == 7:
                self.mode          = "drumrack"
            self._top_octave = _SE_TOP_OCTAVE.get(self.mode, 6)
            if self.octave >= self._top_octave:
                self.octave = self._top_octave - 1

        # --- Rows 1–2: root note, circle of fifths, relative scale ---
        if not self._is_drumrack:
            root      = -1
            new_modus = self.modus

            if row == 2 and col < 7:                      # white keys: C D E F G A B
                root = _SE_WHITE_KEYS[col]
            elif row == 1 and col in (0, 1, 3, 4, 5):    # black keys: C# D# F# G# A#
                root = _SE_WHITE_KEYS[col] + 1
            elif row == 2 and col == 7:                   # circle of fifths →
                root = _SE_CIRCLE_OF_FIFTHS[
                    (_SE_CIRCLE_OF_FIFTHS.index(self.key) + 1) % 12
                ]
            elif row == 1 and col == 6:                   # circle of fifths ←
                root = _SE_CIRCLE_OF_FIFTHS[
                    (_SE_CIRCLE_OF_FIFTHS.index(self.key) - 1 + 12) % 12
                ]
            elif row == 1 and col == 2:                   # relative-scale toggle
                if self.modus == 0:                           # Major → relative minor
                    new_modus = self._current_minor_mode
                    root = _SE_CIRCLE_OF_FIFTHS[
                        (_SE_CIRCLE_OF_FIFTHS.index(self.key) + 3) % 12
                    ]
                elif self.modus in (1, 13, 14):               # minor variants → relative major
                    self._current_minor_mode = self.modus
                    new_modus = 0
                    root = _SE_CIRCLE_OF_FIFTHS[
                        (_SE_CIRCLE_OF_FIFTHS.index(self.key) - 3 + 12) % 12
                    ]
                elif self.modus == 11:                        # Minor Pentatonic ↔ Major Pentatonic
                    new_modus = 12
                    root = _SE_CIRCLE_OF_FIFTHS[
                        (_SE_CIRCLE_OF_FIFTHS.index(self.key) - 3 + 12) % 12
                    ]
                elif self.modus == 12:
                    new_modus = 11
                    root = _SE_CIRCLE_OF_FIFTHS[
                        (_SE_CIRCLE_OF_FIFTHS.index(self.key) + 3) % 12
                    ]

            if root != -1:
                self.modus = new_modus
                self.key   = root

        # --- Row 1, col 7: quick-scale toggle ---
        if row == 1 and col == 7:
            self.quick_scale = not self.quick_scale

        # --- Row 3: octave selector ---
        if row == 3 and 0 <= col < self._top_octave:
            self.octave = col

        # --- Rows 4–7: scale mode (modus) selector ---
        if row >= 4 and not self._is_drumrack:
            mode_idx = (row - 4) * 8 + col
            if 0 <= mode_idx < len(SCALE_MODES):
                self.modus = mode_idx

        self._notify()
        self.draw(lp)

    # ------------------------------------------------------------------
    # ScaleGrid factory
    # ------------------------------------------------------------------

    def get_scale_grid(self, row_interval: int = 3) -> "ScaleGrid":
        """
        Build a :class:`ScaleGrid` from the current editor state.

        The grid uses the current root note, scale intervals, and octave
        register.  Pass it to :meth:`LaunchpadWrapper.color_scale_grid` to
        light up playable notes in the instrument layout.

        Args:
            row_interval: Scale degrees between adjacent rows (default 3,
                          matching ``ScaleComponent._interval``).

        Returns:
            :class:`ScaleGrid` configured for the current scale/key/octave.
        """
        return ScaleGrid(
            intervals=self.scale_intervals,
            root=self.key,
            octave=self.octave,
            row_interval=row_interval,
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

    def run_scale_editor(
        self,
        editor: "ScaleEditorMode",
        blocking: bool = True,
    ) -> None:
        """
        Activate the scale-editor UI: draw it and register pad callbacks.

        Every pad press on the 8×8 grid is routed to
        :meth:`ScaleEditorMode.handle_press`, which updates the editor state
        and redraws automatically.  To deactivate, call
        :meth:`clear_callbacks` (and optionally :meth:`clear`).

        Example::

            editor = ScaleEditorMode(key=0, octave=3, modus=0)
            lp.run_scale_editor(editor)           # blocks until Ctrl-C
            grid = editor.get_scale_grid()
            lp.color_scale_grid(grid)             # show result on instrument

        Args:
            editor:   :class:`ScaleEditorMode` instance to activate.
            blocking: If ``True`` (default), calls :meth:`run` to block until
                      ``Ctrl+C`` or :meth:`disconnect`.  If ``False``, only
                      draws and registers callbacks, then returns immediately
                      (useful when calling :meth:`run` separately or running
                      in a background thread).
        """
        editor.draw(self)

        def _on_press(row: int, col: int) -> None:
            if 0 <= row <= 7 and 0 <= col <= 7:
                editor.handle_press(self, row, col)

        self.on_button_press(_on_press)
        if blocking:
            self.run(blocking=True)

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
    Two-phase interactive demo: scale editor + instrument play.

    Run with:  python LaunchpadWrapper.py
    Press Ctrl+C to stop.

    Phase 1 — Scale Editor (starts here):
        The full 8×8 grid shows the Launchpad95 scale/key/mode UI.
        Use the pads to pick a root note, scale mode, octave, and layout.
        Navigate the circle of fifths or jump to the relative scale.
        Press the top-right automap button to switch to instrument mode.

    Phase 2 — Instrument / Play:
        The grid is recoloured by the scale chosen in Phase 1.
        Press pads to see the MIDI note name printed in the console.
        Press the top-right automap button again to return to the editor.
    """
    print("Connecting to Launchpad...")
    lp = LaunchpadWrapper.connect()
    print(f"Connected: {lp.model}")
    lp.clear()

    # Resolve per-hardware colour constants once
    if lp.model == HardwareModel.MK1:
        root_c, scale_c, off_c, press_c = (
            Mk1Color.AMBER, Mk1Color.GREEN, Mk1Color.OFF, Mk1Color.YELLOW
        )
    else:
        root_c, scale_c, off_c, press_c = (
            Mk2Color.BLUE, Mk2Color.LIGHT_BLUE, Mk2Color.OFF, Mk2Color.WHITE
        )

    editor = ScaleEditorMode(key=0, octave=3, modus=0)
    tuning = [DEFAULT_TEMPERAMENT]  # mutable cell for active temperament
    mode   = ["editor"]   # mutable cell: "editor" | "instrument"

    def show_editor() -> None:
        mode[0] = "editor"
        lp.clear()
        editor.draw(lp)
        print(f"\n[Scale Editor]  {editor.key_name} {editor.scale_name}"
              f"  oct={editor.octave}  layout={editor.mode}")
        print("  Top-right automap button → instrument mode")

    def show_instrument() -> None:
        mode[0] = "instrument"
        lp.clear()
        lp.color_scale_grid(
            editor.get_scale_grid(),
            root_color=root_c,
            in_scale_color=scale_c,
            off_color=off_c,
        )
        print(f"\n[Instrument]  {editor.key_name} {editor.scale_name}"
              f"  oct={editor.octave}  layout={editor.mode}")
        print("  Press pads to see notes.  Top-right automap button → scale editor")

    def on_press(row: int, col: int) -> None:
        # Top-right automap button toggles between editor and instrument
        if row == -1 and col == 7:
            if mode[0] == "editor":
                show_instrument()
            else:
                show_editor()
            return

        if mode[0] == "editor":
            if 0 <= row <= 7 and 0 <= col <= 7:
                editor.handle_press(lp, row, col)
                print(f"  {editor.key_name} {editor.scale_name}"
                      f"  oct={editor.octave}  layout={editor.mode}")

        elif mode[0] == "instrument":
            if 0 <= row <= 7 and col < 8:
                info = editor.get_scale_grid().note_at(row, col)
                if info.valid:
                    display = tuning[0].note_display(info.note)
                    print(f"  Pad ({row},{col}) → MIDI {info.note} ({display})")
                lp.set_led(row, col, press_c)

    def on_release(row: int, col: int) -> None:
        if mode[0] == "instrument" and 0 <= row <= 7 and col < 8:
            info = editor.get_scale_grid().note_at(row, col)
            lp.set_led(row, col,
                       root_c if info.is_root else (scale_c if info.valid else off_c))

    lp.on_button_press(on_press)
    lp.on_button_release(on_release)
    show_editor()

    try:
        lp.run(blocking=True)
    finally:
        lp.disconnect()
        print("Disconnected.")


if __name__ == "__main__":
    _run_demo()
