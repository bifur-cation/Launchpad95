# Launchpad95

A feature-rich Ableton Live Remote Script for the **Novation Launchpad** family of controllers, building on the classic Launchpad 95 script with significant enhancements including RGB clip colours, a device controller, step sequencers, an instrument/scale mode, Pro Session recording, and a Max for Live On-Screen Display (OSD) bridge.

---

## Supported Hardware

| Hardware | Detection | RGB Colour |
|---|---|---|
| Launchpad MK1 / Mini / S | Challenge/response (CC) | No (2-bit amber/green/red) |
| Launchpad MK2 | SysEx challenge/response | Yes (128-colour palette) |
| Launchpad Mini MK3 | Universal Device Inquiry | Yes (128-colour + blink/pulse) |
| Launchpad X | Universal Device Inquiry | Yes (128-colour + blink/pulse) |

Hardware is detected automatically at startup via a SysEx challenge/response sequence. No manual configuration is needed.

---

## Installation

The repository follows a `src/`-layout Python package.  The folder Ableton needs is **`src/Launchpad95/`** — *not* the top-level repository folder.

### As an Ableton Remote Script

1. Locate your Ableton Live Remote Scripts folder:
   - **Windows**: `C:\ProgramData\Ableton\Live <version>\Resources\MIDI Remote Scripts\`
   - **macOS**: `/Applications/Ableton Live <version>.app/Contents/App-Resources/MIDI Remote Scripts/`
2. Copy the inner `src/Launchpad95/` folder (the one containing `__init__.py`, `Launchpad.py`, etc.) into that directory.  After copying, the path on disk should be `…/MIDI Remote Scripts/Launchpad95/__init__.py`.
3. Restart Ableton Live.
4. Open **Preferences → Link / MIDI** and set your Launchpad input and output ports to use **Launchpad95** as the Control Surface.

> Do **not** copy the repository root (the folder that contains `pyproject.toml`, `src/`, `README.md`, …).  Live discovers Remote Scripts by folder name, so the directory inside `MIDI Remote Scripts` must literally be named `Launchpad95` and contain `__init__.py` at its top level.

### As a pip-installable Python package

The repository is also a standard PEP 621 Python package.  Installing it with pip exposes the standalone `LaunchpadWrapper` (see [Standalone Python Wrapper](#standalone-python-wrapper) below) without needing Ableton Live.

```bash
# From a clone of the repo
pip install .

# Or in editable / development mode
pip install -e .

# Or directly from a local path
pip install /path/to/Launchpad95
```

This installs the `Launchpad95` package and the `launchpad95-demo` console script, and pulls in `mido` + `python-rtmidi` for raw MIDI I/O.  The Ableton Remote Script side of the package is gracefully skipped when `_Framework` is unavailable (i.e. outside of Live).

### Repository layout

```
Launchpad95/
├── pyproject.toml            ← packaging metadata (PEP 621)
├── README.md
├── LICENSE
├── M4LDevice/                ← Max for Live OSD device (.amxd)
├── web/                      ← documentation assets, screenshots
└── src/
    └── Launchpad95/          ← the importable Python package
        ├── __init__.py       ← `create_instance` / `get_capabilities` for Live
        ├── Launchpad.py
        ├── LaunchpadWrapper.py
        ├── …all components, skins, colour palettes…
        └── custom_temperament.json
```

---

## Configuration

All user-configurable options are in `Settings.py`.  Edit the class attributes to customise behaviour before installing.

### Key Settings

| Setting | Type | Default | Description |
|---|---|---|---|
| `USER_MODES_1` | `list[str]` | `["instrument", "device", "user 1"]` | Sub-modes cycled by the User1 button |
| `USER_MODES_2` | `list[str]` | `["drum stepseq", "melodic stepseq", "user 2"]` | Sub-modes cycled by the User2 button |
| `SESSION__LINK` | `bool` | `False` | Link session view across multiple Launchpads |
| `STEPSEQ__LINK_WITH_SESSION` | `bool` | `False` | Link step sequencer offset with session view |
| `DEVICE_CONTROLLER__STEPLESS_MODE` | `bool` | `False` | Start device controller in stepless fader mode |
| `ENABLE_TDC` | `bool` | `True` | Enable Time-Dependent Control for device faders |
| `TDC_MAX_TIME` | `float` | `2.0` | Maximum hold-time (seconds) for TDC velocity mapping |
| `TDC_MAP` | `list[float]` | `[0.0, …, 1.0]` | Velocity curve mapped to hold time |
| `USE_CUSTOM_DEVICE_CONTROL_COLORS` | `bool` | `True` | Use per-column custom slider colours (MK2/MK3/LPX) |
| `VELOCITY_THRESHOLD_MIN` | `int` | `10` | Minimum velocity for stepless animation |
| `VELOCITY_THRESHOLD_MAX` | `int` | `100` | Velocity above which change is applied immediately |
| `VELOCITY_FACTOR` | `float` | `500.0` | Denominator scaling fader animation speed |

---

## Modes Overview

The four top-right buttons select the primary mode.  Pressing the same button again cycles through sub-modes.

### Session Mode (top button 4)

Standard Ableton clip-launch grid.  The 8×8 matrix shows clips; side buttons launch scenes; nav buttons scroll the session view.

**Zoom mode**: Hold the Session button while pressing a matrix button to jump to that region.

**Pro Session mode**: Short-press the Session button while already in Session mode to toggle Pro Session mode.  In Pro Session mode:
- The bottom row of the matrix becomes stop-clip buttons.
- Side buttons remain as scene launch buttons.
- Action buttons (shift, undo, delete, duplicate, double, quantize, click, session record) appear.

### User1 Mode (top button 5)

Cycles between the modes listed in `Settings.USER_MODES_1`:

#### Instrument Mode
The 8×8 matrix becomes a playable note grid, coloured by scale membership:
- **Blue (MK2) / Amber (MK1)**: Root note
- **Light blue (MK2) / Green (MK1)**: Notes in scale
- **Dark grey (MK2) / Off (MK1)**: Notes outside scale

Side buttons:
| Button | Function |
|---|---|
| 0 | Toggle scale editor |
| 1 | Undo |
| 2 | Octave up |
| 3 | Octave down |
| 4 | Fire/stop selected clip |
| 5 | Lock to track |
| 6 | Solo track |
| 7 | Session record / arm |

Nav buttons scroll track/scene selection.

**Scale Editor**: Press side button 0 to enter the scale editor.  The matrix shows:
- Row 0: Layout mode (absolute root, horizontal, chromatic guitar, diatonic NS, diatonic chords, diatonic, chromatic, drumrack)
- Row 1: Black keys + circle of fifths ← + relative scale + quick-scale toggle
- Row 2: White keys + circle of fifths →
- Row 3: Octave selector
- Rows 4-7: Scale mode selector (up to 32 scale modes)

#### Device Controller Mode
Each of the 8 matrix columns controls one parameter of the selected device.  The display mode adapts automatically:

| Parameter type | Display |
|---|---|
| Boolean (range=1) | Single toggle button at top |
| Small enum (range ≤ 8) | One lit button per option |
| Large enum (range > 8) | Decrement/increment buttons |
| Continuous | Filled bar graph |
| Continuous + precision | Nudge up/down buttons |

Side buttons:
| Button | Function |
|---|---|
| 0 | Device on/off |
| 1 | Previous parameter bank |
| 2 | Next parameter bank |
| 3 | Mode toggle (short = precision, long = stepless) |
| 4-7 | Device lock slots 1-4 |

Nav buttons navigate tracks and devices.

**Lock system**: Long-press a lock button (4-7) to store the current device in that slot.  Short-press to recall/release it.  The OSD shows `(locked)` when a device is locked.

**Stepless faders**: Long-press the mode toggle button to enable smooth animated parameter changes.  Hold a pad longer to move the parameter more slowly (TDC).

#### User 1 Raw MIDI
The matrix and side buttons pass MIDI note-on/off messages directly through on channel 4 with drum-rack layout mapping enabled.

---

### User2 Mode (top button 6)

Cycles between the modes listed in `Settings.USER_MODES_2`:

#### Drum Step Sequencer
An 8-step (expandable via loop selector) drum/note step sequencer.  The matrix shows steps for the selected pitch:
- **Velocity-graded colours**: Dim = low velocity, bright = high velocity
- **Playhead**: Current playing step highlighted
- **Metronome markers**: Beat/bar boundaries indicated

Side buttons navigate note pitch.  Nav buttons control loop block selection and quantization.

Press and hold a step to adjust its velocity with the adjacent buttons.

Supports normal (single note) and multi-note modes.

#### Melodic Step Sequencer
Extends the drum sequencer with per-step pitch, octave, velocity, and length editing.  Press the mode button to cycle between pitch/octave/velocity/length views.

#### User 2 Raw MIDI
All buttons pass MIDI through on channel 5.

---

### Mixer Mode (top button 7)

Provides 8 vertical channel strips.  The side buttons cycle through mixer sub-modes:

| Sub-mode | Side LED | Function |
|---|---|---|
| Volume | Green | Volume bar sliders |
| Pan | Amber (MK1) / Mint (MK2) | Pan bar sliders |
| Send A | Green | Send A sliders |
| Send B | Green | Send B sliders |
| Stop | Red | Stop clip per track |
| Mute | Amber | Mute toggle per track |
| Solo | Red | Solo toggle per track |
| Arm | Red | Record arm per track |

Global action buttons (top row):
- **Unarm all**: Disarm every armed track
- **Unsolo all**: Clear solo on all tracks
- **Unmute all**: Unmute all tracks

Default-value buttons: Each strip has a reset button that returns the parameter to its default value.  The button is lit when the parameter is already at default.

---

## Standalone Python Wrapper

`LaunchpadWrapper` is a self-contained Python class that talks to any Launchpad MK1, Mini, S, MK2, Mini MK3, or X over MIDI **without Ableton Live**.  Use it for custom controllers, lighting demos, MIDI-driven visualisations, scale-aware controller layouts, prototyping, or any project that just wants to drive the LEDs and read the pads.

It provides hardware auto-detection, a unified API across all four hardware generations (with the right SysEx/CC/note quirks abstracted), high-level helpers for scale grids and bar-graph mixers, and a callback-based event loop.

### Requirements

- Python 3.7+
- `mido` and `python-rtmidi` (installed automatically by `pip install Launchpad95`)
- A connected Launchpad — the wrapper auto-detects via MIDI port name.

### Quick start

```python
from Launchpad95 import LaunchpadWrapper
from Launchpad95.LaunchpadWrapper import Mk2Color, ScaleGrid

lp = LaunchpadWrapper.connect()       # auto-detects connected Launchpad
print(f"Connected: {lp.model}")        # 'mk1', 'mk2', 'mk3', or 'lpx'

lp.set_led(0, 0, Mk2Color.RED)         # top-left pad → red
lp.blink(0, 1, Mk2Color.GREEN)         # blink (MK2/MK3/LPX only)
lp.pulse(0, 2, Mk2Color.BLUE)          # pulse / breathe

lp.on_button_press(lambda r, c: print(f"Pressed ({r},{c})"))
lp.run()                                # blocking MIDI loop; Ctrl+C to stop
lp.disconnect()
```

### Run the bundled demo

After `pip install`, the package exposes a console script that runs an interactive scale-editor + instrument demo on real hardware:

```bash
launchpad95-demo
```

Equivalent to:

```bash
python -m Launchpad95.LaunchpadWrapper
```

The demo opens with the Launchpad95 scale editor on the 8×8 grid; pick a root, mode, and octave with the pads, then press the top-right automap button to switch into instrument mode.  The console prints the MIDI note (and frequency, via the active temperament) for each pad you press.

### API reference

#### Connection and lifecycle

| Method | Purpose |
|---|---|
| `LaunchpadWrapper.connect(model=None, input_port=None, output_port=None)` | Auto-detect hardware by scanning MIDI port names; returns a ready instance.  Pass an explicit `model` (`HardwareModel.MK1` / `MK2` / `MK3` / `LPX`) and port names to override detection. |
| `lp.run(blocking=True)` | Start the MIDI listen loop.  `blocking=False` runs it in a background thread so the calling code can keep working. |
| `lp.disconnect()` | Exit programmer mode, clear all LEDs, and close the MIDI ports. |

#### LED control

| Method | Purpose |
|---|---|
| `set_led(row, col, color)` | Set a single pad to a static colour.  `row=-1` addresses the top row of round buttons; `col=8` addresses the right-side column. |
| `blink(row, col, color)` | Blinking pad (MK2 / MK3 / LPX). |
| `pulse(row, col, color)` | Pulsing/breathing pad (MK2 / MK3 / LPX). |
| `set_row(row, colors)` | Set a whole row from an 8- or 9-element colour list. |
| `set_grid(colors)` | Set the entire 8×8 grid from a 2-D list. |
| `clear()` | Turn off every LED. |

Colour values come from `Mk1Color` (2-bit, used on MK1/Mini/S) or `Mk2Color` (8-bit palette index, used on MK2/MK3/LPX).  The wrapper does **not** translate between the two — pick the palette that matches `lp.model`.

#### Higher-level drawing

| Method | Purpose |
|---|---|
| `color_scale_grid(grid, root_color=…, in_scale_color=…, off_color=…)` | Render a `ScaleGrid` onto the 8×8 matrix, lighting root notes / scale tones / out-of-scale pads in distinct colours. |
| `draw_bar(col, value, min_val=0.0, max_val=1.0, color_on=…, color_off=…)` | Vertical bar graph in one column.  The bar fills from the bottom row upward. |
| `draw_mixer(values, min_val=0.0, max_val=1.0, color_on=…, color_off=…)` | 8-column mixer view; pass a length-8 list of values in `[min_val, max_val]`. |

#### Input callbacks

| Method | Purpose |
|---|---|
| `on_button_press(cb)` / `on_button_release(cb)` | Register a callback invoked for *any* pad/button press or release.  Signature: `cb(row, col)`. |
| `on_pad_press(row, col, cb)` / `on_pad_release(row, col, cb)` | Register a callback for one specific pad/button. |
| `clear_callbacks()` | Remove all registered callbacks. |

#### Scale-aware layouts

```python
from Launchpad95.LaunchpadWrapper import ScaleGrid, Mk2Color

grid = ScaleGrid(scale_name="Major", root=0, octave=4)   # C major @ middle C
lp.color_scale_grid(grid,
                    root_color=Mk2Color.BLUE,
                    in_scale_color=Mk2Color.LIGHT_BLUE,
                    off_color=Mk2Color.OFF)

# What MIDI note does a pad map to?
info = grid.note_at(row=3, col=5)
print(info.note, info.in_scale, info.is_root)
```

`ScaleGrid` ports the diatonic horizontal layout used by `InstrumentControllerComponent` inside Live.  Built-in scales include Major, Minor, Dorian, Phrygian, Lydian, Mixolydian, Locrian, Pentatonics, Blues, Whole Tone, Harmonic/Melodic Minor, and Chromatic — full list in `Launchpad95.LaunchpadWrapper.BUILTIN_SCALES`.

#### Mixer / bar-graph display

```python
import math, time

while True:
    t = time.time()
    values = [0.5 + 0.5 * math.sin(t + i * 0.5) for i in range(8)]
    lp.draw_mixer(values, color_on=Mk2Color.AMBER)
    time.sleep(1 / 30)
```

Combine with `lp.run(blocking=False)` to drive animated displays while still receiving pad-press callbacks.

#### Embedded scale editor

The full Launchpad95 scale editor (key, mode, octave, layout, circle of fifths) is also available as a reusable component:

```python
from Launchpad95.LaunchpadWrapper import LaunchpadWrapper, ScaleEditorMode

lp = LaunchpadWrapper.connect()
editor = ScaleEditorMode(key=0, octave=3, modus=0)
lp.run_scale_editor(editor)            # blocking; pads drive the editor UI
print(editor.scale_name, editor.key_name, editor.octave)
grid = editor.get_scale_grid()         # current scale → ScaleGrid
```

See the `_run_demo()` source in `LaunchpadWrapper.py` for a complete two-phase example that combines the scale editor with an instrument-mode play surface.

---

## Multi-Launchpad Setup

To use two or more Launchpads side-by-side:

1. Set `Settings.SESSION__LINK = True` in each Launchpad95 instance's `Settings.py`.
2. Install a separate copy of the script for each Launchpad.
3. The script automatically detects other active instances and assigns contiguous track offsets.

---

## Max for Live OSD

Launchpad95 exposes a `M4LInterface` data bus that a companion Max for Live device can subscribe to via `updateML` notifications.  The OSD publishes:

| Property | Content |
|---|---|
| `mode` | Current mode name (e.g. `"Session"`, `"Mixer"`, `"Device Controller"`) |
| `attribute_names[0-7]` | Parameter/track names (8 slots) |
| `attributes[0-7]` | Parameter/track values (8 slots) |
| `info[0]` | Primary info line (e.g. track name) |
| `info[1]` | Secondary info line (e.g. device name) |

---

## Architecture

```
Launchpad (ControlSurface)
├── init() — two-stage: stage 1 sends challenge, stage 2 builds UI after response
├── MainSelectorComponent — top-level mode router
│   ├── SpecialProSessionComponent — Session / Pro Session
│   │   ├── SpecialSessionComponent — MK2 RGB clips + OSD
│   │   ├── SpecialProSessionRecordingComponent — fixed-length record
│   │   └── TargetTrackComponent — auto-select record target track
│   ├── SubSelectorComponent — Mixer sub-modes
│   │   └── SpecialMixerComponent — unarm/unsolo/unmute + OSD
│   │       └── DefChannelStripComponent — default-value reset buttons
│   ├── InstrumentControllerComponent — scale-based note grid
│   │   ├── ScaleComponent — scale/key/octave editor
│   │   └── TrackControllerComponent — arm/mute/solo/nav
│   ├── DeviceControllerComponent — device parameter sliders
│   │   └── DeviceControllerStripProxy (×8) — per-column proxy
│   │       └── DeviceControllerStripServer — background animation thread
│   ├── StepSequencerComponent — drum step sequencer
│   │   ├── NoteEditorComponent — step grid display
│   │   ├── NoteSelectorComponent — pitch selector
│   │   └── LoopSelectorComponent — loop region
│   └── StepSequencerComponent2 — melodic step sequencer
│       └── MelodicNoteEditorComponent — pitch/velocity/length editor
├── NoteRepeatComponent — note repeat with rate selection
└── M4LInterface — OSD data bus
```

### Key Design Patterns

**Two-stage initialisation**: `Launchpad.__init__` sets minimal state and sends challenge bytes to all hardware generations simultaneously.  `handle_sysex()` identifies the connected model from the response and calls `init()` to complete setup.  This pattern is required because hardware identity is determined asynchronously.

**Skin system**: All LED colours are resolved via a `_Framework.Skin` instance at runtime using string keys like `"Session.ClipStarted"`.  Two skins are provided: `SkinMK1` (2-bit palette) and `SkinMK2` (128-colour RGB + blink/pulse).

**Proxy/server threading**: `DeviceControllerStripProxy` forwards method calls from the main Ableton thread to `DeviceControllerStripServer` via `queue.Queue`, enabling smooth 50ms parameter animation without blocking the Live audio engine.

**Mode routing**: `MainSelectorComponent` manages a `_modes_heap` (from `ModeSelectorComponent`) and maps the active mode to sub-components.  All `ConfigurableButtonElement` instances share the same physical MIDI note but are re-assigned a different MIDI channel per mode, allowing the MIDI map to route them correctly without rebinding buttons.

---

## File Reference

| File | Description |
|---|---|
| `__init__.py` | Entry point; `create_instance()` and `get_capabilities()` |
| `Launchpad.py` | Main `ControlSurface` subclass |
| `Settings.py` | All user-configurable options |
| `MainSelectorComponent.py` | Top-level mode router |
| `SpecialSessionComponent.py` | Session with MK2 RGB + OSD |
| `SpecialProSessionComponent.py` | Pro Session with recording/quantization |
| `SpecialProSessionRecordingComponent.py` | Fixed-length session recording |
| `SpecialMixerComponent.py` | Mixer with global actions + OSD |
| `SubSelectorComponent.py` | Mixer sub-mode selector |
| `DefChannelStripComponent.py` | Channel strip with default-value reset |
| `DeviceControllerComponent.py` | Device parameter controller |
| `DeviceControllerStrip.py` | Single-column device strip (reference) |
| `DeviceControllerStripProxy.py` | Thread-safe proxy for strip server |
| `DeviceControllerStripServer.py` | Background animation server |
| `InstrumentControllerComponent.py` | Scale-based instrument mode |
| `ScaleComponent.py` | Scale/key/octave management + `MelodicPattern` |
| `TrackControllerComponent.py` | Single-track arm/solo/mute/nav |
| `TargetTrackComponent.py` | Auto-select record target track |
| `NoteRepeatComponent.py` | Note repeat with rate selection |
| `StepSequencerComponent.py` | Drum step sequencer |
| `StepSequencerComponent2.py` | Melodic step sequencer |
| `NoteEditorComponent.py` | Step grid display/editing |
| `NoteSelectorComponent.py` | Pitch/drum-pad selector |
| `LoopSelectorComponent.py` | Loop region selector |
| `ClipSlotMK2.py` | MK2 clip slot with blink/pulse feedback |
| `ConfigurableButtonElement.py` | Skin-aware button element |
| `ButtonSliderElement.py` | Virtual slider from button column |
| `PreciseButtonSliderElement.py` | Enhanced slider with volume/pan modes |
| `M4LInterface.py` | Max for Live OSD data bus |
| `SkinMK1.py` | Complete colour skin for MK1/Mini/S |
| `SkinMK2.py` | Complete colour skin for MK2/MK3/LPX |
| `ColorsMK1.py` | MK1 2-bit `Rgb` colour palette |
| `ColorsMK2.py` | MK2 128-colour `Rgb`/`Blink`/`Pulse` palette |
| `consts.py` | `ACTION_BUTTON_COLORS` mapping |
| `Log.py` | Optional file-based debug logger |

---

## Credits

Based on the original Launchpad 95 script with contributions from the Launchpad community.  Pro Session mode components imported from [poltow/Launchpad97](https://github.com/poltow/Launchpad97).
