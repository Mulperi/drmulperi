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

## Audio Sample Rate

`settings.ini` is created automatically on first run:

```ini
[audio]
sample_rate = 48000
duplex = off
```

Set this to your interface rate (for example `48000`) to avoid pitch/timing issues from rate mismatch.
Set `duplex = on` (or `auto`) to enable record-while-playing on duplex-capable devices.

You can also override at startup:

```bash
PYTHONPATH=src python -m drmulperi --samplerate 48000
```

Duplex override:

```bash
PYTHONPATH=src python -m drmulperi --duplex on
```

## Playback And Duplex Notes

Lessons learned during development:

- Normal playback timing is very sensitive to stream churn. Starting/stopping or swapping audio streams while transport is running can cause immediate tempo instability.
- Calling global audio stop functions (`sounddevice` global stop paths) can also interrupt the output stream and leave playback in a laggy state.
- Running extra input callbacks during playback (metering/capture on a separate stream) can add enough callback pressure to make sequencer timing unstable.
- Sample-rate mismatch (`44.1k` app vs `48k` device) can cause pitch drift and timing artifacts. Keep app and device at the same rate.

Why duplex recording is hard:

- Duplex needs one device/driver path that supports synchronized input+output at the exact same sample rate/buffer settings.
- If CoreAudio/driver cannot keep that duplex path stable (or another app changes device settings), live record-while-playing will jitter.
- Python callback overhead is workable for many systems, but low-latency duplex with heavy UI/control updates can still hit timing limits.

Practical guidance:

- For best stability, use one fixed sample rate (recommended `48000`) and avoid changing audio device settings while the app is running.
- Close DAWs (or ensure they do not reconfigure the same device) when testing live duplex recording.
- If duplex is unstable on your setup, use non-duplex fallback recording (playback paused during capture) as the reliable mode.

## Top Bar

Top bar is navigable and contains:

- `FILE`
- `PATTERN`
- `SONG`
- `RECORD`
- `BPM`
- `LEN`
- `SW`
- `PITCH`
- `VELOCITY` / `RATCHET`
- `MIDI OUT`

Menus open anchored from their button (desktop-style dropdowns).

## Main Hotkeys

- `Space`: play/stop
- `F1` / `F2` / `F3`: switch tabs (`Sequencer`, `Audio`, `Mixer`)
- `F`: open/close File menu
- `P`: open/close Pattern menu
- `R`: open/close Record menu
- `Q`: open/close Patterns overlay
- `W` / `E`: previous/next pattern
- `M`: mute sequencer row (Sequencer view)

## Menus

### File

- New project
- Load project
- Save project (overwrite current project JSON)
- Save Project As (project folder: samples + JSON)
- Save kit (kit export options + output folder)
- Load kit
- Export (audio export overlay)

### Pattern

- Patterns overlay
- Import from clipboard
- Clear pattern
- Copy pattern
- Paste pattern

Pattern copy/paste includes:

- step grid
- ratchets
- length
- swing
- per-pattern audio track data for that pattern

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

## settings.ini Reference

`settings.ini` is created automatically on first run. All sections and keys are optional — missing keys fall back to defaults.

```ini
[audio]
sample_rate = 48000   # audio device sample rate (Hz)
duplex = off          # off | on | auto

[sequencer]
default_kit = defaultkit   # kit folder loaded for new projects
follow_song = on            # on | off — song playback advances the viewed pattern

[ui]
color_primary      = cyan     # frame borders, prompt line, top-menu title
color_text         = white    # general text, step cells, muted labels
color_accent     = green    # playhead marker, chain/SONG on, MIDI on
color_accent       = yellow   # hints, accented steps, high-velocity labels
color_divider      = blue     # column/row divider lines
color_record       = red      # recording indicator, hot meter segment
color_meter        = green    # normal meter fill bars
color_selection_fg = white    # text color inside the selected cell / cursor
color_selection_bg = red      # background color of the selected cell / cursor
color_tertiary     = yellow   # footer PATTERNS / SONG toggle labels
text_bold = off               # on | off — force bold attribute on all rendered UI text
text_uppercase = on           # on = UI labels uppercased, off = UI labels lowercased (filenames/paths keep original case)
```

### Available color names

Standard names:
`black`, `red`, `green`, `yellow`, `blue`, `magenta`, `cyan`, `white`

Bright/intense names (prefix form):
`bright_black`, `bright_red`, `bright_green`, `bright_yellow`, `bright_blue`, `bright_magenta`, `bright_cyan`, `bright_white`

You can also use `intense_` as a synonym for `bright_` (for example `intense_cyan`).

Bright/intense values are rendered using terminal bold/high-intensity attributes on top of the base ANSI color. Exact appearance depends on your terminal emulator and color theme.
