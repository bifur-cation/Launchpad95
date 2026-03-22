"""
Launchpad95 — Ableton Live Remote Script entry point.

This module is the package initializer for the Launchpad95 Remote Script.
Ableton Live discovers this script through `create_instance` and `get_capabilities`.

Supported hardware (via vendor_id 4661 / Novation):
  - Launchpad (original MK1)
  - Launchpad Mini
  - Launchpad S
  - Launchpad MK2  (product IDs 105-120)
  - Launchpad Mini MK3  (product ID 275)
  - Launchpad X  (product ID 259)
"""

from _Framework.Capabilities import (
    CONTROLLER_ID_KEY, PORTS_KEY,
    NOTES_CC, SCRIPT, SYNC, REMOTE,
    controller_id, inport, outport
)
from .Launchpad import Launchpad


def create_instance(c_instance):
    """
    Factory function called by Ableton Live to instantiate the control surface.

    Args:
        c_instance: The Live control surface instance handle provided by the host.

    Returns:
        Launchpad: A fully initialized Launchpad control surface object.
    """
    return Launchpad(c_instance)


def get_capabilities():
    """
    Return a capabilities dictionary that Ableton Live uses to match this script
    to connected MIDI hardware.

    The dictionary describes:
      - CONTROLLER_ID_KEY: vendor/product IDs and human-readable model names.
      - PORTS_KEY: required MIDI input and output port configurations.

    Returns:
        dict: Capability descriptor understood by the _Framework.Capabilities API.
    """
    return {
        CONTROLLER_ID_KEY: controller_id(
            vendor_id=4661,          # Novation USB vendor ID
            product_ids=[
                14,   # Launchpad (original)
                54,   # Launchpad Mini
                105,  # Launchpad S / MK2 variants
                106, 107, 108, 109, 110, 111, 112, 113,
                114, 115, 116, 117, 118, 119, 120,
                275,  # Launchpad Mini MK3
                259,  # Launchpad X
            ],
            model_name=[
                'Launchpad',
                'Launchpad Mini',
                'Launchpad S',
                'Launchpad MK2',
                'Launchpad MK2 2',
                'Launchpad MK2 3',
                'Launchpad MK2 4',
                'Launchpad MK2 5',
                'Launchpad MK2 6',
                'Launchpad MK2 7',
                'Launchpad MK2 8',
                'Launchpad MK2 9',
                'Launchpad MK2 10',
                'Launchpad MK2 11',
                'Launchpad MK2 12',
                'Launchpad MK2 13',
                'Launchpad MK2 14',
                'Launchpad MK2 15',
                'Launchpad MK2 16',
                'Launchpad Mini MK3',
                'Launchpad X',
            ]
        ),
        PORTS_KEY: [
            # Input port: receives notes/CC from the hardware (used for remote control)
            inport(props=[NOTES_CC, REMOTE]),
            # Input port: also forwards messages to the script for internal processing
            inport(props=[NOTES_CC, REMOTE, SCRIPT]),
            # Output port: sends sync + note/CC feedback to the hardware
            outport(props=[NOTES_CC, SYNC, REMOTE]),
            # Output port: primary script output including LED commands
            outport(props=[NOTES_CC, SYNC, REMOTE, SCRIPT]),
        ]
    }
