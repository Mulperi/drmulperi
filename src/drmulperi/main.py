import argparse
import configparser
import curses
import os

from .config import DEFAULT_SETTINGS, SETTINGS_PATH
from .sequencer import Sequencer
from .ui import ui_loop


def _first_json_in_dir(project_dir):
    """Return first JSON file path in directory (case-insensitive sorted), else None."""
    try:
        names = sorted(os.listdir(project_dir), key=str.lower)
    except Exception:
        return None
    for name in names:
        full = os.path.join(project_dir, name)
        if os.path.isfile(full) and name.lower().endswith(".json"):
            return full
    return None


def _resolve_project_pattern_path(project_dir):
    """Resolve project folder to first JSON file path, raising ValueError on failure."""
    folder = os.path.abspath(os.path.expanduser(str(project_dir or "").strip()))
    if not folder:
        raise ValueError("Project folder is empty")
    if not os.path.isdir(folder):
        raise ValueError(f"Project folder not found: {folder}")
    first_json = _first_json_in_dir(folder)
    if not first_json:
        raise ValueError(f"No .json project file found in folder: {folder}")
    return first_json


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


def _load_export_settings(path=SETTINGS_PATH):
    """Load export (EQ/tape) settings from settings.ini."""
    parser = configparser.ConfigParser()
    parser.read(path)
    section = parser["export"] if "export" in parser else {}
    try:
        eq_low_freq = float(section.get("eq_low_freq", "70"))
        eq_low_freq = max(20, min(20000, eq_low_freq))
    except (ValueError, TypeError):
        eq_low_freq = 70.0
    try:
        eq_low_gain = float(section.get("eq_low_gain", "4"))
        eq_low_gain = max(-24, min(24, eq_low_gain))
    except (ValueError, TypeError):
        eq_low_gain = 4.0
    try:
        eq_high_freq = float(section.get("eq_high_freq", "9000"))
        eq_high_freq = max(20, min(20000, eq_high_freq))
    except (ValueError, TypeError):
        eq_high_freq = 9000.0
    try:
        eq_high_gain = float(section.get("eq_high_gain", "3"))
        eq_high_gain = max(-24, min(24, eq_high_gain))
    except (ValueError, TypeError):
        eq_high_gain = 3.0
    return {"eq_low_freq": eq_low_freq, "eq_low_gain": eq_low_gain, "eq_high_freq": eq_high_freq, "eq_high_gain": eq_high_gain}



def _load_sequencer_settings(path=SETTINGS_PATH):
    """Load sequencer defaults from settings.ini."""
    parser = configparser.ConfigParser()
    parser.read(path)
    section = parser["sequencer"] if "sequencer" in parser else {}
    default_kit = str(section.get("default_kit", "")).strip()
    raw_follow_song = str(section.get("follow_song", "off")).strip().lower()
    follow_song = raw_follow_song in {"1", "true", "yes", "on"}
    raw_default_step_count = section.get("default_step_count", "16")
    raw_max_step_count = section.get("max_step_count", "32")
    raw_default_pattern_count = section.get("default_pattern_count", "1")
    raw_track_shift_step_ms = section.get("track_shift_step_ms", "5")
    try:
        parsed_step_count = int(str(raw_default_step_count).strip())
    except Exception:
        parsed_step_count = 16
    try:
        parsed_max_step_count = int(str(raw_max_step_count).strip())
    except Exception:
        parsed_max_step_count = 32
    try:
        parsed_default_pattern_count = int(str(raw_default_pattern_count).strip())
    except Exception:
        parsed_default_pattern_count = 1
    try:
        parsed_track_shift_step_ms = int(str(raw_track_shift_step_ms).strip())
    except Exception:
        parsed_track_shift_step_ms = 5
    max_step_count = max(1, parsed_max_step_count)
    default_step_count = max(1, min(max_step_count, parsed_step_count))
    default_pattern_count = max(1, parsed_default_pattern_count)
    track_shift_step_ms = max(1, min(50, parsed_track_shift_step_ms))
    return default_kit, follow_song, default_step_count, max_step_count, default_pattern_count, track_shift_step_ms


def _load_ui_settings(path=SETTINGS_PATH):
    """Load UI settings from settings.ini."""
    parser = configparser.ConfigParser()
    parser.read(path)
    section = parser["ui"] if "ui" in parser else {}
    defaults = {
        "color_primary": "cyan",
        "color_text": "white",
        "color_accent": "green",
        "color_accent": "yellow",
        "color_divider": "blue",
        "color_record": "red",
        "color_meter": "green",
        "color_selection_fg": "white",
        "color_selection_bg": "red",
        "color_tertiary": "yellow",
        "hotkey_tab_1": "F1",
        "hotkey_tab_2": "F2",
        "hotkey_tab_3": "F3",
        "hotkey_tab_4": "x",
        "hotkey_tab_5": "c",
        "text_bold": "off",
        "text_uppercase": "on",
        "rec_input_metering": "off",
        "large_blocks": "off",
        "sort_audio_tracks_by_type": "on",
        "seq_grid_wide": "off",
        "playhead_divider": "on",
        "show_steps_outside_pattern": "on",
        "humanize_amount": "50",
    }
    colors = {}
    for key, default in defaults.items():
        val = str(section.get(key, default)).strip().lower()
        colors[key] = val if val else default
    return colors


def main(path=SETTINGS_PATH):
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    configured_default_kit, configured_follow_song, configured_default_step_count, configured_max_step_count, configured_default_pattern_count, configured_track_shift_step_ms = _load_sequencer_settings(path)
    configured_colors = _load_ui_settings(path)
    configured_export = _load_export_settings(path)
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
        "--project",
        default=None,
        help="Project folder; loads the first .json file found in that folder",
    )
    parser.add_argument(
        "project_arg",
        nargs="?",
        default=None,
        help="Optional project folder or project JSON path (same as --project/--pattern)",
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
    project_arg = (args.project or "").strip()
    positional_arg = (args.project_arg or "").strip()

    # Precedence: --project > --pattern > positional argument > default new project.
    if project_arg:
        try:
            pattern_path = _resolve_project_pattern_path(project_arg)
        except ValueError as exc:
            parser.error(str(exc))
    elif pattern_arg:
        pattern_path = pattern_arg if pattern_arg.lower().endswith(".json") else f"{pattern_arg}.json"
    elif positional_arg:
        expanded = os.path.abspath(os.path.expanduser(positional_arg))
        if os.path.isdir(expanded):
            try:
                pattern_path = _resolve_project_pattern_path(expanded)
            except ValueError as exc:
                parser.error(str(exc))
        else:
            pattern_path = positional_arg if positional_arg.lower().endswith(".json") else f"{positional_arg}.json"
    else:
        pattern_path = "new_project.json"

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
        max_step_count=configured_max_step_count,
        default_pattern_count=configured_default_pattern_count,
        humanize_amount=configured_colors.get("humanize_amount", "50"),
        track_shift_step_ms=configured_track_shift_step_ms,
    )
    if not project_arg and not pattern_arg and not positional_arg:
        # Default startup should be a truly empty project.
        seq.new_project("new_project.json")
    curses.wrapper(ui_loop, seq, configured_colors, configured_export)


if __name__ == "__main__":
    main()
