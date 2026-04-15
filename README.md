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
PYTHONPATH=src python -m drmulperi
```

Quick start with bundled example kit:

```bash
PYTHONPATH=src python -m drmulperi --kit examplekit --pattern examplekit/patterns.json
```

Compatibility launcher (still works):

```bash
python3 main.py --kit examplekit --pattern examplekit/patterns.json
```

## Run With Kit/Pattern

```bash
PYTHONPATH=src python -m drmulperi --kit kit1 --pattern patterns
```

- `--kit`: folder containing `.wav` samples (first 8 alphabetical files are used)
- `--pattern`: pattern bank JSON name/path (`.json` is added automatically if missing)

## Project Layout

- Source package: `src/drmulperi/`
- Compatibility launcher: `main.py`

## Project Data

Pattern bank JSON stores:

- BPM
- active/visible pattern (`pattern`, `view_pattern`)
- dynamic patterns (`grid`, `pattern_count`)
- ratchets (`ratchet_grid`)
- per-track pan (`track_pan`, accent row fixed center)
- per-track humanize/probability/group (`track_humanize`, `track_probability`, `track_group`)
- per-pattern length (`pattern_length`)
- per-pattern swing (`pattern_swing`) stored as `0..10`
- per-pattern Tracks-view lanes (`audio_track_pan`, `audio_track_volume`, `audio_track_sample_paths`, `audio_track_sample_names`)
- chain mode + chain sequence (`chain_enabled`, `chain`)
- MIDI out state (`midi_out_enabled`)
- global pitch transpose in semitones (`pitch_semitones`)

## Core Controls

- `Space`: play/stop
- Arrow keys: move cursor
- `Up` from top row enters header/tabs focus (`Sequencer`, `Tracks`, `Mixer`)
- `Tab` / `Shift+Tab`: jump next/previous edit column group
- `0..9`: set velocity in step cells (`0` clears step, `1..9` sets velocity)
- `Enter`: toggle step on/off (or reset pan to center when cursor is on pan column)
- `P`: preview current track sample
- `M`: mute/unmute current row
- `Q`: open/close Patterns overlay
- `W` / `E`: previous/next pattern quickly
- `Enter` on `▶` column: preview current track sample
- `Enter` on `↓` column: open sample browser and load one `.wav` into current track
- In Tracks view, `Enter` on `●` opens Record Input overlay (select input device + live dBFS level bar)

## Modes And Editing

- `mode_toggle` (default `T`): toggle velocity/ratchet mode
- Ratchet mode: `1..4` sets ratchet count for selected step
- Quick ratchet shortcuts: `Shift+1..4` (plus layout fallbacks) and `F1..F4`
- Right-side parameter columns after 16 steps: preview (`▶`), sample load (`↓`), pan (`P1..P9`), humanize (`H0..H100`), probability (`%0..%100`), mute group (`0..9`), track pitch (`0..24`)
- Humanize and probability can be edited directly by typing digits in their cells (no Enter required)
- Track pitch column uses `0..24` where `12` is no shift (`-12..+12` semitone mapping)

## Views

- `Sequencer`: step grid + drum sequencing workflow
- `Tracks`: 8 per-pattern audio lanes with columns `Preview`, `Load`, `Pan`, `Volume`, `Record`; sample name shown in row area
- `Mixer`: placeholder tab (UI shell only for now)

## Patterns Overlay

- Open with `Q` (or header `PATTERNS` button + Enter)
- `Enter`: select/queue highlighted pattern
- `Space`: play/stop transport (starts from selected pattern if stopped)
- `A`: add new empty pattern
- `D`: duplicate current view pattern into a new one
- `X`: delete selected pattern (double-press confirm required)
- Rows show `EMPTY`, `LEN`, `SW`, and `HITS` summary

## Import Chops From Dropped WAV

- Drag a `.wav` file path into terminal (or paste an absolute path starting with `/` or `~`)
- App opens `IMPORT CHOPS` overlay with 8 candidate slices
- In `IMPORT CHOPS` overlay:
  - `Up/Down`: move selection
  - `Space`: preview selected chop
  - `Enter` on `[ Use Samples ]`: replace current kit with chopped samples
  - `Enter` on `[ Cancel ]` or `Esc`: cancel
- Accepted chops are saved into `generated_kits/<name>_chop_<timestamp>/` and loaded as active kit

## Load/Save Dialogs

- `pattern_export` (default `X`): save pattern bank to filename
- `pattern_load` (default `L`): open pattern bank browser overlay (`.json`)
- `kit_load` (default `K`): open kit folder browser overlay
- Browser navigation: `Up/Down` select, `Enter` open/select, `Left/Right` or `Backspace` go up/down folders
- Sample browser: `Space` previews highlighted `.wav`
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
  - `pattern_length_dec` (default `[`)
  - `pattern_length_inc` (default `]`)

## Header Focus

- From grid top row, press `Up` to enter header focus.
- In header focus, `Tab` / `Shift+Tab` cycles parameters: `PATTERN BANK`, `KIT`, `BPM`, `LEN`, `SW`, `PITCH`.
- `Enter` on `PATTERN BANK`/`KIT` opens their browser dialogs.
- `Left/Right` adjusts numeric header params (`BPM`, `LEN`, `SW`, `PITCH`).
- `Down` returns from header focus to the grid.

## Keymap

On first run, `keymap.ini` is created in project root.

You can customize these keys there:

- `help_menu`
- `pattern_menu`
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
