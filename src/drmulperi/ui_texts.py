"""Centralized user-facing text catalog.

Naming note:
- "UI" text is copy owned directly by the terminal interface, such as help lines,
    dialog titles, prompts, labels, and controller status messages.
- "backend" text is still user-facing, but it is produced by non-UI logic modules
    such as the sequencer and recorder. In this project it does not mean a web
    server or database backend; it means application-logic messages that the UI
    later displays.
"""


class TextNode(dict):
    """Dictionary node supporting both key and attribute access."""

    def __init__(self, data):
        super().__init__()
        for key, value in data.items():
            if isinstance(value, dict):
                self[key] = TextNode(value)
            else:
                self[key] = value

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


help = TextNode(
    {
        "pattern_params": {
            "name": "Pattern selector: Left/Right changes pattern, Enter opens rename dialog",
            "length": "Pattern steps: type digits to set immediately",
            "swing": "Pattern swing (0-10): type digits to set immediately",
            "mode": "Step mode (velocity, ratchet, blocks, detune, pan)",
        },
        "header": {
            "tabs": "Tabs: Left/Right switch view tabs. Down enters header controls.",
            "patterns": "Enter opens pattern dialog.",
            "bpm": "BPM: Enter opens dialog to set tempo.",
            "midi": "Enter toggles MIDI OUT.",
            "file": "Enter opens File menu.",
            "pattern": "Enter opens Pattern menu.",
            "song": "Enter toggles SONG mode.",
            "record": "Record menu.",
            "chain_set": "Enter sets song order.",
            "default": "Enter edits pitch.",
        },
        "mixer": {
            0: "Mixer: Sequencer track pan (1-9). Press Enter to edit.",
            1: "Mixer: Sequencer track volume (0-9). Press Enter to edit.",
            2: "Mixer: Sequencer track probability (0-9). Press Enter to edit.",
            3: "Mixer: Sequencer track pitch (0-24). Press Enter to edit.",
            4: "Mixer: Audio track pan (1-9). Press Enter to edit.",
            5: "Mixer: Audio track volume (0-9). Press Enter to edit.",
        },
        "song": {
            0: "Song: patterns list. Enter adds selected pattern to the chain.",
            1: "Song: chain list. Enter removes selected item from the chain.",
        },
        "export": {
            0: "Export: Bit depth (8/12/16-bit). Arrows/Space to cycle.",
            1: "Export: Sample rate. Arrows/Space to cycle.",
            2: "Export: Channels (Mono/Stereo). Arrows/Space to cycle.",
            3: "Export: Scope (Pattern/Song). Arrows/Space to cycle.",
            4: "Export: EQ (bass/treble) and TAPE (warble effect) toggles. Enter to toggle.",
            5: "Export: Enter to save audio file.",
        },
        "audio": {
            "track_settings": "Audio track settings (mode, rename, pan, volume, shift, clear). Enter opens dialog.",
            "track_name": "Audio track name. Enter track number to edit settings for this track.",
            "load_sample": "Load sample",
            "probability": "% Probability: 0=always, 9=rarely. Type 0-9 to set.",
            "mutegroup": "Mutegroup (0=off)",
            "track_pitch": "Track pitch: 0..24 scale (12 = no shift). Type digits to set.",
            "accent_sample": "SAMPLE: Accent track (no sample file)",
        },
    }
)


dialog = TextNode(
    {
        "confirm": {
            "title": "ARE YOU SURE?",
            "description": "Please confirm",
            "actions": {"cancel": "No", "ok": "Yes"},
        },
        "text_input": {
            "title": "ENTER VALUE",
            "description": "Enter value",
            "actions": {"cancel": "Cancel", "ok": "OK"},
        },
        "patterns": {"title": "PATTERNS (A:Add, D:Duplicate, X:Delete)"},
        "import_chops": {"title": "IMPORT CHOPS (Space preview, Enter action)"},
        "import_audio": {"title": "IMPORT AUDIO (Arrows move, <-/-> track, Space preview, Enter select)"},
        "record_settings": {"title": "RECORD SETTINGS"},
        "audio_export_options": {"title": "AUDIO EXPORT OPTIONS (Arrows/Space change, Enter export, Esc cancel)"},
        "kit_export_options": {"title": "KIT EXPORT OPTIONS (Arrows/Space change, Enter export, Esc cancel)"},
        "track_parameters": {"title": "TRACK PARAMETERS"},
        "audio_track_settings": {"title": "AUDIO TRACK SETTINGS"},
    }
)


labels = TextNode(
    {
        "rows": {
            "no_patterns": "(no patterns)",
            "no_input_devices": "(no input devices)",
            "browser_empty": "(empty)",
            "use_samples": "[ Use Samples ]",
            "cancel": "[ Cancel ]",
            "cancel_delete_recording": "[ Cancel + Delete Recording ]",
            "record": "[ Record ]",
            "stop": "[ Stop ]",
            "export_audio": "[ Export -> Filename ]",
            "export_kit": "[ Export Kit -> Folder ]",
        },
        "hints": {"use_arrows": "Use arrows to pick values."},
        "actions": {
            "cancel": "Cancel",
            "ok": "OK",
            "no": "No",
            "yes": "Yes",
        },
        "browser": {
            "mode_names": {
                "pattern": "PATTERN",
                "pattern_steps": "PROJECT",
                "sample": "SAMPLE",
                "audio_track": "SAMPLE",
                "default": "KIT",
            },
            "title_default": "{mode} BROWSER (Enter open/select, <-/-> or Backspace up, Esc close)",
            "title_sample": "{mode} BROWSER (Space preview)",
        },
    }
)


prompt = TextNode(
    {
        "dialog": {
            "save_project_as": "Save Project As folder name",
            "export_audio_filename": "Export audio filename",
            "export_kit_folder": "Export kit folder name",
            "song_sequence": "Give song sequence",
            "pattern_name": "Pattern name",
            "set_bpm": "Set BPM (20-300)",
        },
        "confirm": {
            "quit": "Quit application?",
            "clear_pattern": "Clear pattern {num} with existing data?",
            "clear_pattern_with_data": "Clear pattern {num}? This pattern contains data.",
            "delete_pattern_with_data": "Delete pattern {num}? This pattern contains data.",
            "force_delete_audio": "File used elsewhere. Force delete everywhere? {path_name}",
            "clear_audio_track": "Clear sample from audio track {track_num} and delete file? {path_name}",
            "import_patterns_single": "Import 1 pattern from clipboard? This replaces current pattern step data.",
            "import_patterns_many": "Import {count} patterns from clipboard? This replaces pattern step data and enables song mode.",
        },
        "track_params": {
            "names": [
                "Pan 1-9",
                "Volume 0-9",
                "Probability 0-9",
                "Group 0-9",
                "Pitch 0-24",
                "Shift 0-9",
                "Preview Sample",
                "Load Sample",
            ],
            "preview_action": "Preview Sample - Enter preview, second press stops",
            "load_action": "Load Sample - Left/Right track, Up/Down field, Enter browse",
            "edit_hint": "(Enter or type digit to edit in dialog, Left/Right track, Up/Down field, Esc close)",
        },
        "audio_track_params": {
            "names": ["Mode", "Rename", "Pan 1-9", "Volume 0-9", "Timeshift 0-50", "Clear Sample"],
            "edit_hint": "(Enter to apply/edit, Left/Right track, Up/Down field, Esc close)",
        },
    }
)


status = TextNode(
    {
        "generic": {
            "canceled": "Canceled",
            "enter_numeric_value": "Enter numeric value",
            "record_menu_closed": "Record menu closed",
            "import_canceled": "Import canceled",
            "drop_canceled": "Drop canceled",
            "drop_path_detected": "Drop path detected. Import options open automatically (Esc cancels).",
            "select_wav_to_import": "Select a .wav file to import",
            "no_target_track_selected": "No target track selected",
            "accent_no_parameter_here": "Accent track has no parameter here",
            "accent_no_track_parameters": "Accent track has no track parameters",
            "recording_file_missing": "Recording file was already missing",
            "import_canceled_deleted": "Import canceled and recording deleted",
            "mixer_hint": "Mixer: press Enter to edit selected value",
            "pattern_view": "Pattern view",
            "song_view": "Song view",
            "audio_view": "Audio view",
            "mixer_view": "Mixer view",
            "export_view": "Export view",
        },
        "pattern": {
            "steps": "Pattern steps: {value}",
            "swing": "Pattern swing: {value}",
            "humanize": "Pattern humanize: {state}",
            "name": "Pattern name: {name}",
            "cleared": "Cleared pattern {num}",
        },
        "track": {
            "pan": "Track {track_num} pan: {value}",
            "volume": "Track {track_num} volume: {value}",
            "probability": "Track {track_num} probability: {value}",
            "group": "Track {track_num} group: {value}",
            "pitch": "Track {track_num} pitch: {value}",
            "shift": "Track {track_num} shift: {value} ({shift_ms:+d}ms)",
            "name": "Track {track_num} name: {name}",
        },
        "tempo": {
            "tap": "Tap tempo: {bpm} BPM",
            "set": "BPM: {bpm}",
            "invalid": "BPM must be a number (20-300)",
        },
        "importing": {
            "source_ready": "Import source ready: {name}",
            "clipboard_parse_failed": "Clipboard import failed: {message}",
            "copied_patterns": "Copied {count} patterns to clipboard",
        },
        "file": {
            "saved": "Saved {name}",
            "browse_failed": "Browse failed: {error}",
            "copy_failed": "Copy failed: {error}",
            "delete_failed": "Delete failed: {error}",
            "save_failed": "Save failed: {error}",
        },
        "errors": {
            "confirm_action_failed": "Confirm action failed: {error}",
            "input_action_failed": "Input action failed: {error}",
            "invalid_pattern_menu_option": "Invalid Pattern menu option",
            "invalid_file_menu_option": "Invalid File menu option",
        },
    }
)


backend = TextNode(
    {
        "sequencer": {
            "chop": {
                "select_wav": "Select a .wav file to chop",
                "load_failed": "Chop load failed: {error}",
                "too_short": "Sample too short to chop",
                "prepared": "Prepared {count} chops{sr_hint}",
                "invalid_index": "Invalid chop index",
                "no_prepared": "No prepared chops",
                "save_failed": "Chop save failed: {error}",
                "loaded_from_chop": "{message} (from chop)",
            },
            "project": {
                "load_canceled": "Load canceled",
                "pattern_not_found": "Pattern not found: {name}",
                "load_failed": "Load failed: {error}",
                "loaded": "Loaded {name}",
                "new_failed": "New project failed: {error}",
                "new_created": "New project: {name}",
                "save_canceled": "Save canceled",
                "save_failed": "Save failed: {error}",
                "saved": "Saved {name}",
                "save_as_canceled": "Save Project As canceled",
                "folder_create_failed": "Project folder create failed: {error}",
                "pattern_save_failed": "Pattern save failed: {error}",
                "reload_failed": "Project saved but reload failed: {message}",
                "saved_portable": "Project saved: {name} ({kit_count}/8 kit + {track_audio_count} track samples + {pattern_filename})",
                "import_canceled": "Import canceled",
                "project_not_found": "Project not found: {name}",
                "import_failed": "Import failed: {error}",
                "imported_step_data": "Imported step data from {name} ({imported}/{count} patterns)",
            },
            "kit": {
                "folder_not_found": "Kit folder not found: {name}",
                "loaded": "Loaded kit {name} ({loaded_count}/8 samples)",
                "export_canceled": "Kit export canceled",
                "export_failed": "Kit export failed: {error}",
                "no_samples": "No kit samples to export",
                "exported": "Kit exported: {name} ({exported} samples, {sample_rate}Hz, {bit_depth}-bit, {channels})",
            },
            "sample": {
                "invalid_track": "Invalid track",
                "select_wav": "Select a .wav file",
                "load_failed": "Sample load failed: {error}",
                "loaded_track_sample": "Loaded track sample {name}",
                "with_sr_hint": "{message} (SR {src_sr}->{dst_sr})",
                "no_file_force_delete": "No file selected for force delete",
                "force_deleted": "Force deleted file and removed {removed} references",
                "force_removed_delete_failed": "Removed {removed} references (file delete failed: {error})",
                "force_removed_missing": "Removed {removed} references (file already missing)",
                "cleared_kept": "Cleared track sample on track {track_num} (file kept: used elsewhere)",
                "cleared_deleted": "Cleared track sample on track {track_num} (file deleted)",
                "cleared_delete_failed": "Cleared track sample on track {track_num} (delete failed: {error})",
                "cleared": "Cleared track sample on track {track_num}",
                "no_sample_loaded": "No sample loaded on this track",
                "rename_canceled": "Rename canceled",
                "name_exists": "Name exists",
                "rename_failed": "Rename failed: {error}",
                "renamed": "Renamed {old_name} -> {new_name}",
            },
            "export": {
                "audio_canceled": "Audio export canceled",
                "audio_failed": "Audio export failed: {error}",
                "audio_exported": "Exported audio: {name} ({scope}, {sample_rate}Hz, {bit_depth}-bit, {channels})",
            },
            "song": {
                "on": "Song ON",
                "off": "Song OFF",
                "canceled": "Song canceled",
                "invalid_chain_use": "Invalid chain (use pattern numbers 1-{max_patterns})",
                "invalid_chain_range": "Invalid chain (pattern range 1-{max_patterns})",
                "invalid_chain_empty": "Invalid chain (empty)",
                "set": "Song set",
                "appended": "Added pattern {pattern_num} to song",
                "removed": "Removed pattern {pattern_num} from song",
                "removed_last": "Removed last song item",
            },
            "midi": {
                "on": "MIDI OUT ON",
                "off": "MIDI OUT OFF",
            },
            "swing": {
                "canceled": "Swing canceled",
                "not_number": "Swing must be a number (0-10)",
                "out_of_range": "Swing out of range (0-10)",
                "set": "Swing set to {value}",
            },
            "pattern": {
                "added": "Added pattern {num}",
                "at_least_one_required": "At least one pattern is required",
                "deleted": "Deleted pattern {num}",
                "copied": "Copied pattern {num}",
                "clipboard_empty": "Clipboard empty",
                "pasted": "Pasted pattern {num}",
                "each_pattern_rows": "Each pattern must have exactly {rows} rows",
                "row_width_exceeded": "Row 1 has {row_width} steps, but max_step_count is {max_step_count}. Increase [sequencer] max_step_count in settings.ini to paste longer patterns",
                "row_exact_steps": "Row {track_num} must have exactly {row_width} steps",
                "invalid_char": "Invalid char '{char}' on row {track_num}, step {step_num}",
                "clipboard_empty_or_invalid": "Clipboard is empty or invalid",
                "pattern_parse_error": "Pattern {pattern_num}: {message}",
                "imported_many": "Imported {count} patterns from clipboard (song mode ON)",
                "imported_one": "Imported 1 pattern from clipboard",
            },
            "audio_track": {
                "invalid_pattern": "Invalid pattern",
                "mode_song": "Track {track_num} mode: Song (from Pattern {pattern_num})",
                "mode_pattern": "Track {track_num} mode: Pattern {pattern_num}",
                "mode_label_pattern": "Pattern",
                "mode_label_song": "Song",
            },
        },
        "recorder": {
            "monitor": {
                "engine_info": "engine duplex {sample_rate}Hz",
                "input_meter_on_engine": "Input meter ON ({info})",
                "device_fallback_name": "device {device_id}",
                "device_info": "{device_name} {sample_rate}Hz ch{channels}",
                "input_meter_on_device": "Input meter ON ({device_name}, {sample_rate}Hz, ch {channels})",
                "failed": "Record monitor failed: {error}",
            },
            "capture": {
                "duplex_unavailable": "Duplex mode requested but unavailable. Restart with a duplex-capable device.",
                "no_input_device": "No input device",
                "requires_duplex": "Recording while playing requires duplex input device.",
                "fallback_mode": "Recording fallback mode (non-duplex device)",
                "canceled": "Recording canceled",
                "failed_no_audio": "Record failed: no audio captured",
                "recorded": "Recorded {name}{sr_hint}",
                "backing_render_error": "Record failed: backing render error ({error})",
                "empty_backing": "Record failed: empty backing",
                "failed": "Record failed: {error}",
                "recording_with_precount": "Recording... (precount + {scope})",
                "recording": "Recording... ({scope})",
            },
        },
    }
)


def fmt(template, **kwargs):
    return str(template).format(**kwargs)


def pattern_humanize_help(amount_percent):
    return f"Pattern humanize toggle: Enter toggles OFF/ON (ON = {int(amount_percent)}%)"


def preview_sample_help(name):
    return f"Preview sample: {name}"


def audio_track_sample_help(name):
    return f"AUDIO TRACK SAMPLE: {name}"


def sample_help(name):
    return f"SAMPLE: {name}  (Enter on ▶ preview, Enter on ↓ load)"


def browser_title(mode):
    mode_name = labels.browser.mode_names.get(mode, labels.browser.mode_names["default"])
    if mode in {"sample", "audio_track"}:
        return labels.browser.title_sample.format(mode=mode_name)
    return labels.browser.title_default.format(mode=mode_name)


def source_label(name):
    return f"Source: {name}"


def path_label(path):
    return f"Path: {path}"


def track_params_prompt(track_name, index):
    if index == 6:
        return f"{track_name} {prompt.track_params.preview_action}"
    if index == 7:
        return f"{track_name} {prompt.track_params.load_action}"
    return f"{track_name} {prompt.track_params.names[index]} {prompt.track_params.edit_hint}"


def audio_track_params_prompt(track_name, index):
    return f"{track_name} {prompt.audio_track_params.names[index]} {prompt.audio_track_params.edit_hint}"
