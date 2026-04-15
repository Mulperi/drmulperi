import argparse
import configparser
import curses
import os

from .config import DEFAULT_KIT_PATH, DEFAULT_PATTERN_NAME, DEFAULT_SETTINGS, SETTINGS_PATH
from .sequencer import Sequencer
from .ui import ui_loop


def _load_settings_sample_rate(path=SETTINGS_PATH):
    """Load sample rate from settings.ini, creating defaults when needed."""
    parser = configparser.ConfigParser()
    if not os.path.exists(path):
        parser["audio"] = DEFAULT_SETTINGS
        with open(path, "w") as f:
            parser.write(f)
    parser.read(path)
    section = parser["audio"] if "audio" in parser else {}
    raw = section.get("sample_rate", DEFAULT_SETTINGS["sample_rate"])
    try:
        val = int(str(raw).strip())
        if val > 0:
            return val
    except Exception:
        pass
    return int(DEFAULT_SETTINGS["sample_rate"])


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--kit",
        default=DEFAULT_KIT_PATH,
        help="Sample kit directory (optional; if omitted, project JSON/sample loads define kit content)",
    )
    parser.add_argument(
        "--pattern",
        default=DEFAULT_PATTERN_NAME,
        help="Pattern JSON file name/path without or with .json (default: patterns)",
    )
    parser.add_argument(
        "--samplerate",
        type=int,
        default=None,
        help="Audio sample rate override in Hz (e.g. 44100 or 48000). Overrides settings.ini",
    )
    args = parser.parse_args()

    pattern_path = args.pattern
    if not pattern_path.lower().endswith(".json"):
        pattern_path = f"{pattern_path}.json"

    sample_rate = args.samplerate if isinstance(args.samplerate, int) and args.samplerate > 0 else _load_settings_sample_rate()
    seq = Sequencer(kit_path=args.kit, pattern_path=pattern_path, samplerate=sample_rate)
    curses.wrapper(ui_loop, seq)


if __name__ == "__main__":
    main()
