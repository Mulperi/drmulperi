# DR. MULPERI

AI-assisted terminal groovebox / step sequencer built with Python + `curses`.

## Disclaimer

This program was created with help from AI tools.

## Requirements

- Python 3.10+ (tested with 3.13)
- Working audio output device
- `pip`

Optional:

- `mido` + `python-rtmidi` for MIDI OUT
- `portaudio` system library (if `sounddevice` install needs it)

## Dependencies

- `numpy`: audio buffer math and signal handling
- `scipy` (`scipy.io.wavfile`): WAV read/write
- `sounddevice`: real-time audio I/O
- `mido` (optional): MIDI API
- `python-rtmidi` (optional): MIDI backend for `mido`
- `curses` (stdlib): terminal UI rendering and keyboard input

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install numpy scipy sounddevice
# optional MIDI support:
# pip install mido python-rtmidi
```

## Run

```bash
PYTHONPATH=src python -m drmulperi --pattern patterns
```

Example project:

```bash
PYTHONPATH=src python -m drmulperi --pattern examplekit/patterns.json
```

Compatibility launcher:

```bash
python3 main.py --pattern examplekit/patterns.json
```

## Top Bar

Top bar is navigable and contains:

- `FILE`
- `PATTERN`
- `SEQUENCER`
- `SONG`
- `RECORD`
- `BPM`
- `LEN`
- `SW`
- `PITCH`
- `VELOCITY` / `RATCHET`
- `MIDI OUT`
- `HELP`

Menus open anchored from their button (desktop-style dropdowns).

## Main Hotkeys

- `Space`: play/stop
- `F1` / `F2` / `F3`: switch tabs (`Sequencer`, `Audio`, `Mixer`)
- `F`: open/close File menu
- `P`: open/close Pattern menu
- `S`: open/close Sequencer menu
- `R`: open/close Record menu
- `Q`: open/close Patterns overlay
- `W` / `E`: previous/next pattern
- `M`: mute sequencer row (Sequencer view)
- `H`: help overlay

## Menus

### File

- New project
- Load project
- Save project (pack folder: samples + JSON)
- Export (audio export overlay)

### Pattern

- Patterns overlay
- Clear pattern
- Copy pattern
- Paste pattern

Pattern copy/paste includes:

- step grid
- ratchets
- length
- swing
- per-pattern audio track data for that pattern

### Sequencer

- Save kit (kit export options + output folder)
- Load kit

## Views

### Sequencer

Classic 16-step sequencer with per-track parameters.

### Audio

Audio tracks with mode toggle (`Pattern` / `Song`) and columns for preview/load/pan/volume/record/clear/rename.

Ownership transfer behavior when toggling mode:

- Pattern -> Song: moves current viewed pattern's audio into song ownership
- Song -> Pattern: moves song audio into current viewed pattern ownership

### Mixer

Horizontal mixer page:

- left section: Sequencer tracks (`Pan`, `Vol`)
- right section: Audio tracks (`Pan`, `Vol`)

Edit by typing numeric values directly.

## Recording

Record overlay (top `RECORD` or `R`) uses selection-style rows:

- Channels (`Mono` / `Stereo`)
- Input Device
- Input Source (e.g. `In 1`, `In 2`, `In 1/2`, ...)
- Precount pattern
- Action row (`Cancel` / `Record` or `Stop`)

Behavior:

- Recording starts without closing overlay
- Top bar `RECORD` label changes to `STOP` while capture is active
- Borders turn red during active recording
- After recording finishes, Import Audio overlay opens automatically for routing
- If target track is `Song` mode, recording captures one full song-chain pass

## Import Overlay

Import options for any recorded/dropped WAV:

- Chop audio to 8 drum tracks
- Import to single drum track
- Import to audio track

Audio-track import row shows context:

- `(Song)` for song-owned track
- `(Pattern N)` for pattern-owned track

## Project Data

Project JSON stores (high level):

- sequencer grid / ratchets / BPM / swing / length
- current and view pattern indexes
- chain data + song mode
- global pitch and MIDI state
- sequencer per-track params (`track_pan`, `track_volume`, etc.)
- embedded sequencer sample paths (`seq_samples`) resolved relative to project JSON
- audio track data under `audio_tracks`

Save project writes `<project_folder_name>_data.json` inside the saved folder.

## Keymap

`keymap.ini` is loaded once at startup.

You can customize bindings there (restart app after editing).
