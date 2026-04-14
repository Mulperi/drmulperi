# DR. MULPERI

Terminal step sequencer built with Python + `curses`.

## Disclaimer

This program was created with help from AI tools.

## Requirements

- Python 3.10+ (tested with 3.13)
- Audio output device working on your system
- `pip`

## Dependency Purpose

- `numpy`: fast array math for audio buffers and mixing.
- `scipy` (`scipy.io.wavfile`): reads `.wav` sample files.
- `sounddevice`: real-time audio output stream (plays the sequencer audio).
- `mido` (optional): MIDI message API used for MIDI OUT mode.
- `python-rtmidi` (optional): backend driver used by `mido` to access system MIDI ports.
- `curses` (Python stdlib): terminal UI drawing and keyboard input.

Optional (helps if `sounddevice` build/install fails):

- macOS: `brew install portaudio`
- MIDI out (optional): `pip install mido python-rtmidi`

## Quick Start

1. Create local virtual environment:

```bash
python3 -m venv .venv
```

2. Activate virtual environment:

- macOS/Linux:

```bash
source .venv/bin/activate
```

- Windows (PowerShell):

```powershell
.venv\Scripts\Activate.ps1
```

3. Install dependencies:

Minimal install (audio sequencer only):

```bash
pip install numpy scipy sounddevice
```

With MIDI OUT support:

```bash
pip install numpy scipy sounddevice mido python-rtmidi
```

4. Run:

```bash
python main.py
```

## Run With Kit/Pattern

```bash
python main.py --kit kit1 --pattern patterns
```

- `--kit`: folder containing `.wav` samples (first 8 alphabetical files are used)
- `--pattern`: pattern bank JSON name/path (`.json` is added automatically if missing)

## Project Data

Pattern bank JSON stores:

- BPM
- 4 patterns (`grid`)
- ratchets (`ratchet_grid`)
- per-track pan (`track_pan`, accent row fixed center)
- per-pattern length (`pattern_length`)
- chain mode + chain sequence (`chain_enabled`, `chain`)

## Core Controls

- `Space`: play/stop
- Arrow keys: move cursor
- `0..9`: set velocity in step cells (`0` clears step, `1..9` sets velocity)
- `Enter`: toggle step on/off (or reset pan to center when cursor is on pan column)
- `P`: preview current track sample
- `M`: mute/unmute current row
- `Q/W/E/R`: select pattern (manual mode) or queue pattern while playing
- `Enter` on `LOAD` column: open sample browser and load one `.wav` into current track

## Modes And Editing

- `mode_toggle` (default `v`): toggle velocity/ratchet mode
- Ratchet mode: `1..4` sets ratchet count for selected step
- Quick ratchet shortcuts: `Shift+1..4` (plus layout fallbacks) and `F1..F4`
- Pan column: one extra column after 16 steps (`P1..P9`)

## Load/Save Dialogs

- `pattern_export` (default `X`): save pattern bank to filename
- `pattern_load` (default `L`): open pattern bank browser overlay (`.json`)
- `kit_load` (default `K`): open kit folder browser overlay
- Browser navigation: `Up/Down` select, `Enter` open/select, `Left/Right` or `Backspace` go up/down folders
- `Esc` cancels any open dialog
- Filename prompts auto-add `.json` if omitted
- Pattern menu includes `Save Pack`: creates a folder with `pattern_bank.json` and current track samples
- Pattern menu includes `Toggle MIDI OUT` (tracks 1-8 send note triggers on channels 1-8)
- Pattern menu includes `Export Pattern Audio`: renders current pattern to a `.wav` file
- When MIDI OUT is enabled, internal sample playback is muted

## Chain

- `chain_toggle` (default `G`): toggle chain mode on/off
- `chain_edit` (default `C`): edit chain sequence (max 16 steps, values `1..4`)
- Example inputs: `1 2 3 2`, `1,2,3,2`, `1232`
- Chain status is shown in header as `CHAIN:...`

## Pattern Length

- Per-pattern length is supported (`1..16`)
- Out-of-range steps are visually dimmed
- Length controls:
  - `pattern_length_dec` (default `a`)
  - `pattern_length_inc` (default `s`)

## Keymap

On first run, `keymap.ini` is created in project root.

You can customize these keys there:

- `help_menu`
- `mode_toggle`
- `clear_pattern`
- `mute_row`
- `tempo_inc`
- `tempo_dec`
- `chain_toggle`
- `chain_edit`
- `pattern_length_dec`
- `pattern_length_inc`
- `pattern_export`
- `pattern_load`
- `kit_load`
- `pattern_1`
- `pattern_2`
- `pattern_3`
- `pattern_4`

`keymap.ini` is loaded once at app start, so restart the app after editing it.
