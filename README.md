# DR. MULPERI

Terminal step sequencer built with Python + `curses`.

## Requirements

- Python 3.10+ (tested with 3.13)
- Audio output device working on your system
- `pip`

Optional (helps if `sounddevice` build/install fails):

- macOS: `brew install portaudio`

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

```bash
pip install numpy scipy sounddevice
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
- `--pattern`: pattern JSON name/path (`.json` is added automatically if missing)

## Keymap

On first run, `keymap.ini` is created in project root.

You can customize these keys there:

- `mode_toggle`
- `clear_pattern`
- `mute_row`
- `pattern_1`
- `pattern_2`
- `pattern_3`
- `pattern_4`

Restart the app after editing `keymap.ini`.
