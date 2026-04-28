"""
consts.py — Shared colour key constants used across Launchpad95 components.

Currently defines a single dictionary that maps the three button-state names
(color, pressed_color, disabled_color) to their skin key strings.  Components
that need a generic "action button" appearance import this dict and pass it as
keyword arguments to set_on_off_values() or similar helpers.
"""

# ACTION_BUTTON_COLORS: default colour mapping for generic action buttons.
# Keys correspond to the standard skin lookup names defined in SkinMK1 / SkinMK2:
#   'color'          -> the resting / "off" LED colour
#   'pressed_color'  -> the LED colour when the button is held / active
#   'disabled_color' -> the LED colour when the button is not available
ACTION_BUTTON_COLORS = dict(
    color='DefaultButton.Off',
    pressed_color='DefaultButton.On',
    disabled_color='DefaultButton.Disabled'
)
