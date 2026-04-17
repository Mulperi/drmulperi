import argparse
import configparser
import curses
import os

from .config import DEFAULT_KIT_PATH, DEFAULT_SETTINGS, SETTINGS_PATH, STEPS
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


def _load_sequencer_settings(path=SETTINGS_PATH):
    """Load sequencer defaults from settings.ini."""
    parser = configparser.ConfigParser()
    parser.read(path)
    section = parser["sequencer"] if "sequencer" in parser else {}
    default_kit = str(section.get("default_kit", DEFAULT_KIT_PATH)).strip()
    raw_follow_song = str(section.get("follow_song", "off")).strip().lower()
    follow_song = raw_follow_song in {"1", "true", "yes", "on"}
    raw_default_step_count = section.get("default_step_count", "16")
    try:
        parsed_step_count = int(str(raw_default_step_count).strip())
    except Exception:
        parsed_step_count = 16
    default_step_count = max(1, min(STEPS, parsed_step_count))
    return default_kit, follow_song, default_step_count


def _load_ui_settings(path=SETTINGS_PATH):
    """Load UI settings from settings.ini."""
    parser = configparser.ConfigParser()
    parser.read(path)
    section = parser["ui"] if "ui" in parser else {}
    defaults = {
        "color_primary": "cyan",
        "color_text": "white",
        "color_playhead": "green",
        "color_accent": "yellow",
        "color_divider": "blue",
        "color_record": "red",
        "color_meter": "green",
        "color_selection_fg": "white",
        "color_selection_bg": "red",
        "color_tertiary": "yellow",
        "text_bold": "off",
        "text_uppercase": "on",
    }
    colors = {}
    for key, default in defaults.items():
        val = str(section.get(key, default)).strip().lower()
        colors[key] = val if val else default
    return colors


def main(path=SETTINGS_PATH):
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    configured_default_kit, configured_follow_song, configured_default_step_count = _load_sequencer_settings(path)
    configured_colors = _load_ui_settings(path)
    parser.add_argument(
        "--kit",
        default=configured_default_kit,
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

    kit_path = str(args.kit or "").strip()
    settings_sr, settings_duplex = _load_audio_settings(path)
    sample_rate = args.samplerate if isinstance(args.samplerate, int) and args.samplerate > 0 else settings_sr
    duplex_mode = args.duplex if isinstance(args.duplex, str) and args.duplex.strip() else settings_duplex
    seq = Sequencer(
        kit_path=kit_path,
        pattern_path=pattern_path,
        samplerate=sample_rate,
        duplex_mode=duplex_mode,
        default_new_project_kit=kit_path,
        follow_song=configured_follow_song,
        default_step_count=configured_default_step_count,
    )
    if not pattern_arg:
        # Default startup should be a truly empty project.
        seq.new_project("new_project.json")
    curses.wrapper(ui_loop, seq, configured_colors)


if __name__ == "__main__":
    main()
