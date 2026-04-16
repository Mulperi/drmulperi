import argparse
import configparser
import curses
import os

from .config import DEFAULT_KIT_PATH, DEFAULT_SETTINGS, SETTINGS_PATH
from .sequencer import Sequencer
from .ui import ui_loop


def _load_audio_settings(path=SETTINGS_PATH):
    """Load audio settings from settings.ini, creating defaults when needed."""
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
        sample_rate = val if val > 0 else int(DEFAULT_SETTINGS["sample_rate"])
    except Exception:
        sample_rate = int(DEFAULT_SETTINGS["sample_rate"])

    duplex_raw = str(section.get("duplex", DEFAULT_SETTINGS.get("duplex", "off"))).strip().lower()
    if duplex_raw not in {"off", "on", "auto"}:
        duplex_raw = "off"
    return sample_rate, duplex_raw


def main(path=SETTINGS_PATH):
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    config_parser = configparser.ConfigParser()
    config_parser.read(path)
    section = config_parser["sequencer"] if "sequencer" in config_parser else {}
    parser.add_argument(
        "--kit",
        default=DEFAULT_KIT_PATH,
        help="Sample kit directory (optional; if omitted, project JSON/sample loads define kit content)",
    )
    parser.add_argument(
        "--pattern",
        default=None,
        help="Project JSON file name/path without or with .json (default: empty new project)",
    )
    parser.add_argument(
        "--samplerate",
        type=int,
        default=None,
        help="Audio sample rate override in Hz (e.g. 44100 or 48000). Overrides settings.ini",
    )
    parser.add_argument(
        "--duplex",
        choices=["off", "on", "auto"],
        default=None,
        help="Duplex audio mode: off=output only, on=require duplex, auto=try duplex then fallback",
    )
    args = parser.parse_args()

    pattern_arg = (args.pattern or "").strip()
    pattern_path = pattern_arg if pattern_arg else "new_project.json"
    if not pattern_path.lower().endswith(".json"):
        pattern_path = f"{pattern_path}.json"

    settings_sr, settings_duplex = _load_audio_settings()
    sample_rate = args.samplerate if isinstance(args.samplerate, int) and args.samplerate > 0 else settings_sr
    duplex_mode = args.duplex if isinstance(args.duplex, str) and args.duplex.strip() else settings_duplex
    seq = Sequencer(kit_path=args.kit, pattern_path=pattern_path, samplerate=sample_rate, duplex_mode=duplex_mode)
    if not pattern_arg:
        # Default startup should be a truly empty project.
        seq.new_project("new_project.json", kit=section.get("kit", DEFAULT_KIT_PATH))
    curses.wrapper(ui_loop, seq)


if __name__ == "__main__":
    main()
