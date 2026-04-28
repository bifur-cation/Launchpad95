"""
Settings.py — User-configurable settings for Launchpad95.

Edit the class attributes below to customise the behaviour of the script
without touching any other source file.  All settings live as class-level
attributes on ``Settings`` so they can be imported and read from anywhere with::

    from .Settings import Settings
    if Settings.LOGGING:
        ...
"""


class Settings():
    """
    Central configuration class for Launchpad95.

    All attributes are class-level constants; no instance is ever created.

    Attributes:
        SESSION__STOP_BUTTONS (bool):
            When ``True``, adds clip-stop buttons along the bottom row of the
            Session grid.  Experimental — may interfere with some layouts.

        SESSION__LINK (bool):
            When ``True``, multiple Launchpad95 instances running simultaneously
            will link their Session views so they pan together.  Experimental.

        STEPSEQ__LINK_WITH_SESSION (bool):
            When ``True``, the Step Sequencer scrolls in sync with the Session
            view when multiple Launchpad95 instances are linked.  Experimental.

        STEPSEQ__AUTO_SCROLL (bool):
            When ``True``, the Step Sequencer automatically scrolls to the page
            that is currently playing back.

        USER_MODES_1 (list[str]):
            Sub-modes cycled through by the User 1 button.
            Supported values: ``"instrument"``, ``"device"``, ``"user 1"``.

        USER_MODES_2 (list[str]):
            Sub-modes cycled through by the User 2 button.
            Supported values: ``"drum stepseq"``, ``"melodic stepseq"``,
            ``"user 2"``.

        DEVICE_CONTROLLER__STEPLESS_MODE (bool):
            Initial state for stepless faders in Device Controller mode.
            When ``True`` parameter changes animate smoothly instead of jumping.

        VELOCITY_THRESHOLD_MAX (int):
            MIDI velocity (0–127) above which a parameter change is applied
            instantly, bypassing the stepless animation.

        VELOCITY_THRESHOLD_MIN (int):
            Minimum MIDI velocity used for the gradient calculation.  Values
            below this are clamped to this threshold.

        VELOCITY_FACTOR (float):
            Denominator constant that scales the per-roundtrip parameter
            change.  Higher values produce slower movement.

        USE_CUSTOM_DEVICE_CONTROL_COLORS (bool):
            When ``True``, each device slider column uses its own colour
            (``Device.CustomSlider0`` … ``Device.CustomSlider7``).
            When ``False``, all columns share ``Device.DefaultSlider``.

        ENABLE_TDC (bool):
            Enable Time-Dependent Control (TDC).  When ``True``, how long a
            button is held determines the speed of the parameter change —
            longer presses produce slower changes.

        TDC_MAX_TIME (float):
            The hold duration in seconds that corresponds to the slowest
            (index 9) entry in ``TDC_MAP``.

        TDC_MAP (list[float]):
            Ten entries mapping a normalised hold time (0 → ``TDC_MAX_TIME``)
            to a target round-trip time in seconds.  Index 0 is instantaneous;
            index 9 is the slowest.

        LOGGING (bool):
            Enable file-based debug logging to
            ``~/Documents/Ableton/User Library/Remote Scripts/log.txt``.

        VOLUME_LEVELS (tuple[int]):
            Exactly 7 dB values mapped to the upper seven buttons of a volume
            slider column.  The lowest button is always −∞.  Minimum supported
            value is −69 dB.
    """

    # ------------------------------------------------------------------ #
    # Session mode                                                         #
    # ------------------------------------------------------------------ #

    # Add Stop buttons at the bottom of the Session. Experimental
    SESSION__STOP_BUTTONS = False

    # Link sessions between multiple Launchpad95 instances. Experimental
    SESSION__LINK = False

    # Link step sequencer to follow the session position. Experimental
    STEPSEQ__LINK_WITH_SESSION = False

    # Auto-scroll the step sequencer to the currently playing page
    STEPSEQ__AUTO_SCROLL = False

    # ------------------------------------------------------------------ #
    # User mode button assignments                                         #
    # ------------------------------------------------------------------ #

    # Sub-modes for the User 1 button (cycles on repeated press)
    USER_MODES_1 = [
        "instrument",
        "device",
        # "user 1",  # uncomment to expose raw User 1 MIDI passthrough
    ]

    # Sub-modes for the User 2 button (cycles on repeated press)
    USER_MODES_2 = [
        "drum stepseq",
        "melodic stepseq",
        # "user 2",  # uncomment to expose raw User 2 MIDI passthrough
    ]

    # ------------------------------------------------------------------ #
    # Device Controller fader behaviour                                   #
    # ------------------------------------------------------------------ #

    # Enable stepless (animated) fader mode by default
    DEVICE_CONTROLLER__STEPLESS_MODE = True

    # Velocity above which changes are applied instantly (no animation)
    VELOCITY_THRESHOLD_MAX = 100

    # Minimum velocity used in the gradient formula
    VELOCITY_THRESHOLD_MIN = 40

    # Scaling factor for the per-round-trip change amount.
    # Formula: change = (velocity^3) / VELOCITY_FACTOR
    VELOCITY_FACTOR = (127 ** 2) * (127 / 2)

    # Use per-column custom slider colours instead of the single default colour
    USE_CUSTOM_DEVICE_CONTROL_COLORS = False

    # ------------------------------------------------------------------ #
    # Time-Dependent Control (TDC)                                        #
    # ------------------------------------------------------------------ #

    # Enable TDC — hold time determines movement speed
    ENABLE_TDC = True

    # Maximum hold time (seconds) → slowest speed (TDC_MAP[-1])
    TDC_MAX_TIME = 2.0

    # Round-trip time (seconds) for each TDC hold-time bucket.
    # Index 0 = instant, index 9 = ~40 s full-range sweep.
    TDC_MAP = [0, 0.75, 1.5, 3, 5, 8, 12, 17, 25, 40]

    # ------------------------------------------------------------------ #
    # Debugging                                                            #
    # ------------------------------------------------------------------ #

    # Write debug output to ~/Documents/Ableton/User Library/Remote Scripts/log.txt
    LOGGING = False

    # ------------------------------------------------------------------ #
    # Volume slider levels                                                 #
    # ------------------------------------------------------------------ #

    # dB values for the 7 upper buttons of each volume column.
    # The 8th (bottom) button is always −∞.  Lowest valid value: −69 dB.
    VOLUME_LEVELS = (6, 0, -6, -12, -18, -24, -42)
