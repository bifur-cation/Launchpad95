"""
ColorsMK1.py — LED colour palette for the Launchpad MK1/Mini/S.

The original Launchpad hardware uses a 2-bit red + 2-bit green LED matrix,
giving a palette of solid colours (plus blink variants).  Each ``Color``
value is an integer in the range 0–127 that maps to a specific LED velocity
sent over MIDI.

The ``Rgb`` class groups these ``Color`` instances by hue for easy reference
from ``SkinMK1.py``.

Blink colours are indicated by the ``_BLINK`` suffix; their MIDI values
trigger the hardware's internal blink mode.
"""

from _Framework.ButtonElement import Color


class Rgb:
    """
    Named colour constants for the Launchpad MK1 / Mini / S LED palette.

    Each attribute is a :class:`Color` instance whose ``midi_value`` is the
    raw velocity byte sent to the Launchpad to light the corresponding LED.

    Colour groups
    -------------
    BLACK        : LED off
    RED          : solid red at three intensities (FULL, HALF, THIRD)
    RED_BLINK    : blinking red at three intensities
    GREEN        : solid green at three intensities
    GREEN_BLINK  : blinking green at three intensities
    AMBER        : solid amber (red + green) at three intensities
    AMBER_BLINK  : blinking amber at three intensities
    YELLOW       : solid yellow (brighter than amber) at two intensities
    YELLOW_BLINK : blinking yellow
    ORANGE       : solid orange at two intensities
    ORANGE_BLINK : blinking orange
    MANDARIN     : solid mandarin (warm orange) + blink
    LIME         : solid lime green + blink
    """

    # --- Off ---
    BLACK = Color(4)

    # --- Red (solid) ---
    RED = Color(7)
    RED_FULL = Color(7)
    RED_HALF = Color(6)
    RED_THIRD = Color(5)

    # --- Red (blink) ---
    RED_BLINK = Color(11)
    RED_BLINK_HALF = Color(10)
    RED_BLINK_THIRD = Color(9)

    # --- Green (solid) ---
    GREEN = Color(52)
    GREEN_FULL = Color(52)
    GREEN_HALF = Color(36)
    GREEN_THIRD = Color(20)

    # --- Green (blink) ---
    GREEN_BLINK = Color(56)
    GREEN_BLINK_HALF = Color(40)
    GREEN_BLINK_THIRD = Color(24)

    # --- Amber (solid) ---
    AMBER = Color(55)
    AMBER_FULL = Color(55)
    AMBER_HALF = Color(38)
    AMBER_THIRD = Color(21)

    # --- Amber (blink) ---
    AMBER_BLINK = Color(59)
    AMBER_BLINK_HALF = Color(42)
    AMBER_BLINK_THIRD = Color(25)

    # --- Yellow (solid) ---
    YELLOW = Color(54)
    YELLOW_FULL = Color(54)
    YELLOW_HALF = Color(37)

    # --- Yellow (blink) ---
    YELLOW_BLINK = Color(58)
    YELLOW_BLINK_HALF = Color(41)

    # --- Orange (solid) ---
    ORANGE = Color(39)
    ORANGE_FULL = Color(39)
    ORANGE_HALF = Color(22)

    # --- Orange (blink) ---
    ORANGE_BLINK = Color(43)
    ORANGE_BLINK_HALF = Color(26)

    # --- Misc warm tones ---
    MANDARIN = Color(23)
    MANDARIN_FULL = Color(23)
    MANDARIN_BLINK = Color(27)

    LIME = Color(53)
    LIME_FULL = Color(53)
    LIME_BLINK = Color(57)
