import curses
import os
import shlex
import subprocess
import time
from urllib.parse import unquote, urlparse

from .config import (
    ACCENT_TRACK,
    FILE_MENU_ITEMS,
    CLEAR_COL,
    LOAD_COL,
    PREVIEW_COL,
    PATTERN_MENU_ITEMS,
    PATTERNS,
    REC_COL,
    TRACK_LABEL_COL,
    TRACK_PITCH_COL,
    TRACKS,
)
from .keymap import Keymap, _event_tokens
from .navigation import NavigationModel
from . import recorder
from . import ui_texts as texts


# Audio tab volume column — own negative ID, no collision with steps or other param cols.
AUDIO_VOLUME_COL = -7
TAB_SEQUENCER = 0
TAB_SONG = 1
TAB_AUDIO = 2
TAB_MIXER = 3
TAB_EXPORT = 4

def _read_system_clipboard_text():
    """Return clipboard text using platform tools (macOS/Linux) with safe fallback."""
    # macOS
    try:
        result = subprocess.run(["pbpaste"], capture_output=True, text=True, check=False)
        if result.returncode == 0 and isinstance(result.stdout, str):
            text = result.stdout
            if text:
                return text
    except Exception:
        pass
    # Linux (when available)
    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0 and isinstance(result.stdout, str):
            text = result.stdout
            if text:
                return text
    except Exception:
        pass
    return ""


def _write_system_clipboard_text(text):
    """Write text to system clipboard using platform tools (macOS/Linux)."""
    payload = str(text or "")
    # macOS
    try:
        result = subprocess.run(["pbcopy"], input=payload, text=True, capture_output=True, check=False)
        if result.returncode == 0:
            return True, ""
    except Exception:
        pass
    # Linux (when available)
    try:
        result = subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=payload,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return True, ""
    except Exception:
        pass
    return False, "Clipboard write tool not available"


def _normalize_dropped_path(raw_path):
    """Normalize dragged path text from terminal into a local filesystem path."""
    text = str(raw_path or "").strip()
    if not text:
        return ""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ['"', "'"]:
        text = text[1:-1]
    if text.startswith("file://"):
        parsed = urlparse(text)
        text = unquote(parsed.path or "")
    else:
        text = unquote(text)
    try:
        parts = shlex.split(text)
        if parts:
            text = parts[0]
    except ValueError:
        pass
    return os.path.expanduser(text)

def draw(
    stdscr,
    seq,
    cursor_x,
    cursor_y,
    navigation,
    edit_mode,
    pattern_load_prompt,
    status_message,
    pattern_menu_active,
    pattern_menu_kind,
    pattern_menu_index,
    patterns_overlay_active,
    patterns_overlay_index,
    import_overlay_active,
    import_overlay_index,
    import_overlay_path,
    import_overlay_can_delete_source,
    import_target_drum_track,
    import_target_audio_track,
    chop_overlay_active,
    chop_overlay_index,
    record_overlay_active,
    record_device_names,
    record_device_index,
    record_input_sources,
    record_input_source_index,
    record_overlay_index,
    record_action_index,
    record_channels,
    record_precount_enabled,
    record_precount_pattern,
    record_level_db,
    record_monitor_running,
    record_level_tick,
    record_monitor_info,
    record_capture_active,
    file_menu_key_label,
    file_browser_active,
    file_browser_mode,
    file_browser_path,
    file_browser_items,
    file_browser_index,
    audio_export_options_active,
    audio_export_options,
    audio_export_options_index,
    kit_export_options_active,
    kit_export_options,
    kit_export_options_index,
    mode_key_label,
    tab_1_label,
    tab_2_label,
    tab_3_label,
    tab_4_label,
    tab_5_label,
    export_eq_enabled,
    export_tape_enabled,
    clear_key_label,
    length_dec_label,
    length_inc_label,
    ui_options,
    track_params_dialog_active,
    track_params_dialog_track,
    track_params_dialog_index,
    track_params_dialog_input,
    audio_track_params_dialog_active,
    audio_track_params_dialog_track,
    audio_track_params_dialog_index,
    text_input_dialog_active,
    text_input_dialog_message,
    text_input_dialog_input,
    text_input_dialog_index,
    confirm_dialog_active,
    confirm_dialog_message,
    confirm_dialog_index,
    theme
):
    """Render full terminal UI frame from current sequencer/controller state."""
    navigation.clamp()
    header_focus = navigation.header.focus
    header_section = navigation.header.section
    header_param = navigation.header.current_param()
    pattern_params_focus = navigation.pattern.focus
    pattern_params_index = navigation.pattern.index
    active_tab = navigation.active_tab
    header_edit_active = navigation.header.edit_active
    sequencer_content_focus = active_tab == TAB_SEQUENCER and not header_focus and not pattern_params_focus
    song_content_focus = active_tab == TAB_SONG and not header_focus
    audio_content_focus = active_tab == TAB_AUDIO and not header_focus
    mixer_content_focus = active_tab == TAB_MIXER and not header_focus
    export_content_focus = active_tab == TAB_EXPORT and not header_focus
    stdscr.clear()
    h, w = stdscr.getmaxyx()
    modal_dim_active = ui_options.get("dim_overlay_enabled", True) and (
        pattern_menu_active
        or patterns_overlay_active
        or chop_overlay_active
        or import_overlay_active
        or record_overlay_active
        or file_browser_active
        or audio_export_options_active
        or kit_export_options_active
        or track_params_dialog_active
        or audio_track_params_dialog_active
        or text_input_dialog_active
        or confirm_dialog_active
    )
    dim_background_active = modal_dim_active

    def safe_add(y, x, text, attr=0, transform_case=True):
        """Safely draw text in curses with clipping and optional global text transforms.

        Use transform_case=False for user-provided filenames/paths so their original
        casing is preserved.
        """
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        if not isinstance(text, str):
            text = str(text)
        if transform_case:
            if theme.get("text_uppercase_enabled", True):
                text = text.upper()
            else:
                text = text.lower()
        if theme.get("text_bold_enabled", False):
            attr = (attr or 0) | curses.A_BOLD
        if dim_background_active:
            attr = (attr or 0) | curses.A_DIM
        max_len = w - x
        if max_len <= 0:
            return
        if y == h - 1 and x + len(text) >= w:
            text = text[:max(0, w - x - 1)]
        else:
            text = text[:max_len]
        if not text:
            return
        try:
            if attr:
                stdscr.addstr(y, x, text, attr)
            else:
                stdscr.addstr(y, x, text)
        except curses.error:
            pass

    def draw_hline(y, x0, x1, ch="-", attr=0):
        if y < 0 or y >= h or x0 > x1:
            return
        x0 = max(0, x0)
        x1 = min(w - 1, x1)
        safe_add(y, x0, ch * (x1 - x0 + 1), attr)

    def draw_box(x0, y0, x1, y1, attr=0):
        if x0 >= x1 or y0 >= y1:
            return
        if x0 < 0 or y0 < 0 or x1 >= w or y1 >= h:
            return
        draw_hline(y0, x0 + 1, x1 - 1, "─", attr)
        draw_hline(y1, x0 + 1, x1 - 1, "─", attr)
        safe_add(y0, x0, "┌", attr)
        safe_add(y0, x1, "┐", attr)
        safe_add(y1, x0, "└", attr)
        safe_add(y1, x1, "┘", attr)
        for y in range(y0 + 1, y1):
            safe_add(y, x0, "│", attr)
            safe_add(y, x1, "│", attr)

    def _begin_modal_draw():
        nonlocal dim_background_active
        prev = dim_background_active
        dim_background_active = False
        return prev

    def _end_modal_draw(prev):
        nonlocal dim_background_active
        dim_background_active = prev

    # terminal size check for outlined layout (minimum size to show all UI elements with borders and spacing).
    min_layout_h = 16
    min_layout_w = 40
    if h < min_layout_h or w < min_layout_w:
        safe_add(0, 0, "Terminal too small for outlined layout")
        stdscr.refresh()
        return

    frame_attr = theme["record"] if record_capture_active else theme["frame"]

    area_prompt = h - 1
    outer_left = 0
    outer_top = 0
    outer_right = w - 1
    outer_bottom = h - 2
    draw_box(outer_left, outer_top, outer_right, outer_bottom, frame_attr)

    header_left = 2
    header_right = w - 3
    area_menubar = 1
    area_work_left = 2
    area_work_right = w - 3
    area_work_top = 2
    area_work_bottom = h - 3
    draw_box(area_work_left, area_work_top, area_work_right, area_work_bottom, frame_attr)

    mode = {
        "velocity": "VELOCITY",
        "ratchet": "RATCHET",
        "blocks": "BLOCKS",
        "detune": "DETUNE",
        "pan": "PAN",
    }.get(edit_mode, "VELOCITY")
    # Menubar options are defined here. Edit labels/ordering in this list.
    top_menus = [
        ("file", " FILE "),
        ("pattern", " PATT "),
        ("song", " SONG "),
        ("record", " REC "),
        ("bpm", f" {seq.bpm} "),
        ("pitch", f" {seq.pitch_semitones:+d}st "),
        ("midi", " MIDI "),
    ]
    top_menu_x = {}
    menu_x = outer_left + 2
    for menu_key, menu_label in top_menus:
        top_menu_x[menu_key] = menu_x
        menu_attr = theme["text"]
        if menu_key == "song":
            menu_attr = theme["chain_on"] if seq.chain_enabled else theme["chain_off"]
        if menu_key == "record":
            menu_attr = theme["record"] if record_capture_active else theme["text"]
        if menu_key == "midi":
            menu_attr = theme["midi_on"] if seq.midi_out_enabled else theme["midi_off"]
        if pattern_menu_active and pattern_menu_kind == menu_key:
            menu_attr = theme["title"]
        if header_focus and header_section == "params" and header_param == menu_key:
            menu_attr = menu_attr | theme["selected"]
        safe_add(outer_top, menu_x, menu_label, menu_attr)
        if menu_key in {"file", "pattern", "record"} and len(menu_label) > 2:
            safe_add(outer_top, menu_x + 1, menu_label[1], menu_attr | curses.A_UNDERLINE)
        menu_x += len(menu_label) + 1

    tabs = [
        ("seq", tab_1_label),
        ("song", tab_2_label),
        ("aud", tab_3_label),
        ("mix", tab_4_label),
        ("exp", tab_5_label),
    ]
    tx = 3
    for i, (label, hotkey) in enumerate(tabs):
        tab_text = f"┌ {label} {hotkey} ┐"
        attr = theme["muted"]
        if i == active_tab:
            attr = theme["title"]
        if header_focus and header_section == "tabs" and i == active_tab:
            attr = attr | theme["selected"]
        safe_add(area_menubar, tx, tab_text, attr)
        hotkey_x = tx + len(f"┌ {label} ")
        safe_add(area_menubar, hotkey_x, hotkey, attr | curses.A_UNDERLINE)
        tx += len(tab_text) + 1

    content_x = max(header_left + 2, tx + 2)

    queue_flash_on = int(time.time() * 2) % 2 == 0
    count = seq.pattern_count()
    max_visible = min(12, max(1, count))
    start_idx = 0
    if count > max_visible:
        start_idx = max(0, min(seq.view_pattern - (max_visible // 2), count - max_visible))
    pattern_line = "  "
    for i in range(start_idx, start_idx + max_visible):
        if seq.view_pattern == i:
            pattern_line += f"[{i+1}] "
        elif (not seq.chain_enabled) and seq.playing and seq.next_pattern == i:
            pattern_line += f"({i+1}) " if queue_flash_on else f" {i+1}  "
        else:
            pattern_line += f" {i+1}  "
    if start_idx > 0:
        pattern_line = "... " + pattern_line
    if count > (start_idx + max_visible):
        pattern_line += "... "

    # Always show song order text, even when song mode is off.
    song_parts = []
    if seq.chain:
        for idx, pat in enumerate(seq.chain):
            label = str(pat + 1)
            if seq.chain_enabled and idx == seq.chain_pos:
                song_parts.append(f"[{label}]")
            else:
                song_parts.append(label)
    song_line = "-".join(song_parts) if song_parts else "-"

    area_work_content_x = area_work_left + 2
    # Two control rows directly under tabs (pattern controls area).
    area_patt_controls = (area_work_top + 1, area_work_top + 2)
    area_patt_controls_y = area_patt_controls[0]
    area_patt_values_y = area_patt_controls[1]
    playhead_y = area_work_top + 3
    current_length = seq.pattern_length[seq.view_pattern]
    show_playhead = seq.playing and (seq.view_pattern == seq.pattern)
    x = area_work_content_x
    safe_add(playhead_y, x, "  ", theme["text"])
    x += 2

    if active_tab == TAB_SEQUENCER:
        pattern_name = seq.get_pattern_name(seq.view_pattern)
        name_cell_width = max(18, min(50, w - area_work_content_x - 4))
        name_value = pattern_name
        name_text = str(name_value or "")[:name_cell_width].ljust(name_cell_width)
        name_attr = theme["text"]
        if pattern_params_focus and pattern_params_index == 0:
            name_attr = name_attr | theme["selected"]
        safe_add(
            area_patt_controls_y,
            area_work_content_x,
            name_text,
            name_attr,
            transform_case=False,
        )

        pattern_param_table = [
            ("name", "NAME", "", 8),
            ("length", "LEN", str(seq.pattern_length[seq.view_pattern]), 8),
            ("swing", "SW", str(seq.current_pattern_swing_ui()), 7),
            ("humanize", "", "HUMAN", 7),
            ("mode", "MODE", mode.title(), 8),
        ]
        px = area_work_content_x
        for idx, (item_key, item_header, item_value, cell_w) in enumerate(pattern_param_table):
            if item_key == "name":
                continue
            value_attr = theme["text"]
            if item_key == "humanize" and seq.current_pattern_humanize_enabled():
                value_attr = theme["accent"]
            if pattern_params_focus and pattern_params_index == idx:
                value_attr = value_attr | theme["selected"]
            safe_add(area_patt_values_y, px, f"{item_value:<{cell_w}}", value_attr)
            px += cell_w + 2

    def col_cell_width(col):
        if col == "audio_name":
            return 16
        if 0 <= col < seq.max_step_count:
            return 1
        if col == LOAD_COL:
            return 1
        if col == PREVIEW_COL:
            return 1
        if col == AUDIO_VOLUME_COL:
            return 3
        if col == REC_COL:
            return 1
        if col == CLEAR_COL:
            return 1
        if col == TRACK_PITCH_COL:
            return 3
        return 3

    # --- Sequencer tab UI elements: playhead lane + step-grid baseline ---
    seq_col_gap = 1 if ui_options.get("seq_grid_wide_enabled", False) else 0
    if active_tab == 0:
        # Sequencer view: reserve the preview slot before the step grid.
        safe_add(playhead_y, x, " " * (1 + seq_col_gap), theme["text"])
        x += 1 + seq_col_gap
        step_x = x
        _max_steps = seq.max_step_count
        step_span = _max_steps * (1 + seq_col_gap)
        safe_add(playhead_y, step_x, " " * step_span, theme["muted"])
        if show_playhead and 0 <= seq.step < _max_steps:
            safe_add(playhead_y, step_x + (seq.step * (1 + seq_col_gap)), "v", theme["playhead"])
        if ui_options.get("playhead_divider_enabled", True) and 1 <= current_length < _max_steps:
            safe_add(playhead_y, step_x + ((current_length - 1) * (1 + seq_col_gap)), "|", theme["hint"])
    # --- Audio tab UI elements: rows align to sequencer lanes (no playhead heading) ---
    elif active_tab == TAB_SONG:
        song_state = "ON" if seq.chain_enabled else "OFF"
        safe_add(area_patt_controls_y, area_work_content_x, f"Song mode: {song_state}", theme["title"] if seq.chain_enabled else theme["muted"])
        safe_add(area_patt_values_y, area_work_content_x, "Enter left to add, Enter right to remove.", theme["muted"])
    elif active_tab == TAB_AUDIO:
        safe_add(area_patt_controls_y, area_work_content_x, "Press enter on sample name to toggle song/pattern mode.", theme["muted"])
        safe_add(area_patt_values_y, area_work_content_x, "Song-level samples don't trigger per pattern.", theme["muted"])
        # safe_add(playhead_y, area_work_content_x, "Enter on track name toggles Pattern/Song mode.", theme["muted"])
    elif active_tab == TAB_MIXER:
        mixer_base_x = area_work_content_x + len("1 ") + 2
        mixer_audio_x = mixer_base_x + 13
        safe_add(playhead_y, mixer_base_x, "Sequencer Tracks", theme["title"])
        safe_add(playhead_y, mixer_audio_x, "Audio Tracks", theme["title"])

    row_start = area_work_top + 4
    pattern_count = seq.pattern_count()
    song_chain_count = len(seq.chain)
    if active_tab == TAB_SEQUENCER:
        visible_rows = TRACKS
    elif active_tab == TAB_EXPORT:
        visible_rows = 0
    elif active_tab == TAB_SONG:
        visible_rows = max(pattern_count, song_chain_count, 1)
    else:
        visible_rows = TRACKS - 1
    if active_tab == TAB_SEQUENCER:
        track_order = [t for t in range(TRACKS - 1)]
    elif active_tab == TAB_AUDIO:
        sort_audio_tracks_by_type = bool(ui_options.get("sort_audio_tracks_by_type_enabled", True))
        if sort_audio_tracks_by_type:
            track_order = (
                [t for t in range(TRACKS - 1) if seq.audio_track_mode[t] == 0]
                + [t for t in range(TRACKS - 1) if seq.audio_track_mode[t] == 1]
            )
        else:
            track_order = [t for t in range(TRACKS - 1)]
    else:
        track_order = [t for t in range(TRACKS - 1)]
    first_song_row = None
    if active_tab == TAB_AUDIO:
        for idx, tr in enumerate(track_order):
            if seq.audio_track_mode[tr] == 1:
                first_song_row = idx
                break
    now_pc = time.perf_counter()
    for row_idx in range(visible_rows):
        y = row_start + row_idx
        if y >= area_work_bottom:
            continue
        if active_tab == TAB_SONG:
            left_attr = theme["text"]
            right_attr = theme["text"]
            left_selected = song_content_focus and cursor_x == 0 and cursor_y == row_idx
            right_selected = song_content_focus and cursor_x == 1 and cursor_y == row_idx
            left_name = texts.labels.rows.no_patterns
            if row_idx < pattern_count:
                left_name = f"{row_idx + 1} {seq.get_pattern_name(row_idx)}"
            right_name = texts.labels.rows.browser_empty
            if row_idx < song_chain_count:
                chain_pattern = int(seq.chain[row_idx])
                right_name = f"{chain_pattern + 1} {seq.get_pattern_name(chain_pattern)}"
            left_title_x = area_work_content_x
            right_title_x = max(left_title_x + 20, (w // 2))
            if row_idx == 0:
                safe_add(playhead_y, left_title_x, "Patterns", theme["title"])
                safe_add(playhead_y, right_title_x, "Chain List", theme["title"])
            safe_add(y, left_title_x, left_name[:max(1, right_title_x - left_title_x - 2)], left_attr | (theme["selected"] if left_selected else 0), transform_case=False)
            safe_add(y, right_title_x, right_name[:max(1, area_work_right - right_title_x - 1)], right_attr | (theme["selected"] if right_selected else 0), transform_case=False)
            continue

        t = row_idx if active_tab == TAB_SEQUENCER else track_order[row_idx]

        row_attr = theme["accent"] if t == ACCENT_TRACK else theme["text"]
        if seq.muted_rows[t]:
            row_attr = theme["muted"]
        if active_tab == TAB_AUDIO and seq.audio_track_mode[t] == 1:
            row_attr = theme["accent"]
        # No extra separator line in Audio view; ordering + color indicate grouping.

        x = area_work_content_x
        if active_tab == TAB_AUDIO:
            row_label = f"{t+1} "
        elif active_tab == TAB_MIXER:
            row_label = f"{t+1} "
        else:
            row_label = "A " if t == ACCENT_TRACK else f"{t+1} "
        label_attr = row_attr
        trigger_arr = getattr(
            seq,
            "audio_track_trigger_until" if active_tab == TAB_AUDIO else "seq_track_trigger_until",
            [0.0] * TRACKS,
        )
        if t < TRACKS - 1 and not seq.muted_rows[t] and trigger_arr[t] > now_pc:
            label_attr = theme["playhead"]
        track_label_selected = (
            (active_tab == 0 and sequencer_content_focus)
            or (active_tab == TAB_AUDIO and audio_content_focus)
        ) and cursor_x == TRACK_LABEL_COL and cursor_y == row_idx
        if track_label_selected:
            label_attr = label_attr | theme["selected"]
        safe_add(y, x, row_label, label_attr)
        x += len(row_label)

        def velocity_attr(value):
            if value <= 0:
                return theme["muted"]
            if value < 4:
                return theme["velocity_low"]
            return theme["velocity_high"]

        block_on_char = "■" if ui_options.get("large_blocks_enabled", False) else "▪"
        show_steps_outside_pattern = ui_options.get("show_steps_outside_pattern_enabled", True)

        # --- Audio tab UI elements: audio parameter columns + sample-name column last ---
        if active_tab == TAB_AUDIO:
            sample_name = seq.get_audio_track_name(seq.view_pattern, t)
            ch_tag = "◯◯" if seq.get_audio_track_channels(seq.view_pattern, t) >= 2 else "◯"
            sample_name_width = col_cell_width("audio_name")
            audio_col_gap = 1
            sample_field = f"{ch_tag} {sample_name}"[:sample_name_width].ljust(sample_name_width)
            preview_selected = audio_content_focus and cursor_x == PREVIEW_COL and cursor_y == row_idx
            safe_add(y, x, "▶", row_attr | (theme["selected"] if preview_selected else 0))
            x += 1 + audio_col_gap
            body_selected = audio_content_focus and cursor_x == 0 and cursor_y == row_idx
            body = f"[{sample_field}]" if body_selected else f" {sample_field} "
            attr = row_attr | (theme["selected"] if body_selected else 0)
            safe_add(y, x, body, attr, transform_case=False)
        elif active_tab == TAB_MIXER:
            seq_pan = seq.seq_track_pan[t]
            seq_vol = seq.seq_track_volume[t]
            seq_prob = seq.seq_track_probability[t]
            seq_pitch = seq.seq_track_pitch[t]
            aud_pan = seq.get_audio_track_pan(seq.view_pattern, t)
            aud_vol = seq.get_audio_track_volume(seq.view_pattern, t)
            safe_add(y, x, "  ", row_attr)
            x += 2

            mix_cells = [
                (0, f"P{seq_pan}", row_attr, 2),
                (1, f"V{seq_vol}", row_attr, 2),
                (2, f"P{seq_prob}", row_attr, 2),
                (3, f"{seq_pitch + 12}", row_attr, 2),
                (4, f"P{aud_pan}", row_attr, 2),
                (5, f"V{aud_vol}", row_attr, 2),
            ]
            for idx, text, base_attr, cell_w in mix_cells:
                if idx == 4:
                    safe_add(y, x, "     ", row_attr)
                    x += 5
                elif idx > 0:
                    safe_add(y, x, "  ", row_attr)
                    x += 2
                is_selected = mixer_content_focus and cursor_x == idx and cursor_y == row_idx
                cell_attr = base_attr | (theme["selected"] if is_selected else 0)
                safe_add(y, x, f"{text:>{cell_w}}", cell_attr)
                x += cell_w
        else:
            # --- Sequencer tab UI elements: preview + step grid + per-track params ---
            # Sequencer view: preview is shown next to the track label (before steps).
            preview_char = "▶" if t != ACCENT_TRACK else " "
            preview_attr = row_attr
            if sequencer_content_focus and cursor_x == PREVIEW_COL and cursor_y == t:
                preview_attr = preview_attr | theme["selected"]
            safe_add(y, x, f"{preview_char:>1}", preview_attr)
            x += 1 + seq_col_gap

            # Sequencer grid: compact 1-char step cells.
            for s in range(seq.max_step_count):
                val = seq.grid[seq.view_pattern][t][s]
                ratchet = seq.ratchet_grid[seq.view_pattern][t][s]
                detune = seq.detune_grid[seq.view_pattern][t][s]
                if (not show_steps_outside_pattern) and s >= seq.pattern_length[seq.view_pattern]:
                    cell_attr = theme["muted"]
                    if sequencer_content_focus and cursor_x == s and cursor_y == t:
                        cell_attr = cell_attr | theme["selected"]
                    safe_add(y, x, " ", cell_attr)
                    x += 1 + seq_col_gap
                    continue
                if edit_mode == "blocks":
                    char = block_on_char if val > 0 else "."
                elif edit_mode == "ratchet":
                    char = str(ratchet if val > 0 else ".")
                elif edit_mode == "detune":
                    char = str(detune) if val > 0 else "."
                elif edit_mode == "pan":
                    char = str(seq.pan_grid[seq.view_pattern][t][s]) if val > 0 else "."
                else:
                    char = str(val) if val > 0 else "."

                if t == ACCENT_TRACK:
                    if edit_mode == "blocks":
                        char = block_on_char if val > 0 else "."
                    else:
                        char = "1" if val > 0 else "."
                    cell_attr = theme["accent"]
                else:
                    cell_attr = velocity_attr(val)

                if s >= seq.pattern_length[seq.view_pattern]:
                    cell_attr = theme["muted"]
                elif val == 0 and (s % 4 == 0):
                    # Highlight each beat-start dot so the rhythm grid is easier to read.
                    cell_attr = theme["text"]
                if sequencer_content_focus and cursor_x == s and cursor_y == t:
                    cell_attr = cell_attr | theme["selected"]
                safe_add(y, x, char, cell_attr)
                x += 1 + seq_col_gap

    # --- Export tab inline content ---
    if active_tab == TAB_EXPORT:
        ex = area_work_content_x
        ey = area_work_top + 1
        safe_add(ey, ex, "Export Audio", theme["title"])
        ey += 2
        bit_depth = int(audio_export_options.get("bit_depth", 16))
        sample_rate = int(audio_export_options.get("sample_rate", seq.engine.sr))
        channels = int(audio_export_options.get("channels", 2))
        scope = str(audio_export_options.get("scope", "pattern")).strip().lower()

        def _draw_export_row(y, row_idx, label, options, selected_value):
            is_focused = export_content_focus and cursor_y == row_idx
            safe_add(y, ex, ">" if is_focused else " ", theme["text"])
            safe_add(y, ex + 2, label, theme["title"] if is_focused else theme["muted"])
            ox = ex + 2 + len(label)
            for text, value in options:
                attr = theme["text"] if value == selected_value else theme["muted"]
                safe_add(y, ox, text, attr)
                ox += len(text) + 2

        _draw_export_row(ey,     0, "Bit Depth:   ", [("8-bit ", 8), ("12-bit", 12), ("16-bit", 16)], bit_depth)
        _draw_export_row(ey + 1, 1, "Sample Rate: ", [("11k ", 11025), ("22k ", 22050), ("32k ", 32000), ("44.1k ", 44100), ("48k", 48000)], sample_rate)
        _draw_export_row(ey + 2, 2, "Channels:    ", [("Mono  ", 1), ("Stereo", 2)], channels)
        _draw_export_row(ey + 3, 3, "Export:      ", [("Pattern", "pattern"), ("Song   ", "chain")], scope)

        # Effects row — EQ and TAPE toggles
        eff_y = ey + 4
        is_eff = export_content_focus and cursor_y == 4
        safe_add(eff_y, ex, ">" if is_eff else " ", theme["text"])
        safe_add(eff_y, ex + 2, "Effects:     ", theme["title"] if is_eff else theme["muted"])
        eq_x = ex + 2 + len("Effects:     ")
        eq_attr = theme["accent"] if export_eq_enabled else theme["muted"]
        if is_eff and cursor_x == 0:
            eq_attr = eq_attr | theme["selected"]
        safe_add(eff_y, eq_x, "[EQ]", eq_attr)
        tape_x = eq_x + len("[EQ]") + 2
        tape_attr = theme["accent"] if export_tape_enabled else theme["muted"]
        if is_eff and cursor_x == 1:
            tape_attr = tape_attr | theme["selected"]
        safe_add(eff_y, tape_x, "[TAPE]", tape_attr)

        # Export action button
        btn_y = ey + 6
        is_btn = export_content_focus and cursor_y == 5
        btn_attr = theme["text"] | (theme["selected"] if is_btn else 0)
        safe_add(btn_y, ex + 4, "[ Export ]", btn_attr)

    prompt_line = ""
    help_line = ""

    def current_preview_name():
        """Return the current sample name for preview help text in Audio and Sequencer views."""
        if active_tab == TAB_AUDIO:
            if cursor_y < TRACKS - 1 and track_order:
                active_track = track_order[max(0, min(len(track_order) - 1, cursor_y))]
                return str(seq.get_audio_track_name(seq.view_pattern, active_track))
            return "-"
        if cursor_y < TRACKS - 1 and 0 <= cursor_y < len(seq.engine.sample_names):
            return str(seq.engine.sample_names[cursor_y])
        return "Accent track"
    if pattern_params_focus and active_tab == 0:
        pattern_nav_keys = ["name", "length", "swing", "humanize", "mode"]
        active_key = pattern_nav_keys[max(0, min(len(pattern_nav_keys) - 1, pattern_params_index))]
        if active_key == "name":
            help_line = texts.help.pattern_params.name
        elif active_key == "length":
            help_line = texts.help.pattern_params.length
        elif active_key == "swing":
            help_line = texts.help.pattern_params.swing
        elif active_key == "humanize":
            help_line = texts.pattern_humanize_help(getattr(seq, "humanize_amount", 50))
        else:
            help_line = texts.help.pattern_params.mode
    elif header_focus:
        if header_section == "tabs":
            help_line = texts.help.header.tabs
        elif header_param == "patterns":
            help_line = texts.help.header.patterns
        elif header_param == "bpm":
            help_line = texts.help.header.bpm
        elif header_param == "midi":
            help_line = texts.help.header.midi
        elif header_param == "file":
            help_line = texts.help.header.file
        elif header_param == "pattern":
            help_line = texts.help.header.pattern
        elif header_param == "song":
            help_line = texts.help.header.song
        elif header_param == "record":
            help_line = texts.help.header.record
        elif header_param == "chain_set":
            help_line = texts.help.header.chain_set
        else:
            help_line = texts.help.header.default
    elif active_tab == TAB_SONG and cursor_x == 0:
        help_line = texts.help.song[0]
    elif active_tab == TAB_SONG and cursor_x == 1:
        help_line = texts.help.song[1]
    elif active_tab == TAB_MIXER and cursor_x == 0:
        help_line = texts.help.mixer[0]
    elif active_tab == TAB_MIXER and cursor_x == 1:
        help_line = texts.help.mixer[1]
    elif active_tab == TAB_MIXER and cursor_x == 2:
        help_line = texts.help.mixer[2]
    elif active_tab == TAB_MIXER and cursor_x == 3:
        help_line = texts.help.mixer[3]
    elif active_tab == TAB_MIXER and cursor_x == 4:
        help_line = texts.help.mixer[4]
    elif active_tab == TAB_MIXER and cursor_x == 5:
        help_line = texts.help.mixer[5]
    elif active_tab == TAB_EXPORT and cursor_y == 0:
        help_line = texts.help.export[0]
    elif active_tab == TAB_EXPORT and cursor_y == 1:
        help_line = texts.help.export[1]
    elif active_tab == TAB_EXPORT and cursor_y == 2:
        help_line = texts.help.export[2]
    elif active_tab == TAB_EXPORT and cursor_y == 3:
        help_line = texts.help.export[3]
    elif active_tab == TAB_EXPORT and cursor_y == 4:
        help_line = texts.help.export[4]
    elif active_tab == TAB_EXPORT and cursor_y == 5:
        help_line = texts.help.export[5]
    elif active_tab == TAB_AUDIO and cursor_x == TRACK_LABEL_COL:
        help_line = texts.help.audio.track_settings
    elif active_tab == TAB_AUDIO and cursor_x == PREVIEW_COL:
        help_line = texts.preview_sample_help(current_preview_name())
    elif active_tab == TAB_AUDIO and cursor_x == 0:
        help_line = texts.help.audio.track_name
    elif active_tab == TAB_AUDIO and cursor_y < TRACKS - 1:
        active_track = track_order[max(0, min(len(track_order) - 1, cursor_y))]
        help_line = texts.audio_track_sample_help(seq.get_audio_track_name(seq.view_pattern, active_track))
    elif cursor_x == LOAD_COL:
        help_line = texts.help.audio.load_sample
    elif cursor_x == PREVIEW_COL:
        help_line = texts.preview_sample_help(current_preview_name())
    elif cursor_x == REC_COL:
        help_line = texts.help.audio.probability
    elif cursor_x == CLEAR_COL:
        help_line = texts.help.audio.mutegroup
    elif cursor_x == TRACK_PITCH_COL:
        help_line = texts.help.audio.track_pitch
    elif cursor_y < TRACKS - 1:
        help_line = texts.sample_help(seq.engine.sample_names[cursor_y])
    else:
        help_line = texts.help.audio.accent_sample

    if pattern_load_prompt:
        prompt_line = pattern_load_prompt
    elif status_message:
        prompt_line = f"{status_message} | {help_line}"
    else:
        prompt_line = help_line

    # Always use global text transformation setting for the final prompt line
    if prompt_line:
        prompt_col = 0
        safe_add(area_prompt, prompt_col, prompt_line[:max(0, w - 1)], theme["prompt"], transform_case=True)

    # Always-visible current sample label at bottom-right of sequencer area.
    # TODO: DELETE IF WANTED
    # if active_tab == 1 and cursor_y < TRACKS - 1 and track_order:
    #     active_track = track_order[max(0, min(len(track_order) - 1, cursor_y))]
    #     current_sample_name = seq.get_audio_track_name(seq.view_pattern, active_track)
    # elif cursor_y < TRACKS - 1:
    #     current_sample_name = seq.engine.sample_names[cursor_y]
    # else:
    #     current_sample_name = "Accent track"
    # sample_label = f"SAMPLE: {current_sample_name}"
    # sample_y = area_work_bottom - 1
    # sample_x = max(area_work_left + 2, area_work_right - len(sample_label) - 1)
    # safe_add(sample_y, sample_x, sample_label[: max(0, area_work_right - sample_x)], theme["muted"], transform_case=False)

    if pattern_menu_active:
        _prev_dim_background_active = _begin_modal_draw()
        if pattern_menu_kind == "pattern":
            items = PATTERN_MENU_ITEMS
        else:
            items = FILE_MENU_ITEMS
        max_item_len = max((len(item) for item in items), default=10)
        box_width = min(w - 4, max(24, max_item_len + 4))
        box_height = min(h - 2, len(items) + 2)
        anchor_x = top_menu_x.get(pattern_menu_kind, outer_left + 2)
        box_left = max(1, min(anchor_x, w - box_width - 1))
        box_top = outer_top + 1
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1

        draw_box(box_left, box_top, box_right, box_bottom, frame_attr)
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])
        for i, item in enumerate(items):
            item_attr = theme["text"]
            if i == pattern_menu_index:
                item_attr = item_attr | theme["selected"]
            safe_add(box_top + 1 + i, box_left + 2, item[: box_width - 4], item_attr)
            if pattern_menu_kind == "pattern" and i == 1:
                add_pos = item.find("Add")
                if add_pos >= 0:
                    safe_add(box_top + 1 + i, box_left + 2 + add_pos, "A", item_attr | curses.A_UNDERLINE)
            if pattern_menu_kind == "pattern" and i == 2:
                dup_pos = item.find("Duplicate")
                if dup_pos >= 0:
                    safe_add(box_top + 1 + i, box_left + 2 + dup_pos, "D", item_attr | curses.A_UNDERLINE)
            if pattern_menu_kind == "pattern" and i == 7:
                copy_pos = item.find("Copy")
                if copy_pos >= 0:
                    safe_add(box_top + 1 + i, box_left + 2 + copy_pos, "C", item_attr | curses.A_UNDERLINE)
            if pattern_menu_kind == "pattern" and i == 8:
                v_pos = item.find("(V)")
                if v_pos >= 0:
                    safe_add(box_top + 1 + i, box_left + 2 + v_pos + 1, "V", item_attr | curses.A_UNDERLINE)
            if pattern_menu_kind == "pattern" and i == 9:
                x_pos = item.find("(X)")
                if x_pos >= 0:
                    safe_add(box_top + 1 + i, box_left + 2 + x_pos + 1, "X", item_attr | curses.A_UNDERLINE)
        _end_modal_draw(_prev_dim_background_active)

    if patterns_overlay_active:
        _prev_dim_background_active = _begin_modal_draw()
        count = seq.pattern_count()
        title = texts.dialog["patterns"].title
        rows = []
        row_is_empty = []
        for i in range(count):
            view_tag = "VIEW" if i == seq.view_pattern else "    "
            if i == seq.pattern:
                play_tag = "▶"
            elif (not seq.chain_enabled) and seq.playing and seq.next_pattern == i:
                play_tag = "▶" if queue_flash_on else " "
            else:
                play_tag = " "
            hits = seq.pattern_note_count(i)
            length = seq.pattern_length[i]
            swing = seq.swing_internal_to_ui(seq.pattern_swing[i])
            is_empty = not seq.pattern_has_data(i)
            state = "EMPTY" if is_empty else "     "
            pat_name = str(seq.get_pattern_name(i) or "")[:18].ljust(18)
            rows.append(
                f"{i+1:>2}. {view_tag} {play_tag} {state} {pat_name} LEN:{length:>2} SW:{swing:>2} HITS:{hits:>3}"
            )
            row_is_empty.append(is_empty)
        if not rows:
            rows = [texts.labels.rows.no_patterns]
        list_height = min(14, max(6, h - 12))
        box_width = min(w - 8, 86)
        box_height = min(h - 4, list_height + 4)
        box_left = max(1, (w - box_width) // 2)
        box_top = max(1, (h - box_height) // 2)
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1
        draw_box(box_left, box_top, box_right, box_bottom, frame_attr)
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])
        safe_add(box_top + 1, box_left + 2, title[: box_width - 4], theme["text"])

        max_rows = box_height - 3
        start = 0
        if patterns_overlay_index >= max_rows:
            start = patterns_overlay_index - max_rows + 1
        end = min(len(rows), start + max_rows)
        for i in range(start, end):
            y = box_top + 2 + (i - start)
            attr = theme["muted"] if row_is_empty[i] else theme["text"]
            if i == patterns_overlay_index:
                attr = attr | theme["selected"]
            safe_add(y, box_left + 2, rows[i][: box_width - 4], attr, transform_case=False)
        _end_modal_draw(_prev_dim_background_active)

    if chop_overlay_active:
        _prev_dim_background_active = _begin_modal_draw()
        title = texts.dialog["import_chops"].title
        rows = []
        for i in range(8):
            name = "-"
            if i < len(seq.chop_preview_names):
                name = seq.chop_preview_names[i]
            rows.append(f"{i+1:>2}. ▶ {name}")
        rows.append(texts.labels.rows.use_samples)
        rows.append(texts.labels.rows.cancel)
        box_width = min(w - 8, 72)
        box_height = min(h - 4, 15)
        box_left = max(1, (w - box_width) // 2)
        box_top = max(1, (h - box_height) // 2)
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1
        draw_box(box_left, box_top, box_right, box_bottom, frame_attr)
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])
        safe_add(box_top + 1, box_left + 2, title[: box_width - 4], theme["text"])
        src = os.path.basename(seq.chop_preview_path) if seq.chop_preview_path else "-"
        safe_add(box_top + 2, box_left + 2, texts.source_label(src)[: box_width - 4], theme["muted"], transform_case=False)
        for i, row in enumerate(rows):
            y = box_top + 3 + i
            if y >= box_bottom:
                break
            attr = theme["text"]
            if i == chop_overlay_index:
                attr = attr | theme["selected"]
            safe_add(y, box_left + 2, row[: box_width - 4], attr)
        _end_modal_draw(_prev_dim_background_active)

    if import_overlay_active:
        _prev_dim_background_active = _begin_modal_draw()
        title = texts.dialog["import_audio"].title
        src = os.path.basename(import_overlay_path) if import_overlay_path else "-"
        audio_mode_label = "Song" if (0 <= import_target_audio_track < (TRACKS - 1) and seq.audio_track_mode[import_target_audio_track] == 1) else f"Pattern {seq.view_pattern + 1}"
        rows = [
            "Chop audio to 8 drum tracks",
            f"Import to single drum track: {import_target_drum_track + 1}",
            f"Import to audio track: {import_target_audio_track + 1} ({audio_mode_label})",
            texts.labels.rows.cancel,
        ]
        if import_overlay_can_delete_source:
            rows.append(texts.labels.rows.cancel_delete_recording)
        box_width = min(w - 8, 78)
        box_height = min(h - 4, 11 if import_overlay_can_delete_source else 10)
        box_left = max(1, (w - box_width) // 2)
        box_top = max(1, (h - box_height) // 2)
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1
        draw_box(box_left, box_top, box_right, box_bottom, frame_attr)
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])
        safe_add(box_top + 1, box_left + 2, title[: box_width - 4], theme["text"])
        safe_add(box_top + 2, box_left + 2, texts.source_label(src)[: box_width - 4], theme["muted"], transform_case=False)
        for i, row in enumerate(rows):
            y = box_top + 3 + i
            if y >= box_bottom:
                break
            attr = theme["text"]
            if i == import_overlay_index:
                attr = attr | theme["selected"]
            safe_add(y, box_left + 2, row[: box_width - 4], attr)
        _end_modal_draw(_prev_dim_background_active)

    if record_overlay_active:
        _prev_dim_background_active = _begin_modal_draw()
        title = texts.dialog["record_settings"].title
        devices = record_device_names if record_device_names else [texts.labels.rows.no_input_devices]
        selected_dev = devices[record_device_index] if devices else texts.labels.rows.no_input_devices
        box_width = min(w - 8, 78)
        box_height = min(h - 4, 12)
        record_anchor_x = top_menu_x.get("record", outer_left + 2)
        box_left = max(1, min(record_anchor_x, w - box_width - 1))
        box_top = outer_top + 1
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1
        draw_box(box_left, box_top, box_right, box_bottom, frame_attr)
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])
        safe_add(box_top + 1, box_left + 2, title[: box_width - 4], theme["text"])

        def draw_options_line(y, label, options, selected_value, selected_row):
            safe_add(y, box_left + 2, ">" if selected_row else " ", theme["text"])
            safe_add(y, box_left + 4, label, theme["text"])
            x = box_left + 4 + len(label)
            for text, value in options:
                selected = (value == selected_value)
                attr = theme["text"] if selected else theme["muted"]
                safe_add(y, x, text, attr)
                x += len(text) + 2

        draw_options_line(
            box_top + 3,
            "Channels: ",
            [("Mono", 1), ("Stereo", 2)],
            record_channels,
            record_overlay_index == 0,
        )
        safe_add(box_top + 4, box_left + 2, ">" if record_overlay_index == 1 else " ", theme["text"])
        safe_add(box_top + 4, box_left + 4, f"Input Device: {selected_dev}"[: box_width - 6], theme["text"])
        source_text = "Input Source: " + (record_input_sources[record_input_source_index]["label"] if record_input_sources and 0 <= record_input_source_index < len(record_input_sources) else "Default")
        safe_add(box_top + 5, box_left + 2, ">" if record_overlay_index == 2 else " ", theme["text"])
        safe_add(box_top + 5, box_left + 4, source_text[: box_width - 6], theme["text"], transform_case=False)
        draw_options_line(
            box_top + 6,
            "Precount: ",
            [("Off", 0), ("On", 1)],
            1 if record_precount_enabled else 0,
            record_overlay_index == 3,
        )
        draw_options_line(
            box_top + 7,
            "Precount pattern: ",
            [(str(i + 1), i) for i in range(max(1, min(16, seq.pattern_count())))],
            max(0, min(seq.pattern_count() - 1, int(record_precount_pattern))),
            record_overlay_index == 4,
        )

        if ui_options.get("record_input_metering_enabled", False):
            meter_y = box_bottom - 2
            meter_left = box_left + 2
            meter_width = max(10, box_width - 26)
            norm = max(0.0, min(1.0, (record_level_db + 60.0) / 60.0))
            fill = int(round(norm * meter_width))
            hot_start = max(0, int(round(meter_width * 0.82)))
            if record_monitor_running:
                db_text = f"{record_level_db:>5.1f} dBFS"
            else:
                db_text = "stopped"
            safe_add(meter_y, meter_left, "IN [", theme["hint"])
            meter_x = meter_left + 4
            if fill > 0:
                normal_fill = min(fill, hot_start)
                hot_fill = max(0, fill - hot_start)
                if normal_fill > 0:
                    safe_add(meter_y, meter_x, "█" * normal_fill, theme["meter_fill"])
                if hot_fill > 0:
                    safe_add(meter_y, meter_x + normal_fill, "█" * hot_fill, theme["meter_hot"])
            if fill < meter_width:
                safe_add(meter_y, meter_x + fill, "░" * (meter_width - fill), theme["muted"])
            safe_add(meter_y, meter_x + meter_width, "] ", theme["hint"])
            safe_add(meter_y, meter_x + meter_width + 2, db_text[: max(0, box_width - 4)], theme["hint"])
        btn_y = box_bottom - 1
        record_label = texts.labels.rows.stop if record_capture_active else texts.labels.rows.record
        action_row = (record_overlay_index == 5)
        cancel_attr = theme["text"] if (action_row and record_action_index == 0) else theme["muted"]
        record_attr = theme["record"] if (action_row and record_action_index == 1) else theme["muted"]
        safe_add(btn_y, box_left + 2, texts.labels.rows.cancel, cancel_attr)
        rec_x = box_right - len(record_label) - 2
        safe_add(btn_y, rec_x, record_label, record_attr)
        _end_modal_draw(_prev_dim_background_active)

    if file_browser_active:
        _prev_dim_background_active = _begin_modal_draw()
        title = texts.browser_title(file_browser_mode)
        visible_items = file_browser_items if file_browser_items else [{"name": texts.labels.rows.browser_empty, "is_dir": False, "is_parent": False}]
        list_height = min(14, max(6, h - 12))
        max_name = max(len(it["name"]) for it in visible_items)
        box_width = min(w - 6, max(52, max_name + 12))
        box_height = min(h - 4, list_height + 4)
        box_left = max(1, (w - box_width) // 2)
        box_top = max(1, (h - box_height) // 2)
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1

        draw_box(box_left, box_top, box_right, box_bottom, frame_attr)
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])

        safe_add(box_top + 1, box_left + 2, title[: box_width - 4], theme["text"])
        path_line = texts.path_label(file_browser_path)
        safe_add(box_top + 2, box_left + 2, path_line[: box_width - 4], theme["muted"], transform_case=False)

        max_rows = box_height - 4
        start = 0
        if file_browser_index >= max_rows:
            start = file_browser_index - max_rows + 1
        end = min(len(visible_items), start + max_rows)

        for i in range(start, end):
            row = box_top + 3 + (i - start)
            label = visible_items[i]["name"]
            item_attr = theme["text"]
            if i == file_browser_index and file_browser_items:
                item_attr = item_attr | theme["selected"]
            safe_add(row, box_left + 2, label[: box_width - 4], item_attr, transform_case=False)
        _end_modal_draw(_prev_dim_background_active)

    if audio_export_options_active:
        _prev_dim_background_active = _begin_modal_draw()
        title = texts.dialog["audio_export_options"].title
        bit_depth = int(audio_export_options.get("bit_depth", 16))
        sample_rate = int(audio_export_options.get("sample_rate", seq.engine.sr))
        channels = int(audio_export_options.get("channels", 2))
        scope = str(audio_export_options.get("scope", "pattern")).strip().lower()
        if scope not in ["pattern", "chain"]:
            scope = "pattern"
        row_count = 5
        box_width = min(w - 8, 72)
        box_height = 11
        box_left = max(1, (w - box_width) // 2)
        box_top = max(1, (h - box_height) // 2)
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1
        draw_box(box_left, box_top, box_right, box_bottom, frame_attr)
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])
        safe_add(box_top + 1, box_left + 2, title[: box_width - 4], theme["text"])
        safe_add(box_top + 2, box_left + 2, texts.labels.hints.use_arrows, theme["muted"])

        def draw_options_line(y, label, options, selected_value, selected_row):
            safe_add(y, box_left + 2, ">" if selected_row else " ", theme["text"])
            safe_add(y, box_left + 4, label, theme["text"])
            x = box_left + 4 + len(label)
            for option_text, option_value in options:
                attr = theme["text"] if option_value == selected_value else theme["muted"]
                safe_add(y, x, option_text, attr)
                x += len(option_text)

        draw_options_line(
            box_top + 4,
            "Bit Depth: ",
            [('8-bit  ', 8), ('12-bit', 12), ('16-bit', 16)],
            bit_depth,
            audio_export_options_index == 0,
        )
        draw_options_line(
            box_top + 5,
            "Sample Rate: ",
            [("11k  ", 11025), ("22k  ", 22050), ("32k  ", 32000), ("44.1k  ", 44100), ("48k", 48000)],
            sample_rate,
            audio_export_options_index == 1,
        )
        draw_options_line(
            box_top + 6,
            "Channels: ",
            [("Mono  ", 1), ("Stereo", 2)],
            channels,
            audio_export_options_index == 2,
        )
        draw_options_line(
            box_top + 7,
            "Export: ",
            [("Current Pattern  ", "pattern"), ("Whole Song", "chain")],
            scope,
            audio_export_options_index == 3,
        )
        export_attr = theme["text"] | (theme["selected"] if audio_export_options_index == (row_count - 1) else 0)
        safe_add(box_top + 8, box_left + 4, texts.labels.rows.export_audio, export_attr)
        _end_modal_draw(_prev_dim_background_active)

    if kit_export_options_active:
        _prev_dim_background_active = _begin_modal_draw()
        title = texts.dialog["kit_export_options"].title
        bit_depth = int(kit_export_options.get("bit_depth", 16))
        sample_rate = int(kit_export_options.get("sample_rate", seq.engine.sr))
        channels = int(kit_export_options.get("channels", 1))
        row_count = 4
        box_width = min(w - 8, 72)
        box_height = 10
        box_left = max(1, (w - box_width) // 2)
        box_top = max(1, (h - box_height) // 2)
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1
        draw_box(box_left, box_top, box_right, box_bottom, theme["frame"])
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])
        safe_add(box_top + 1, box_left + 2, title[: box_width - 4], theme["text"])
        safe_add(box_top + 2, box_left + 2, texts.labels.hints.use_arrows, theme["muted"])

        def draw_kit_options_line(y, label, options, selected_value, selected_row):
            safe_add(y, box_left + 2, ">" if selected_row else " ", theme["text"])
            safe_add(y, box_left + 4, label, theme["text"])
            x = box_left + 4 + len(label)
            for text, value in options:
                selected = (value == selected_value)
                attr = theme["text"] if selected else theme["muted"]
                if selected_row and selected:
                    attr = attr | theme["selected"]
                safe_add(y, x, text, attr)
                x += len(text) + 2

        draw_kit_options_line(
            box_top + 4,
            "Bit depth: ",
            [('8-bit', 8), ('12-bit', 12), ('16-bit', 16)],
            bit_depth,
            kit_export_options_index == 0,
        )
        draw_kit_options_line(
            box_top + 5,
            "Sample rate: ",
            [("11025", 11025), ("22050", 22050), ("44100", 44100), ("48000", 48000)],
            sample_rate,
            kit_export_options_index == 1,
        )
        draw_kit_options_line(
            box_top + 6,
            "Channels: ",
            [("Mono  ", 1), ("Stereo", 2)],
            channels,
            kit_export_options_index == 2,
        )
        export_attr = theme["text"] | (theme["selected"] if kit_export_options_index == (row_count - 1) else 0)
        safe_add(box_top + 7, box_left + 4, texts.labels.rows.export_kit, export_attr)
        _end_modal_draw(_prev_dim_background_active)

    # Footer row sits above area_prompt.
    footer_row = outer_bottom
    transport_icon = "▶" if seq.playing else "▢"
    transport_attr = frame_attr
    safe_add(footer_row, outer_left + 2, transport_icon, transport_attr)
    compact_pattern_line = " ".join(pattern_line.split())
    footer_patterns = f"PATTERNS {compact_pattern_line}"
    footer_song = f"SONG {song_line}"
    footer_x = outer_left + 6
    max_w = max(0, outer_right - (outer_left + 8))
    patterns_attr = theme["tertiary_on"] if not seq.chain_enabled else theme["tertiary_off"]
    song_attr = theme["tertiary_on"] if seq.chain_enabled else theme["tertiary_off"]
    safe_add(footer_row, footer_x, footer_patterns[:max_w], patterns_attr)
    footer_x += len(footer_patterns)
    safe_add(footer_row, footer_x, "   "[:max(0, max_w - len(footer_patterns))], frame_attr)
    footer_x += 3
    safe_add(footer_row, footer_x, footer_song[:max(0, max_w - (len(footer_patterns) + 3))], song_attr)
    project_dir = os.path.basename(os.path.dirname(seq.pattern_path)) if seq.pattern_path else ""
    if not project_dir:
        project_dir = "."
    project_label = f" {project_dir} "
    project_x = max(outer_left + 2, outer_right - len(project_label) - 2)
    safe_add(footer_row, project_x, project_label, theme["muted"])


    # Track params dialog
    if track_params_dialog_active:
        _prev_dim_background_active = _begin_modal_draw()
        title = texts.dialog["track_parameters"].title
        if track_params_dialog_track == ACCENT_TRACK:
            track_name = "Accent"
        else:
            sample_name = "-"
            if 0 <= track_params_dialog_track < len(seq.engine.sample_names):
                sample_name = str(seq.engine.sample_names[track_params_dialog_track] or "-")
            track_name = f"Track {track_params_dialog_track + 1}: {sample_name}"
        params = [
            ("Pan (1-9)", str(seq.seq_track_pan[track_params_dialog_track])),
            ("Volume (0-9)", str(seq.seq_track_volume[track_params_dialog_track])),
            ("Probability (0-9)", str(seq.seq_track_probability[track_params_dialog_track])),
            ("Group (0-9)", str(seq.seq_track_group[track_params_dialog_track])),
            ("Pitch (0-24)", str(seq.seq_track_pitch[track_params_dialog_track] + 12)),
            ("Shift (0-9)", str(seq.seq_track_shift[track_params_dialog_track])),
            ("Load Sample", "Press Enter"),
        ]
        box_width = min(w - 8, max(50, len(track_name) + 6))
        box_height = min(h - 4, 14)
        box_left = max(1, (w - box_width) // 2)
        box_top = max(1, (h - box_height) // 2)
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1
        draw_box(box_left, box_top, box_right, box_bottom, frame_attr)
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])
        safe_add(box_top + 1, box_left + 2, title[: box_width - 4], theme["text"])
        safe_add(box_top + 2, box_left + 2, track_name[: box_width - 4], theme["muted"], transform_case=False)
        for i, (param_label, current_value) in enumerate(params):
            y = box_top + 3 + i
            if y >= box_bottom:
                break
            attr = theme["text"]
            if i == track_params_dialog_index:
                attr = attr | theme["selected"]
            line = f"{param_label}: {current_value}"
            safe_add(y, box_left + 2, line[: box_width - 4], attr)
        _end_modal_draw(_prev_dim_background_active)

    if audio_track_params_dialog_active:
        _prev_dim_background_active = _begin_modal_draw()
        title = texts.dialog["audio_track_settings"].title
        track_name = f"Track {audio_track_params_dialog_track + 1}: {seq.get_audio_track_name(seq.view_pattern, audio_track_params_dialog_track)}"
        mode_text = seq.get_audio_track_mode(audio_track_params_dialog_track)
        params = [
            ("Mode", mode_text),
            ("Rename", str(seq.get_audio_track_name(seq.view_pattern, audio_track_params_dialog_track))),
            ("Pan (1-9)", str(seq.get_audio_track_pan(seq.view_pattern, audio_track_params_dialog_track))),
            ("Volume (0-9)", str(seq.get_audio_track_volume(seq.view_pattern, audio_track_params_dialog_track))),
            ("Timeshift (0-50)", str(seq.get_audio_track_shift(seq.view_pattern, audio_track_params_dialog_track))),
            ("Clear Sample", "Enter"),
        ]
        box_width = min(w - 8, max(58, len(track_name) + 6))
        box_height = min(h - 4, 13)
        box_left = max(1, (w - box_width) // 2)
        box_top = max(1, (h - box_height) // 2)
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1
        draw_box(box_left, box_top, box_right, box_bottom, frame_attr)
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])
        safe_add(box_top + 1, box_left + 2, title[: box_width - 4], theme["text"])
        safe_add(box_top + 2, box_left + 2, track_name[: box_width - 4], theme["muted"], transform_case=False)
        for i, (param_label, current_value) in enumerate(params):
            y = box_top + 3 + i
            if y >= box_bottom:
                break
            attr = theme["text"]
            if i == audio_track_params_dialog_index:
                attr = attr | theme["selected"]
            line = f"{param_label}: {current_value}"
            safe_add(y, box_left + 2, line[: box_width - 4], attr, transform_case=False)
        _end_modal_draw(_prev_dim_background_active)

    if text_input_dialog_active:
        _prev_dim_background_active = _begin_modal_draw()
        title = texts.dialog["text_input"].title
        message = (text_input_dialog_message or "").strip()
        input_text = str(text_input_dialog_input or "")
        box_width = min(w - 8, max(52, len(message) + 6 if message else 52))
        box_height = min(h - 4, 9)
        box_left = max(1, (w - box_width) // 2)
        box_top = max(1, (h - box_height) // 2)
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1
        input_width = max(12, box_width - 8)
        draw_box(box_left, box_top, box_right, box_bottom, frame_attr)
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])
        safe_add(box_top + 1, box_left + 2, title[: box_width - 4], theme["text"])
        safe_add(box_top + 2, box_left + 2, (message or texts.dialog["text_input"].description)[: box_width - 4], theme["muted"], transform_case=False)
        safe_add(box_top + 4, box_left + 3, (input_text[:input_width]).ljust(input_width), theme["text"] | curses.A_UNDERLINE, transform_case=False)

        cancel_attr = theme["text"] | (theme["selected"] if text_input_dialog_index == 0 else 0)
        ok_attr = theme["text"] | (theme["selected"] if text_input_dialog_index == 1 else 0)
        safe_add(box_bottom - 2, box_left + 6, f"[ {texts.labels.actions.cancel} ]", cancel_attr)
        safe_add(box_bottom - 2, box_right - 10, f"[ {texts.labels.actions.ok} ]", ok_attr)
        _end_modal_draw(_prev_dim_background_active)

    if confirm_dialog_active:
        _prev_dim_background_active = _begin_modal_draw()
        title = texts.dialog["confirm"].title
        message = (confirm_dialog_message or "").strip()
        box_width = min(w - 8, max(46, len(message) + 6 if message else 46))
        box_height = min(h - 4, 8)
        box_left = max(1, (w - box_width) // 2)
        box_top = max(1, (h - box_height) // 2)
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1
        draw_box(box_left, box_top, box_right, box_bottom, frame_attr)
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])
        safe_add(box_top + 1, box_left + 2, title[: box_width - 4], theme["text"])
        safe_add(box_top + 2, box_left + 2, (message or texts.dialog["confirm"].description)[: box_width - 4], theme["muted"], transform_case=False)

        no_attr = theme["text"] | (theme["selected"] if confirm_dialog_index == 0 else 0)
        yes_attr = theme["text"] | (theme["selected"] if confirm_dialog_index == 1 else 0)
        safe_add(box_bottom - 2, box_left + 6, f"[ {texts.labels.actions.no} ]", no_attr)
        safe_add(box_bottom - 2, box_right - 12, f"[ {texts.labels.actions.yes} ]", yes_attr)
        _end_modal_draw(_prev_dim_background_active)

    stdscr.refresh()

# ---------- CONTROLLER ----------
class Controller:
    """Owns transient UI/dialog state and translates key input into actions."""
    def __init__(self, sequencer, keymap, export_settings=None):
        self.seq = sequencer
        self.keymap = keymap
        self.export_settings = export_settings or {}
        self.nav = NavigationModel()
        self.record_input_metering_enabled = False
        self.sort_audio_tracks_by_type_enabled = True
        self.export_eq_enabled = False
        self.export_tape_enabled = False
        self.cursor_x = 0
        self.cursor_y = 0
        self.edit_mode = "blocks"
        self.audio_export_options_active = False
        self.audio_export_options = {
            "bit_depth": 16,
            "sample_rate": self.seq.engine.sr,
            "channels": 2,
            "scope": "pattern",
        }
        self.audio_export_options_index = 0
        self.kit_export_options_active = False
        self.kit_export_options = {
            "bit_depth": 16,
            "sample_rate": self.seq.engine.sr,
            "channels": 1,
        }
        self.kit_export_options_index = 0
        self.track_params_dialog_active = False
        self.track_params_dialog_track = 0
        self.track_params_dialog_index = 0
        self.track_params_dialog_input = ""
        self.audio_track_params_dialog_active = False
        self.audio_track_params_dialog_track = 0
        self.audio_track_params_dialog_index = 0
        self.pattern_menu_active = False
        self.pattern_menu_kind = "file"
        self.pattern_menu_index = 0
        self.file_browser_active = False
        self.file_browser_mode = None
        self.file_browser_target_track = None
        self.file_browser_path = os.getcwd()
        self.file_browser_items = []
        self.file_browser_index = 0
        self.tap_tempo_times = []
        self.inline_value_buffer = ""
        self.inline_value_target = None  # (row, col)
        self.inline_value_time = 0.0
        self.patterns_overlay_active = False
        self.patterns_overlay_index = 0
        self.import_overlay_active = False
        self.import_overlay_index = 0
        self.import_overlay_path = None
        self.import_overlay_can_delete_source = False
        self.import_target_drum_track = 0
        self.import_target_audio_track = 0
        self.chop_overlay_active = False
        self.chop_overlay_index = 0
        self.drop_path_active = False
        self.drop_path_input = ""
        self.drop_path_last_input_time = 0.0
        self.record_overlay_active = False
        self.record_device_names = []
        self.record_device_ids = []
        self.record_device_sample_rates = []
        self.record_device_channels = []
        self.record_device_index = 0
        self.record_input_sources = []
        self.record_input_source_index = 0
        self.record_overlay_index = 0
        self.record_action_index = 1
        self.record_channels = 1
        self.record_precount_enabled = True
        self.record_precount_pattern = 0
        self.record_level_db = -60.0
        self.record_level_peak_db = -60.0
        self.record_monitor_running = False
        self._record_monitor_stream = None
        self.record_monitor_info = ""
        self._record_stream = None
        self.record_capture_active = False
        self.record_capture_stage = "idle"
        self.record_capture_pattern = 0
        self.record_capture_scope = "pattern"
        self.record_capture_phase_start = 0.0
        self.record_capture_precount_seconds = 0.0
        self.record_capture_take_seconds = 0.0
        self.record_capture_precount_loops = 0
        self.record_capture_take_loops = 1
        self.record_capture_loop_count = 0
        self.record_capture_context_track = None
        self.record_capture_context_audio = False
        self.record_capture_track = 0
        self.record_capture_last_step = 0
        self.record_capture_chunks = []
        self.record_capture_sr = 0
        self.record_level_tick = 0
        self.record_capture_input_indices = [0]
        self.record_capture_channels = 1
        self.record_stream_blocksize = 2048
        self.record_capture_buffer = None
        self.record_capture_write = 0
        self.record_capture_capacity = 0
        self.record_capture_duration_seconds = 0.0
        self.record_capture_started_at = 0.0
        self.record_capture_trim_seconds = 0.0
        self.record_capture_controls_transport = True
        self.record_capture_end_time = 0.0
        self.record_use_external_capture = False
        self.record_capture_started_playback = False
        self.text_input_dialog_active = False
        self.text_input_dialog_message = ""
        self.text_input_dialog_input = ""
        self.text_input_dialog_index = 1  # 0=Cancel, 1=OK
        self.text_input_dialog_action = None
        self.text_input_dialog_max_length = 120
        self.confirm_dialog_active = False
        self.confirm_dialog_message = ""
        self.confirm_dialog_index = 0  # 0=No, 1=Yes
        self.confirm_dialog_action = None
        self.status_message = ""
        self.pattern_actions = [f"pattern_{i+1}" for i in range(PATTERNS)]

    def _close_inline_text_prompts(self):
        """Close legacy prompt-line text entry states."""
        pass

    def _open_text_input_dialog(self, message, action, initial_input="", max_length=120):
        """Open centered generic text input dialog with Cancel/OK buttons."""
        self._close_inline_text_prompts()
        self.text_input_dialog_active = True
        self.text_input_dialog_message = str(message or "")
        self.text_input_dialog_input = str(initial_input or "")
        self.text_input_dialog_index = 1
        self.text_input_dialog_action = action
        self.text_input_dialog_max_length = max(1, int(max_length))

    def _close_text_input_dialog(self):
        self.text_input_dialog_active = False
        self.text_input_dialog_message = ""
        self.text_input_dialog_input = ""
        self.text_input_dialog_index = 1
        self.text_input_dialog_action = None
        self.text_input_dialog_max_length = 120

    def _open_confirm_dialog(self, message, action):
        """Open centered generic confirm dialog with No/Yes buttons."""
        self.confirm_dialog_active = True
        self.confirm_dialog_message = str(message or "")
        self.confirm_dialog_index = 0
        self.confirm_dialog_action = action

    def _close_confirm_dialog(self):
        self.confirm_dialog_active = False
        self.confirm_dialog_message = ""
        self.confirm_dialog_index = 0
        self.confirm_dialog_action = None

    def _confirm_quit_action(self):
        return "EXIT_APP"

    def move_cursor(self, dx, dy):
        nav = self._sequencer_nav_cols()
        if self.cursor_x in nav:
            idx = (nav.index(self.cursor_x) + dx) % len(nav)
            self.cursor_x = nav[idx]
        self.cursor_y = (self.cursor_y + dy) % TRACKS

    def _sequencer_nav_cols(self):
        """Sequencer navigation order matching visual layout (track, preview, steps)."""
        return [TRACK_LABEL_COL, PREVIEW_COL] + list(range(self.seq.max_step_count))

    def _audio_nav_cols(self):
        """Audio tab navigation order matching visual layout."""
        return [TRACK_LABEL_COL, PREVIEW_COL, 0]

    def _song_nav_row_count(self, column=None):
        """Return visible row count for the Song tab column."""
        col = self.cursor_x if column is None else int(column)
        if col == 1:
            return max(1, len(self.seq.chain))
        return max(1, self.seq.pattern_count())

    def _clamp_song_cursor(self):
        """Clamp Song-tab cursor to the active column and available rows."""
        self.cursor_x = 0 if int(self.cursor_x) <= 0 else 1
        self.cursor_y = max(0, min(self._song_nav_row_count() - 1, int(self.cursor_y)))

    def _sequencer_beat_cols(self):
        """Return beat-start step columns for current visible pattern length."""
        try:
            current_len = int(self.seq.pattern_length[self.seq.view_pattern])
        except Exception:
            current_len = self.seq.max_step_count
        step_span = max(1, min(self.seq.max_step_count, current_len))
        cols = list(range(0, step_span, 4))
        return cols if cols else [0]

    def _cycle_edit_mode(self):
        """Rotate sequencer edit mode through all available step views."""
        modes = ["velocity", "ratchet", "blocks", "detune", "pan"]
        try:
            idx = modes.index(self.edit_mode)
        except ValueError:
            idx = 0
        self.edit_mode = modes[(idx + 1) % len(modes)]

    def _pattern_param_keys(self):
        """Ordered keys for work-area pattern parameter navigation."""
        return list(self.nav.pattern.items)

    def _pattern_param_current(self):
        return self.nav.pattern.current_item()

    def _clear_pattern_param_input(self):
        self.nav.pattern.clear_input()

    def _focus_header_nav(self, section="params", edit_active=False):
        self.nav.focus_header(section=section, edit_active=edit_active)

    def _focus_pattern_params(self, index=0, edit_active=False):
        self.nav.focus_pattern(index=index, edit_active=edit_active)

    def _leave_pattern_params_to_grid(self):
        self.nav.leave_pattern_to_grid()
        self.cursor_y = 0

    def _apply_pattern_param_input(self):
        """Apply numeric input buffer to focused Steps/Swing control immediately."""
        key = self._pattern_param_current()
        text = (self.nav.pattern.input_buffer or "").strip()
        if key not in ["length", "swing"] or not text:
            return
        try:
            value = int(text)
        except ValueError:
            return

        if key == "length":
            target = max(1, min(self.seq.max_step_count, value))
            current = int(self.seq.pattern_length[self.seq.view_pattern])
            delta = target - current
            if delta != 0:
                self.seq.change_current_pattern_length(delta)
            self.status_message = texts.fmt(texts.status.pattern.steps, value=target)
        elif key == "swing":
            target = max(0, min(10, value))
            self.seq.set_current_pattern_swing_ui(target)
            self.status_message = texts.fmt(texts.status.pattern.swing, value=target)

    def _adjust_pattern_param(self, delta):
        """Apply +/- adjustment to the currently focused work-area pattern parameter."""
        self._clear_pattern_param_input()
        key = self._pattern_param_current()
        if key == "name":
            return
        if key == "length":
            self.seq.change_current_pattern_length(delta)
        elif key == "swing":
            self.seq.change_current_pattern_swing(delta)
        elif key == "humanize":
            self.seq.toggle_current_pattern_humanize()
            state = "ON" if self.seq.current_pattern_humanize_enabled() else "OFF"
            self.status_message = texts.fmt(texts.status.pattern.humanize, state=state)
        elif key == "mode":
            if delta > 0:
                self._cycle_edit_mode()
            elif delta < 0:
                # Reverse cycle for left/back edits.
                modes = ["velocity", "ratchet", "blocks", "detune", "pan"]
                try:
                    idx = modes.index(self.edit_mode)
                except ValueError:
                    idx = 0
                self.edit_mode = modes[(idx - 1) % len(modes)]

    def _set_active_tab(self, tab_index):
        """Switch active top tab and clamp cursor for that view."""
        self.nav.active_tab = int(tab_index)
        self.nav.clamp()
        if self.nav.active_tab != TAB_SEQUENCER:
            self.nav.pattern.blur()
            self._clear_pattern_param_input()
        if self.nav.active_tab == TAB_SEQUENCER and self.cursor_x == AUDIO_VOLUME_COL:
            self.cursor_x = REC_COL
        if self.nav.active_tab == TAB_SONG:
            self.cursor_x = 0 if self.cursor_x not in [0, 1] else self.cursor_x
            self._clamp_song_cursor()
        if self.nav.active_tab in [TAB_AUDIO, TAB_MIXER]:
            self.cursor_y = min(self.cursor_y, TRACKS - 2)
        if self.nav.active_tab == TAB_AUDIO and self.cursor_x not in [TRACK_LABEL_COL, PREVIEW_COL, 0]:
            self.cursor_x = TRACK_LABEL_COL
        if self.nav.active_tab == TAB_MIXER and self.cursor_x > 5:
            self.cursor_x = 0
        if self.nav.active_tab == TAB_EXPORT:
            self.cursor_y = max(0, min(5, self.cursor_y))
            self.cursor_x = 0

    def _export_tab_change(self, direction):
        """Change the focused export option value left/right, or cycle EQ/TAPE cursor."""
        opts = self.audio_export_options
        row = self.cursor_y
        if row == 0:
            bit_depths = [8, 12, 16]
            cur = int(opts.get("bit_depth", 16))
            try:
                idx = bit_depths.index(cur)
            except ValueError:
                idx = 1
            opts["bit_depth"] = bit_depths[(idx + direction) % len(bit_depths)]
        elif row == 1:
            rates = [11025, 22050, 32000, 44100, 48000]
            cur = int(opts.get("sample_rate", 44100))
            try:
                idx = rates.index(cur)
            except ValueError:
                idx = 3
            opts["sample_rate"] = rates[(idx + direction) % len(rates)]
        elif row == 2:
            chans = [1, 2]
            cur = int(opts.get("channels", 2))
            try:
                idx = chans.index(cur)
            except ValueError:
                idx = 1
            opts["channels"] = chans[(idx + direction) % len(chans)]
        elif row == 3:
            scopes = ["pattern", "chain"]
            cur = str(opts.get("scope", "pattern")).strip().lower()
            try:
                idx = scopes.index(cur)
            except ValueError:
                idx = 0
            opts["scope"] = scopes[(idx + direction) % len(scopes)]
        elif row == 4:
            self.cursor_x = max(0, min(1, self.cursor_x + direction))

    def _tracks_order(self):
        """Return display order for Audio view (Pattern lanes first, Song lanes after)."""
        if not getattr(self, "sort_audio_tracks_by_type_enabled", True):
            return [t for t in range(TRACKS - 1)]
        pattern_rows = [t for t in range(TRACKS - 1) if self.seq.audio_track_mode[t] == 0]
        song_rows = [t for t in range(TRACKS - 1) if self.seq.audio_track_mode[t] == 1]
        return pattern_rows + song_rows

    def _track_for_row(self, row):
        """Map current Audio-view row index to real track index."""
        order = self._tracks_order()
        if not order:
            return 0
        idx = max(0, min(len(order) - 1, int(row)))
        return order[idx]

    def _row_for_track(self, track):
        """Map real track index back to current Audio-view row index."""
        order = self._tracks_order()
        if not order:
            return 0
        try:
            return order.index(track)
        except ValueError:
            return 0

    def _apply_inline_track_value(self, col, digit):
        """Apply inline numeric typing for track parameter columns without Enter."""
        if self.cursor_y == ACCENT_TRACK:
            self.status_message = texts.status.generic.accent_no_parameter_here
            return

        now = time.time()
        target = (self.cursor_y, col)
        if self.inline_value_target != target or (now - self.inline_value_time) > 1.0:
            self.inline_value_buffer = ""

        self.inline_value_target = target
        self.inline_value_time = now
        self.inline_value_buffer = (self.inline_value_buffer + str(digit))[-3:]

        try:
            value = int(self.inline_value_buffer)
        except ValueError:
            value = digit
        if col == REC_COL:
            value = max(0, min(100, value))
            self.seq.set_track_probability(self.cursor_y, value)
        elif col == TRACK_PITCH_COL:
            value = max(0, min(24, value))
            self.seq.set_track_pitch_ui(self.cursor_y, value)

    def _apply_inline_audio_track_value(self, col, digit):
        """Apply inline numeric typing for Audio-view parameter columns."""
        track_idx = self._track_for_row(self.cursor_y)
        now = time.time()
        target = (self.cursor_y, col)
        if self.inline_value_target != target or (now - self.inline_value_time) > 1.0:
            self.inline_value_buffer = ""

        self.inline_value_target = target
        self.inline_value_time = now
        self.inline_value_buffer = (self.inline_value_buffer + str(digit))[-3:]

        try:
            value = int(self.inline_value_buffer)
        except ValueError:
            value = digit

        if col == AUDIO_VOLUME_COL:
            self.seq.set_audio_track_volume(self.seq.view_pattern, track_idx, max(0, min(9, value)))
        elif col == TRACK_PITCH_COL:
            self.seq.set_audio_track_shift(self.seq.view_pattern, track_idx, max(0, min(50, value)))

    def _close_audio_export_options_dialog(self):
        self.audio_export_options_active = False

    def _close_kit_export_options_dialog(self):
        self.kit_export_options_active = False

    def _close_track_params_dialog(self):
        self.track_params_dialog_active = False
        self.track_params_dialog_track = 0
        self.track_params_dialog_index = 0
        self.track_params_dialog_input = ""

    def _close_audio_track_params_dialog(self):
        self.audio_track_params_dialog_active = False
        self.audio_track_params_dialog_track = 0
        self.audio_track_params_dialog_index = 0

    def _track_params_dialog_track_label(self, track=None):
        """Return track label for track-parameter dialog, including sample filename."""
        idx = int(self.track_params_dialog_track if track is None else track)
        if idx == ACCENT_TRACK:
            return "Accent"
        sample_name = "-"
        if 0 <= idx < len(self.seq.engine.sample_names):
            sample_name = str(self.seq.engine.sample_names[idx] or "-")
        return f"Track {idx + 1}: {sample_name}"

    def _track_params_dialog_current_value(self, track, index):
        if index == 0:
            return str(self.seq.seq_track_pan[track])
        if index == 1:
            return str(self.seq.seq_track_volume[track])
        if index == 2:
            return str(self.seq.seq_track_probability[track])
        if index == 3:
            return str(self.seq.seq_track_group[track])
        if index == 4:
            return str(self.seq.seq_track_pitch[track] + 12)
        if index == 5:
            return str(self.seq.seq_track_shift[track])
        return ""

    def _apply_track_param_value_text(self, track, index, text):
        """Parse and apply one numeric track parameter from text input dialog."""
        try:
            value = int((text or "").strip())
        except ValueError:
            self.status_message = texts.status.generic.enter_numeric_value
            return False

        if index == 0:
            value = max(1, min(9, value))
            self.seq.set_track_pan(track, value)
            self.status_message = texts.fmt(texts.status.track.pan, track_num=track + 1, value=value)
        elif index == 1:
            value = max(0, min(9, value))
            self.seq.set_track_volume(track, value)
            self.status_message = texts.fmt(texts.status.track.volume, track_num=track + 1, value=value)
        elif index == 2:
            value = max(0, min(9, value))
            self.seq.set_track_probability(track, value)
            self.status_message = texts.fmt(texts.status.track.probability, track_num=track + 1, value=value)
        elif index == 3:
            value = max(0, min(9, value))
            self.seq.set_track_group(track, value)
            self.status_message = texts.fmt(texts.status.track.group, track_num=track + 1, value=value)
        elif index == 4:
            value = max(0, min(24, value))
            self.seq.set_track_pitch_ui(track, value)
            self.status_message = texts.fmt(texts.status.track.pitch, track_num=track + 1, value=value)
        elif index == 5:
            value = max(0, min(9, value))
            self.seq.set_track_shift(track, value)
            shift_ms = self.seq.seq_shift_ui_to_ms(value)
            self.status_message = texts.fmt(texts.status.track.shift, track_num=track + 1, value=value, shift_ms=shift_ms)
        else:
            return False
        return True

    def _apply_track_params_dialog(self, initial_input_override=None):
        """Open value-entry dialog for selected track parameter or browse sample."""
        track = int(self.track_params_dialog_track)
        if track == ACCENT_TRACK:
            self.status_message = texts.status.generic.accent_no_track_parameters
            return

        # Index 6 is Load Sample, which opens file browser (no value input needed)
        if self.track_params_dialog_index == 6:
            self._open_file_browser("sample", target_track=track)
            self._close_track_params_dialog()
            return

        idx = int(self.track_params_dialog_index)
        prompt = f"{self._track_params_dialog_track_label(track)} {texts.prompt.track_params.names[idx]}"
        initial_value = (
            str(initial_input_override)
            if initial_input_override is not None
            else self._track_params_dialog_current_value(track, idx)
        )

        def _do_apply(text):
            return self._apply_track_param_value_text(track, idx, text)

        max_len = 2 if idx == 4 else 1
        self._open_text_input_dialog(prompt, _do_apply, initial_input=initial_value, max_length=max_len)

    def _audio_track_params_dialog_track_label(self, track=None):
        idx = int(self.audio_track_params_dialog_track if track is None else track)
        if idx < 0 or idx >= (TRACKS - 1):
            return "Track -"
        name = self.seq.get_audio_track_name(self.seq.view_pattern, idx)
        mode = self.seq.get_audio_track_mode(idx)
        return f"Track {idx + 1}: {name} ({mode})"

    def _audio_track_params_dialog_current_value(self, track, index):
        if index == 0:
            return self.seq.get_audio_track_mode(track)
        if index == 1:
            return str(self.seq.get_audio_track_name(self.seq.view_pattern, track))
        if index == 2:
            return str(self.seq.get_audio_track_pan(self.seq.view_pattern, track))
        if index == 3:
            return str(self.seq.get_audio_track_volume(self.seq.view_pattern, track))
        if index == 4:
            return str(self.seq.get_audio_track_shift(self.seq.view_pattern, track))
        return ""

    def _apply_audio_track_param_value_text(self, track, index, text):
        if index == 1:
            self.seq.set_audio_track_name(self.seq.view_pattern, track, text)
            self.status_message = texts.fmt(
                texts.status.track.name,
                track_num=track + 1,
                name=self.seq.get_audio_track_name(self.seq.view_pattern, track),
            )
            return True
        try:
            value = int((text or "").strip())
        except ValueError:
            self.status_message = texts.status.generic.enter_numeric_value
            return False

        if index == 2:
            value = max(1, min(9, value))
            self.seq.set_audio_track_pan(self.seq.view_pattern, track, value)
            self.status_message = texts.fmt(texts.status.track.pan, track_num=track + 1, value=value)
            return True
        if index == 3:
            value = max(0, min(9, value))
            self.seq.set_audio_track_volume(self.seq.view_pattern, track, value)
            self.status_message = texts.fmt(texts.status.track.volume, track_num=track + 1, value=value)
            return True
        if index == 4:
            value = max(0, min(50, value))
            self.seq.set_audio_track_shift(self.seq.view_pattern, track, value)
            shift_ms = self.seq.audio_shift_ui_to_ms(value)
            self.status_message = texts.fmt(texts.status.track.shift, track_num=track + 1, value=value, shift_ms=shift_ms)
            return True
        return False

    def _apply_audio_track_params_dialog(self, initial_input_override=None):
        """Apply action or open value dialog for selected audio-track parameter."""
        track = int(self.audio_track_params_dialog_track)
        if track < 0 or track >= (TRACKS - 1):
            return
        idx = int(self.audio_track_params_dialog_index)

        if idx == 0:
            ok, message = self.seq.toggle_audio_track_mode(self.seq.view_pattern, track)
            self.status_message = message
            self.cursor_y = self._row_for_track(track)
            return
        if idx == 5:
            self._open_clear_audio_confirm(self.seq.view_pattern, track)
            return

        prompt = f"{self._audio_track_params_dialog_track_label(track)} {texts.prompt.audio_track_params.names[idx]}"
        initial_value = (
            str(initial_input_override)
            if initial_input_override is not None
            else self._audio_track_params_dialog_current_value(track, idx)
        )

        def _do_apply(text):
            return self._apply_audio_track_param_value_text(track, idx, text)

        max_len = 64 if idx == 1 else 2
        self._open_text_input_dialog(prompt, _do_apply, initial_input=initial_value, max_length=max_len)

    def _tap_tempo(self):
        """Register a tap and update BPM from average interval of last 4 taps."""
        now = time.perf_counter()
        self.tap_tempo_times.append(now)
        # Drop taps older than 3 seconds (stale sequence)
        self.tap_tempo_times = [t for t in self.tap_tempo_times if now - t < 3.0]
        if len(self.tap_tempo_times) >= 2:
            intervals = [self.tap_tempo_times[i] - self.tap_tempo_times[i - 1]
                         for i in range(1, len(self.tap_tempo_times))]
            avg_interval = sum(intervals) / len(intervals)
            bpm = round(60.0 / avg_interval)
            bpm = max(20, min(300, bpm))
            self.seq.set_bpm(bpm)
            self.status_message = texts.fmt(texts.status.tempo.tap, bpm=bpm)

    def _close_chain_dialog(self):
        pass

    def _close_pattern_menu(self):
        self.pattern_menu_active = False
        self.pattern_menu_kind = "file"

    def _close_chop_overlay(self):
        """Close chop preview/apply overlay."""
        self.chop_overlay_active = False
        self.chop_overlay_index = 0

    def _close_import_overlay(self):
        """Close audio import action overlay."""
        self.import_overlay_active = False
        self.import_overlay_index = 0
        self.import_overlay_path = None
        self.import_overlay_can_delete_source = False

    def _open_import_overlay(self, path, can_delete_source=False):
        """Open import action overlay for a dropped/pasted WAV path."""
        src = _normalize_dropped_path(path)
        if not os.path.isfile(src) or not src.lower().endswith(".wav"):
            self.status_message = texts.status.generic.select_wav_to_import
            return False
        self.import_overlay_active = True
        self.import_overlay_index = 0
        self.import_overlay_path = src
        self.import_overlay_can_delete_source = bool(can_delete_source)
        self.drop_path_active = False
        self.drop_path_input = ""
        if self.nav.active_tab == TAB_AUDIO:
            default_track = self._track_for_row(self.cursor_y)
        else:
            default_track = self.cursor_y if 0 <= self.cursor_y < (TRACKS - 1) else 0
        self.import_target_drum_track = default_track
        self.import_target_audio_track = default_track
        self.status_message = texts.fmt(texts.status.importing.source_ready, name=os.path.basename(src))
        return True

    def _refresh_record_devices(self):
        recorder.refresh_record_devices(self)

    def _refresh_record_input_sources(self):
        recorder.refresh_record_input_sources(self)

    def _current_record_input_indices(self):
        return recorder.current_record_input_indices(self)

    def _extract_record_input(self, indata):
        return recorder.extract_record_input(self, indata)

    def _record_level_callback(self, indata, frames, time_info, status):
        recorder.record_level_callback(self, indata, frames, time_info, status)

    def _record_capture_callback(self, indata, frames, time_info, status):
        recorder.record_capture_callback(self, indata, frames, time_info, status)

    def _stop_record_monitor(self):
        recorder.stop_record_monitor(self)

    def _start_record_monitor(self):
        recorder.start_record_monitor(self)

    def _start_record_capture_stream(self):
        return recorder.start_record_capture_stream(self)

    def _open_record_overlay(self, target_track=None, from_audio_view=False):
        recorder.open_record_overlay(self, target_track=target_track, from_audio_view=from_audio_view)

    def _close_record_overlay(self):
        recorder.close_record_overlay(self)

    def _cancel_record_capture(self, reason="Recording canceled"):
        recorder.cancel_record_capture(self, reason=reason)

    def _finish_record_capture(self):
        recorder.finish_record_capture(self)

    def _arm_record_capture(self):
        recorder.arm_record_capture(self)

    def _try_open_chop_overlay(self, path):
        """Prepare chops from a dropped/pasted path and open chop overlay."""
        ok, message = self.seq.prepare_chop_candidates_from_file(path)
        self.status_message = message
        if ok:
            self.chop_overlay_active = True
            self.chop_overlay_index = 0
            self.drop_path_active = False
            self.drop_path_input = ""
        return ok

    def _maybe_auto_open_drop_path(self):
        """Auto-open import overlay shortly after a dropped path appears complete."""
        if not self.drop_path_active:
            return False
        src = _normalize_dropped_path(self.drop_path_input)
        if not src.lower().endswith(".wav"):
            return False
        if (time.perf_counter() - self.drop_path_last_input_time) < 0.15:
            return False
        return self._open_import_overlay(src)

    def _close_file_browser(self):
        self.file_browser_active = False
        self.file_browser_mode = None
        self.file_browser_target_track = None
        self.file_browser_items = []
        self.file_browser_index = 0

    def _refresh_file_browser(self):
        items = []
        current = os.path.abspath(self.file_browser_path)
        self.file_browser_path = current
        parent = os.path.dirname(current)
        if parent and parent != current:
            items.append({"name": "../", "path": parent, "is_dir": True, "is_parent": True})

        if self.file_browser_mode == "kit":
            items.append({"name": "[LOAD THIS FOLDER]", "path": current, "is_dir": False, "is_parent": False, "is_action": True})

        try:
            entries = list(os.scandir(current))
        except Exception as exc:
            self.status_message = texts.fmt(texts.status.file.browse_failed, error=exc)
            entries = []

        dirs = []
        files = []
        for e in entries:
            if e.name.startswith("."):
                continue
            if e.is_dir(follow_symlinks=False):
                dirs.append(e)
            elif e.is_file(follow_symlinks=False):
                if self.file_browser_mode in ["pattern", "pattern_steps"] and e.name.lower().endswith(".json"):
                    files.append(e)
                elif self.file_browser_mode in ["sample", "audio_track"] and e.name.lower().endswith(".wav"):
                    files.append(e)

        dirs.sort(key=lambda e: e.name.casefold())
        files.sort(key=lambda e: e.name.casefold())

        for e in dirs:
            items.append({"name": f"{e.name}/", "path": e.path, "is_dir": True, "is_parent": False})
        for e in files:
            items.append({"name": e.name, "path": e.path, "is_dir": False, "is_parent": False})

        self.file_browser_items = items
        if self.file_browser_index >= len(items):
            self.file_browser_index = max(0, len(items) - 1)

    def _open_file_browser(self, mode, target_track=None):
        self.file_browser_mode = mode
        self.file_browser_target_track = target_track
        start_path = os.getcwd()
        if mode == "kit":
            start_path = self.seq.kit_path if os.path.isdir(self.seq.kit_path) else start_path
        elif mode == "sample" and target_track is not None:
            sample_path = self.seq.engine.sample_paths[target_track]
            if sample_path and os.path.exists(sample_path):
                start_path = os.path.dirname(sample_path)
            elif os.path.isdir(self.seq.kit_path):
                start_path = self.seq.kit_path
        self.file_browser_path = os.path.abspath(start_path)
        self.file_browser_active = True
        self.file_browser_index = 0
        self.audio_export_options_active = False
        self.kit_export_options_active = False
        self._refresh_file_browser()

    def _file_browser_enter_dir(self):
        if not self.file_browser_items:
            return
        item = self.file_browser_items[self.file_browser_index]
        if not item["is_dir"]:
            return
        self.file_browser_path = item["path"]
        self.file_browser_index = 0
        self._refresh_file_browser()

    def _run_file_browser_select(self):
        if not self.file_browser_items:
            return
        item = self.file_browser_items[self.file_browser_index]

        if item["is_parent"]:
            self.file_browser_path = item["path"]
            self.file_browser_index = 0
            self._refresh_file_browser()
            return

        if item.get("is_action"):
            if self.file_browser_mode == "kit":
                ok, message = self.seq.load_kit_folder(item["path"])
                self.status_message = message
                self._close_file_browser()
            return

        if item["is_dir"]:
            self.file_browser_path = item["path"]
            self.file_browser_index = 0
            self._refresh_file_browser()
            return

        if self.file_browser_mode == "pattern":
            ok, message = self.seq.load_project_file(item["path"])
            self.status_message = message
            self._close_file_browser()
            return

        if self.file_browser_mode == "pattern_steps":
            ok, message = self.seq.import_pattern_steps_from_project(item["path"])
            self.status_message = message
            self._close_file_browser()
            return

        if self.file_browser_mode == "kit":
            return

        if self.file_browser_mode == "sample":
            track = self.file_browser_target_track
            if track is None:
                self.status_message = texts.status.generic.no_target_track_selected
                self._close_file_browser()
                return
            ok, message = self.seq.load_single_sample_to_track(track, item["path"])
            self.status_message = message
            self._close_file_browser()
            return

        if self.file_browser_mode == "audio_track":
            track = self.file_browser_target_track
            if track is None:
                self.status_message = texts.status.generic.no_target_track_selected
                self._close_file_browser()
                return
            ok, message = self.seq.load_audio_track_sample(self.seq.view_pattern, track, item["path"])
            self.status_message = message
            self._close_file_browser()
            return

    def _tick_record_capture(self):
        recorder.tick_record_capture(self)

    def _open_clear_audio_confirm(self, pattern_index, track):
        """Open generic confirm dialog for clearing an audio track sample."""
        pattern_idx = int(pattern_index)
        track_idx = int(track)
        path = self.seq.get_audio_track_path(pattern_idx, track_idx)
        path_name = os.path.basename(path) if path else "(no file)"

        def _force_delete_everywhere():
            ok, message = self.seq.force_delete_audio_path(path)
            self.status_message = message
            return True

        def _do_clear_audio_track():
            ok, message, needs_force = self.seq.clear_audio_track_sample(
                pattern_idx,
                track_idx,
                delete_file=True,
            )
            self.status_message = message
            if needs_force:
                self._open_confirm_dialog(
                    texts.fmt(texts.prompt.confirm.force_delete_audio, path_name=path_name),
                    _force_delete_everywhere,
                )
            return True

        self._open_confirm_dialog(
            texts.fmt(texts.prompt.confirm.clear_audio_track, track_num=track_idx + 1, path_name=path_name),
            _do_clear_audio_track,
        )

    def _menu_items(self):
        """Return currently active top-menu item list."""
        if self.pattern_menu_kind == "pattern":
            return PATTERN_MENU_ITEMS
        return FILE_MENU_ITEMS

    def _open_top_menu(self, kind):
        """Open top-level menu by kind: file or pattern."""
        if kind not in ["file", "pattern"]:
            kind = "file"
        self.pattern_menu_kind = kind
        self.pattern_menu_active = True
        self.pattern_menu_index = 0

    def _focus_header_menu_button(self, kind):
        """Return header focus to a specific top menu button."""
        if kind not in ["file", "pattern"]:
            kind = "file"
        self._focus_header_nav(section="params", edit_active=False)
        try:
            self.nav.header.param_index = self.nav.header.params.index(kind)
        except ValueError:
            self.nav.header.param_index = 0

    def _run_pattern_menu_action(self):
        if self.pattern_menu_kind == "pattern":
            if self.pattern_menu_index == 0:
                self.patterns_overlay_active = True
                self.patterns_overlay_index = max(0, min(self.seq.pattern_count() - 1, self.seq.view_pattern))
                ok, message = True, ""
            elif self.pattern_menu_index == 1:
                ok, message = self.seq.add_pattern_after_current(copy_from_view=False)
            elif self.pattern_menu_index == 2:
                ok, message = self.seq.add_pattern_after_current(copy_from_view=True)
            elif self.pattern_menu_index == 3:
                clip_text = _read_system_clipboard_text()
                ok_parse, parse_message, parsed = self.seq.parse_patterns_from_text(clip_text)
                if not ok_parse:
                    ok, message = False, texts.fmt(texts.status.importing.clipboard_parse_failed, message=parse_message)
                else:
                    import_count = len(parsed)
                    def _do_import_from_clipboard():
                        ok_import, msg_import = self.seq.import_patterns_from_text(clip_text)
                        self.status_message = msg_import
                        return True
                    if import_count > 1:
                        confirm_msg = texts.fmt(texts.prompt.confirm.import_patterns_many, count=import_count)
                    else:
                        confirm_msg = texts.prompt.confirm.import_patterns_single
                    self._open_confirm_dialog(confirm_msg, _do_import_from_clipboard)
                    ok, message = True, ""
            elif self.pattern_menu_index == 4:
                self._open_file_browser("pattern_steps")
                ok, message = True, ""
            elif self.pattern_menu_index == 5:
                text = self.seq.export_patterns_to_text()
                copied, copy_error = _write_system_clipboard_text(text)
                if copied:
                    ok, message = True, texts.fmt(texts.status.importing.copied_patterns, count=self.seq.pattern_count())
                else:
                    ok, message = False, texts.fmt(texts.status.file.copy_failed, error=copy_error)
            elif self.pattern_menu_index == 6:
                idx = self.seq.view_pattern
                if self.seq.pattern_has_data(idx):
                    def _do_clear_pattern_from_menu():
                        self.seq.clear_current_pattern()
                        self.status_message = texts.fmt(texts.status.pattern.cleared, num=idx + 1)
                        return True

                    self._open_confirm_dialog(
                        texts.fmt(texts.prompt.confirm.clear_pattern_with_data, num=idx + 1),
                        _do_clear_pattern_from_menu,
                    )
                    ok, message = True, ""
                else:
                    self.seq.clear_current_pattern()
                    ok, message = True, texts.fmt(texts.status.pattern.cleared, num=idx + 1)
            elif self.pattern_menu_index == 7:
                ok, message = self.seq.copy_current_pattern()
            elif self.pattern_menu_index == 8:
                ok, message = self.seq.paste_to_current_pattern()
            elif self.pattern_menu_index == 9:
                idx = self.seq.view_pattern
                if self.seq.pattern_has_data(idx):
                    def _do_delete_pattern_from_menu():
                        ok_delete, msg_delete = self.seq.delete_pattern(idx)
                        self.status_message = msg_delete
                        return ok_delete

                    self._open_confirm_dialog(
                        texts.fmt(texts.prompt.confirm.delete_pattern_with_data, num=idx + 1),
                        _do_delete_pattern_from_menu,
                    )
                    ok, message = True, ""
                else:
                    ok, message = self.seq.delete_pattern(idx)
            else:
                ok, message = False, texts.status.errors.invalid_pattern_menu_option
            self.status_message = message
            return

        if self.pattern_menu_index == 0:
            ok, message = self.seq.new_project("new_project.json")
        elif self.pattern_menu_index == 1:
            self._open_file_browser("pattern")
            ok, message = True, ""
        elif self.pattern_menu_index == 2:
            try:
                self.seq.save()
                ok, message = True, texts.fmt(texts.status.file.saved, name=os.path.basename(self.seq.pattern_path))
            except Exception as exc:
                ok, message = False, texts.fmt(texts.status.file.save_failed, error=exc)
        elif self.pattern_menu_index == 3:
            def _do_save_project_as(text):
                ok_save, msg_save = self.seq.save_project_as(text)
                self.status_message = msg_save
                return ok_save

            self._open_text_input_dialog(texts.prompt.dialog.save_project_as, _do_save_project_as)
            ok, message = True, ""
        elif self.pattern_menu_index == 4:
            self.kit_export_options_active = True
            self.kit_export_options_index = 0
            self.kit_export_options = {
                "bit_depth": 16,
                "sample_rate": self.seq.engine.sr,
                "channels": 1,
            }
            self.kit_export_options_active = True
            ok, message = True, ""
        elif self.pattern_menu_index == 5:
            self._open_file_browser("kit")
            ok, message = True, ""
        elif self.pattern_menu_index == 6:
            self.audio_export_options_active = True
            self.audio_export_options_index = 0
            self.audio_export_options = {
                "bit_depth": 16,
                "sample_rate": self.seq.engine.sr,
                "channels": 2,
                "scope": "pattern",
            }
            self.audio_export_options_active = True
            ok, message = True, ""
        else:
            ok, message = False, texts.status.errors.invalid_file_menu_option
        self.status_message = message

    def handle_key(self, key):
        """Handle a single key event. Returns False when app should exit."""
        event_tokens = _event_tokens(key)
        key_code = key if isinstance(key, int) else ord(key)
        header_nav = self.nav.header
        pattern_nav = self.nav.pattern
        if self.nav.active_tab == TAB_SEQUENCER and self.cursor_x == AUDIO_VOLUME_COL:
            self.cursor_x = REC_COL
        if self.status_message and key_code != -1:
            self.status_message = ""
        if self.nav.active_tab in [TAB_AUDIO, TAB_MIXER] and self.cursor_y >= (TRACKS - 1):
            self.cursor_y = TRACKS - 2

        if self.confirm_dialog_active:
            if key_code == 27:
                self._close_confirm_dialog()
                self.status_message = texts.status.generic.canceled
                return True
            if key_code in [curses.KEY_LEFT, curses.KEY_UP, curses.KEY_BTAB]:
                self.confirm_dialog_index = 0
                return True
            if key_code in [curses.KEY_RIGHT, curses.KEY_DOWN, 9]:
                self.confirm_dialog_index = 1
                return True
            if isinstance(key, str) and key.lower() in ["y", "n"]:
                self.confirm_dialog_index = 1 if key.lower() == "y" else 0
                if key.lower() == "n":
                    self._close_confirm_dialog()
                    self.status_message = texts.status.generic.canceled
                    return True
                # key == 'y' executes action below by simulating Enter branch
                key_code = 10
            if key_code in [10, 13, curses.KEY_ENTER]:
                action = self.confirm_dialog_action
                execute_yes = (self.confirm_dialog_index == 1)
                self._close_confirm_dialog()
                if not execute_yes:
                    self.status_message = texts.status.generic.canceled
                    return True
                if callable(action):
                    try:
                        result = action()
                    except Exception as exc:
                        self.status_message = texts.fmt(texts.status.errors.confirm_action_failed, error=exc)
                        return True
                    if result == "EXIT_APP":
                        return False
                return True
            return True

        if self.text_input_dialog_active:
            if key_code == 27:
                self._close_text_input_dialog()
                self.status_message = texts.status.generic.canceled
                return True
            if key_code in [curses.KEY_LEFT, curses.KEY_UP, curses.KEY_BTAB]:
                self.text_input_dialog_index = 0
                return True
            if key_code in [curses.KEY_RIGHT, curses.KEY_DOWN, 9]:
                self.text_input_dialog_index = 1
                return True
            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.text_input_dialog_input = self.text_input_dialog_input[:-1]
                return True
            if isinstance(key, str) and key.isprintable() and key not in ["\n", "\r", "\t"]:
                if len(self.text_input_dialog_input) < self.text_input_dialog_max_length:
                    self.text_input_dialog_input += key
                return True
            if key_code in [10, 13, curses.KEY_ENTER]:
                action = self.text_input_dialog_action
                value = self.text_input_dialog_input
                execute_ok = (self.text_input_dialog_index == 1)
                self._close_text_input_dialog()
                if not execute_ok:
                    self.status_message = texts.status.generic.canceled
                    return True
                if callable(action):
                    try:
                        result = action(value)
                    except Exception as exc:
                        self.status_message = texts.fmt(texts.status.errors.input_action_failed, error=exc)
                        return True
                    if result == "EXIT_APP":
                        return False
                return True
            return True

        if self.record_overlay_active:
            if self.keymap.matches("record_menu", event_tokens):
                if self.record_capture_active:
                    if self.seq.playing:
                        self.seq.toggle_playback()
                    self._finish_record_capture()
                else:
                    self._close_record_overlay()
                    self.status_message = texts.status.generic.record_menu_closed
                return True
            row_count = 6
            if key_code == 27:
                self._close_record_overlay()
                return True
            if key_code == curses.KEY_UP:
                self.record_overlay_index = (self.record_overlay_index - 1) % row_count
                return True
            if key_code == curses.KEY_DOWN:
                self.record_overlay_index = (self.record_overlay_index + 1) % row_count
                return True
            if key_code in [ord("m"), ord("M")]:
                self.record_channels = 1
                self._start_record_monitor()
                return True
            if key_code in [ord("s"), ord("S")]:
                self.record_channels = 2
                self._start_record_monitor()
                return True
            if key_code in [curses.KEY_LEFT, curses.KEY_RIGHT, 32]:
                direction = -1 if key_code == curses.KEY_LEFT else 1
                if key_code == 32:
                    direction = 1
                if self.record_overlay_index == 0:
                    self.record_channels = 2 if self.record_channels == 1 else 1
                    self._refresh_record_input_sources()
                    self._start_record_monitor()
                elif self.record_overlay_index == 1:
                    if self.record_device_ids:
                        self.record_device_index = (self.record_device_index + direction) % len(self.record_device_ids)
                        self._refresh_record_input_sources()
                        self.record_input_source_index = 0
                        self._start_record_monitor()
                elif self.record_overlay_index == 2:
                    if self.record_input_sources:
                        self.record_input_source_index = (self.record_input_source_index + direction) % len(self.record_input_sources)
                    self._start_record_monitor()
                elif self.record_overlay_index == 3:
                    self.record_precount_enabled = not self.record_precount_enabled
                elif self.record_overlay_index == 4:
                    count = max(1, self.seq.pattern_count())
                    self.record_precount_pattern = (self.record_precount_pattern + direction) % count
                elif self.record_overlay_index == 5:
                    self.record_action_index = 0 if self.record_action_index == 1 else 1
                return True
            if key_code in [10, 13, curses.KEY_ENTER]:
                if self.record_overlay_index == 5:
                    if self.record_action_index == 0:
                        self._close_record_overlay()
                        self.status_message = texts.status.generic.record_menu_closed
                    else:
                        if self.record_capture_active:
                            if self.seq.playing:
                                self.seq.toggle_playback()
                            self._finish_record_capture()
                        else:
                            self._arm_record_capture()
                    return True
                self.record_overlay_index = min(row_count - 1, self.record_overlay_index + 1)
                return True
            return True

        if self.import_overlay_active:
            max_index = 4 if self.import_overlay_can_delete_source else 3
            if key_code == 27:
                self._close_import_overlay()
                self.status_message = texts.status.generic.import_canceled
                return True
            if key_code == curses.KEY_UP:
                self.import_overlay_index = (self.import_overlay_index - 1) % (max_index + 1)
                return True
            if key_code == curses.KEY_DOWN:
                self.import_overlay_index = (self.import_overlay_index + 1) % (max_index + 1)
                return True
            if key_code == curses.KEY_LEFT:
                if self.import_overlay_index == 1:
                    self.import_target_drum_track = (self.import_target_drum_track - 1) % (TRACKS - 1)
                elif self.import_overlay_index == 2:
                    self.import_target_audio_track = (self.import_target_audio_track - 1) % (TRACKS - 1)
                return True
            if key_code == curses.KEY_RIGHT:
                if self.import_overlay_index == 1:
                    self.import_target_drum_track = (self.import_target_drum_track + 1) % (TRACKS - 1)
                elif self.import_overlay_index == 2:
                    self.import_target_audio_track = (self.import_target_audio_track + 1) % (TRACKS - 1)
                return True
            if key_code == 32:
                path = self.import_overlay_path
                if not path:
                    return True
                if self.import_overlay_index == 2:
                    ok, message = self.seq.preview_audio_track_file(
                        path,
                        pattern_index=self.seq.view_pattern,
                        track=self.import_target_audio_track,
                    )
                else:
                    ok, message = self.seq.preview_sample_file(path, track=self.import_target_drum_track)
                self.status_message = message
                return True
            if key_code in [10, 13, curses.KEY_ENTER]:
                path = self.import_overlay_path
                if not path:
                    self._close_import_overlay()
                    self.status_message = texts.status.generic.import_canceled
                    return True
                if self.import_overlay_index == 0:
                    self._close_import_overlay()
                    self._try_open_chop_overlay(path)
                    return True
                if self.import_overlay_index == 1:
                    ok, message = self.seq.load_single_sample_to_track(self.import_target_drum_track, path)
                    self.status_message = message
                    self._close_import_overlay()
                    return True
                if self.import_overlay_index == 2:
                    ok, message = self.seq.load_audio_track_sample(
                        self.seq.view_pattern,
                        self.import_target_audio_track,
                        path,
                    )
                    self.status_message = message
                    self._close_import_overlay()
                    return True
                if self.import_overlay_can_delete_source and self.import_overlay_index == 4:
                    delete_path = path
                    self._close_import_overlay()
                    try:
                        if delete_path and os.path.isfile(delete_path):
                            os.remove(delete_path)
                            self.status_message = texts.status.generic.import_canceled_deleted
                        else:
                            self.status_message = texts.status.generic.recording_file_missing
                    except Exception as exc:
                        self.status_message = texts.fmt(texts.status.file.delete_failed, error=exc)
                    return True
                self._close_import_overlay()
                self.status_message = texts.status.generic.import_canceled
                return True
            return True

        if self.chop_overlay_active:
            max_index = 9
            if key_code == 27:
                self._close_chop_overlay()
                return True
            if key_code == curses.KEY_UP:
                self.chop_overlay_index = (self.chop_overlay_index - 1) % (max_index + 1)
                return True
            if key_code == curses.KEY_DOWN:
                self.chop_overlay_index = (self.chop_overlay_index + 1) % (max_index + 1)
                return True
            if key_code == 32:  # Space preview
                if self.chop_overlay_index < len(self.seq.chop_preview_samples):
                    ok, message = self.seq.preview_chop_candidate(self.chop_overlay_index, self.cursor_y)
                    self.status_message = message
                return True
            if key_code in [10, 13, curses.KEY_ENTER]:
                if self.chop_overlay_index < 8:
                    ok, message = self.seq.preview_chop_candidate(self.chop_overlay_index, self.cursor_y)
                    self.status_message = message
                    return True
                if self.chop_overlay_index == 8:
                    ok, message = self.seq.apply_chop_candidates_to_kit()
                    self.status_message = message
                    self._close_chop_overlay()
                    return True
                self._close_chop_overlay()
                self.status_message = texts.status.generic.import_canceled
                return True
            return True

        if self.drop_path_active:
            if key_code == 27:
                self.drop_path_active = False
                self.drop_path_input = ""
                self.status_message = texts.status.generic.drop_canceled
                return True
            if key_code in [10, 13, curses.KEY_ENTER]:
                dropped = _normalize_dropped_path(self.drop_path_input)
                self.drop_path_active = False
                self.drop_path_input = ""
                if dropped:
                    self._open_import_overlay(dropped)
                return True
            if key_code in {curses.KEY_BACKSPACE, 127, 8} or key in ["\b", "\x7f"]:
                self.drop_path_input = self.drop_path_input[:-1]
                self.drop_path_last_input_time = time.perf_counter()
                return True
            if isinstance(key, str) and key.isprintable() and key not in ["\n", "\r", "\t"]:
                if len(self.drop_path_input) < 1000:
                    self.drop_path_input += key
                self.drop_path_last_input_time = time.perf_counter()
                return True
            return True

        if self.patterns_overlay_active:
            count = self.seq.pattern_count()
            if key_code == 27 or self.keymap.matches("patterns_overlay", event_tokens):
                self.patterns_overlay_active = False
                return True
            if key_code == curses.KEY_UP:
                if count > 0:
                    self.patterns_overlay_index = (self.patterns_overlay_index - 1) % count
                return True
            if key_code == curses.KEY_DOWN:
                if count > 0:
                    self.patterns_overlay_index = (self.patterns_overlay_index + 1) % count
                return True
            if key_code in [10, 13, curses.KEY_ENTER]:
                if count > 0:
                    self.seq.select_pattern(self.patterns_overlay_index)
                return True
            if key_code == 32:
                if not self.seq.playing and count > 0:
                    self.seq.select_pattern(self.patterns_overlay_index)
                self.seq.toggle_playback()
                return True
            if key_code in [ord("a"), ord("A")]:
                ok, message = self.seq.add_pattern_after_current(copy_from_view=False)
                self.status_message = message
                self.patterns_overlay_index = self.seq.view_pattern
                return True
            if key_code in [ord("d"), ord("D")]:
                ok, message = self.seq.add_pattern_after_current(copy_from_view=True)
                self.status_message = message
                self.patterns_overlay_index = self.seq.view_pattern
                return True
            if key_code in [ord("x"), ord("X")]:
                if count <= 0:
                    return True
                idx = self.patterns_overlay_index
                if self.seq.pattern_has_data(idx):
                    def _do_delete_pattern_from_overlay():
                        ok, message = self.seq.delete_pattern(idx)
                        self.status_message = message
                        self.patterns_overlay_index = min(idx, self.seq.pattern_count() - 1)
                        return True

                    self._open_confirm_dialog(
                        f"Delete pattern {idx + 1}? This pattern contains data.",
                        _do_delete_pattern_from_overlay,
                    )
                    return True

                ok, message = self.seq.delete_pattern(idx)
                self.status_message = message
                self.patterns_overlay_index = min(idx, self.seq.pattern_count() - 1)
                return True
            return True

        if self.audio_export_options_active:
            row_count = 5
            if key_code == 27:
                self._close_audio_export_options_dialog()
                return True
            if key_code == curses.KEY_UP:
                self.audio_export_options_index = (self.audio_export_options_index - 1) % row_count
                return True
            if key_code == curses.KEY_DOWN:
                self.audio_export_options_index = (self.audio_export_options_index + 1) % row_count
                return True
            if key_code in [10, 13, curses.KEY_ENTER]:
                if self.audio_export_options_index == 4:
                    self.audio_export_options_active = False
                    def _do_export_audio(text):
                        ok_export, msg_export = self.seq.export_current_pattern_audio(
                            text,
                            options={**self.audio_export_options, "eq_enabled": self.export_eq_enabled, "tape_enabled": self.export_tape_enabled, **self.export_settings},
                        )
                        self.status_message = msg_export
                        return ok_export

                    self._open_text_input_dialog(texts.prompt.dialog.export_audio_filename, _do_export_audio)
                    return True
                key_code = curses.KEY_RIGHT

            if key_code in [curses.KEY_LEFT, curses.KEY_RIGHT, 32]:
                direction = -1 if key_code == curses.KEY_LEFT else 1
                if key_code == 32:
                    direction = 1

                if self.audio_export_options_index == 0:
                    bit_depths = [8, 16]
                    cur = int(self.audio_export_options.get("bit_depth", 16))
                    try:
                        idx = bit_depths.index(cur)
                    except ValueError:
                        idx = 1
                    idx = (idx + direction) % len(bit_depths)
                    self.audio_export_options["bit_depth"] = bit_depths[idx]
                elif self.audio_export_options_index == 1:
                    rates = [11025, 22050, 32000, 44100, 48000]
                    cur = int(self.audio_export_options.get("sample_rate", 44100))
                    try:
                        idx = rates.index(cur)
                    except ValueError:
                        idx = rates.index(44100)
                    idx = (idx + direction) % len(rates)
                    self.audio_export_options["sample_rate"] = rates[idx]
                elif self.audio_export_options_index == 2:
                    chans = [1, 2]
                    cur = int(self.audio_export_options.get("channels", 2))
                    try:
                        idx = chans.index(cur)
                    except ValueError:
                        idx = 1
                    idx = (idx + direction) % len(chans)
                    self.audio_export_options["channels"] = chans[idx]
                elif self.audio_export_options_index == 3:
                    scopes = ["pattern", "chain"]
                    cur = str(self.audio_export_options.get("scope", "pattern")).strip().lower()
                    try:
                        idx = scopes.index(cur)
                    except ValueError:
                        idx = 0
                    idx = (idx + direction) % len(scopes)
                    self.audio_export_options["scope"] = scopes[idx]
                return True
            return True

        if self.kit_export_options_active:
            row_count = 4
            if key_code == 27:
                self._close_kit_export_options_dialog()
                return True
            if key_code == curses.KEY_UP:
                self.kit_export_options_index = (self.kit_export_options_index - 1) % row_count
                return True
            if key_code == curses.KEY_DOWN:
                self.kit_export_options_index = (self.kit_export_options_index + 1) % row_count
                return True
            if key_code in [10, 13, curses.KEY_ENTER]:
                if self.kit_export_options_index == 3:
                    self.kit_export_options_active = False
                    def _do_export_kit(text):
                        ok_export, msg_export = self.seq.export_current_kit(text, options=self.kit_export_options)
                        self.status_message = msg_export
                        return ok_export

                    self._open_text_input_dialog(texts.prompt.dialog.export_kit_folder, _do_export_kit)
                    return True
                key_code = curses.KEY_RIGHT

            if key_code in [curses.KEY_LEFT, curses.KEY_RIGHT, 32]:
                direction = -1 if key_code == curses.KEY_LEFT else 1
                if key_code == 32:
                    direction = 1

                if self.kit_export_options_index == 0:
                    bit_depths = [8, 16]
                    cur = int(self.kit_export_options.get("bit_depth", 16))
                    try:
                        idx = bit_depths.index(cur)
                    except ValueError:
                        idx = 1
                    idx = (idx + direction) % len(bit_depths)
                    self.kit_export_options["bit_depth"] = bit_depths[idx]
                elif self.kit_export_options_index == 1:
                    rates = [11025, 22050, 44100, 48000]
                    cur = int(self.kit_export_options.get("sample_rate", 44100))
                    try:
                        idx = rates.index(cur)
                    except ValueError:
                        idx = rates.index(44100)
                    idx = (idx + direction) % len(rates)
                    self.kit_export_options["sample_rate"] = rates[idx]
                elif self.kit_export_options_index == 2:
                    chans = [1, 2]
                    cur = int(self.kit_export_options.get("channels", 1))
                    try:
                        idx = chans.index(cur)
                    except ValueError:
                        idx = 0
                    idx = (idx + direction) % len(chans)
                    self.kit_export_options["channels"] = chans[idx]
                return True
            return True

        if self.file_browser_active:
            if key_code == 27:
                self._close_file_browser()
                return True
            if "SPACE" in event_tokens or key_code == 32:
                if self.file_browser_mode in ["sample", "audio_track"] and self.file_browser_items:
                    item = self.file_browser_items[self.file_browser_index]
                    if (not item.get("is_parent")) and (not item.get("is_action")) and (not item["is_dir"]):
                        if self.file_browser_mode == "sample":
                            ok, message = self.seq.preview_sample_file(item["path"], self.file_browser_target_track)
                        else:
                            ok, message = self.seq.preview_audio_track_file(
                                item["path"],
                                pattern_index=self.seq.view_pattern,
                                track=self.file_browser_target_track,
                            )
                        self.status_message = message
                return True
            if key_code in {curses.KEY_BACKSPACE, 127, 8}:
                parent = os.path.dirname(self.file_browser_path)
                if parent and parent != self.file_browser_path:
                    self.file_browser_path = parent
                    self.file_browser_index = 0
                    self._refresh_file_browser()
                return True
            if key_code == curses.KEY_UP:
                if self.file_browser_items:
                    self.file_browser_index = (self.file_browser_index - 1) % len(self.file_browser_items)
                return True
            if key_code == curses.KEY_DOWN:
                if self.file_browser_items:
                    self.file_browser_index = (self.file_browser_index + 1) % len(self.file_browser_items)
                return True
            if key_code in [10, 13, curses.KEY_ENTER]:
                self._run_file_browser_select()
                return True
            if key_code == curses.KEY_RIGHT:
                self._file_browser_enter_dir()
                return True
            if key_code == curses.KEY_LEFT:
                parent = os.path.dirname(self.file_browser_path)
                if parent and parent != self.file_browser_path:
                    self.file_browser_path = parent
                    self.file_browser_index = 0
                    self._refresh_file_browser()
                return True
            return True

        if self.pattern_menu_active:
            menu_items = self._menu_items()
            close_by_hotkey = self.keymap.matches("file_menu", event_tokens)
            if self.pattern_menu_kind == "pattern":
                close_by_hotkey = close_by_hotkey or self.keymap.matches("pattern_menu", event_tokens)
            if key_code == 27 or close_by_hotkey:
                menu_kind = self.pattern_menu_kind
                self._close_pattern_menu()
                self._focus_header_menu_button(menu_kind)
                return True
            if key_code == curses.KEY_UP:
                self.pattern_menu_index = (self.pattern_menu_index - 1) % len(menu_items)
                return True
            if key_code == curses.KEY_DOWN:
                self.pattern_menu_index = (self.pattern_menu_index + 1) % len(menu_items)
                return True
            if self.pattern_menu_kind == "pattern" and key_code in [ord("a"), ord("A")]:
                self.pattern_menu_index = 1
                self._run_pattern_menu_action()
                self._close_pattern_menu()
                return True
            if self.pattern_menu_kind == "pattern" and key_code in [ord("d"), ord("D")]:
                self.pattern_menu_index = 2
                self._run_pattern_menu_action()
                self._close_pattern_menu()
                return True
            if self.pattern_menu_kind == "pattern" and key_code in [ord("c"), ord("C")]:
                self.pattern_menu_index = 7
                self._run_pattern_menu_action()
                self._close_pattern_menu()
                return True
            if self.pattern_menu_kind == "pattern" and key_code in [ord("v"), ord("V")]:
                self.pattern_menu_index = 8
                self._run_pattern_menu_action()
                self._close_pattern_menu()
                return True
            if self.pattern_menu_kind == "pattern" and key_code in [ord("x"), ord("X")]:
                self.pattern_menu_index = 9
                self._run_pattern_menu_action()
                self._close_pattern_menu()
                return True
            if key_code in [10, 13, curses.KEY_ENTER]:
                self._run_pattern_menu_action()
                self._close_pattern_menu()
                return True
            if ord("1") <= key_code <= ord("9"):
                idx = key_code - ord("1")
                if idx < len(menu_items):
                    self.pattern_menu_index = idx
                    self._run_pattern_menu_action()
                    self._close_pattern_menu()
                    return True
            return True

        # Track-parameter dialog input has priority over global cursor/navigation handlers.
        if self.track_params_dialog_active:
            if key_code == 27:  # ESC
                self._close_track_params_dialog()
                return True
            if key_code in [10, 13, curses.KEY_ENTER]:
                self._apply_track_params_dialog()
                return True
            if key_code == curses.KEY_RIGHT:
                if self.track_params_dialog_track == ACCENT_TRACK:
                    self.track_params_dialog_track = 0
                else:
                    self.track_params_dialog_track = (self.track_params_dialog_track + 1) % max(1, TRACKS - 1)
                return True
            if key_code == curses.KEY_LEFT:
                if self.track_params_dialog_track == ACCENT_TRACK:
                    self.track_params_dialog_track = max(0, TRACKS - 2)
                else:
                    self.track_params_dialog_track = (self.track_params_dialog_track - 1) % max(1, TRACKS - 1)
                return True
            if key_code in [curses.KEY_DOWN, 9]:
                self.track_params_dialog_index = (self.track_params_dialog_index + 1) % 7
                return True
            if key_code in [curses.KEY_UP, curses.KEY_BTAB]:
                self.track_params_dialog_index = (self.track_params_dialog_index - 1) % 7
                return True

            if isinstance(key, str) and key.isdigit() and self.track_params_dialog_index != 6:
                self._apply_track_params_dialog(initial_input_override=key)
                return True
            return True

        # Audio-track parameter dialog input has priority over global handlers.
        if self.audio_track_params_dialog_active:
            if key_code == 27:  # ESC
                self._close_audio_track_params_dialog()
                return True
            if key_code in [10, 13, curses.KEY_ENTER]:
                self._apply_audio_track_params_dialog()
                return True
            if key_code == curses.KEY_RIGHT:
                self.audio_track_params_dialog_track = (self.audio_track_params_dialog_track + 1) % max(1, TRACKS - 1)
                self.cursor_y = self._row_for_track(self.audio_track_params_dialog_track)
                return True
            if key_code == curses.KEY_LEFT:
                self.audio_track_params_dialog_track = (self.audio_track_params_dialog_track - 1) % max(1, TRACKS - 1)
                self.cursor_y = self._row_for_track(self.audio_track_params_dialog_track)
                return True
            if key_code in [curses.KEY_DOWN, 9]:
                self.audio_track_params_dialog_index = (self.audio_track_params_dialog_index + 1) % 6
                return True
            if key_code in [curses.KEY_UP, curses.KEY_BTAB]:
                self.audio_track_params_dialog_index = (self.audio_track_params_dialog_index - 1) % 6
                return True
            if isinstance(key, str):
                if key.isdigit() and self.audio_track_params_dialog_index in [2, 3, 4]:
                    self._apply_audio_track_params_dialog(initial_input_override=key)
                    return True
                if key.isprintable() and key.strip() and self.audio_track_params_dialog_index == 1:
                    self._apply_audio_track_params_dialog(initial_input_override=key)
                    return True
            return True

        # Global navigation handlers (arrow keys + tab) start here.
        if key_code == curses.KEY_RIGHT:
            if pattern_nav.focus and self.nav.active_tab == 0:
                if pattern_nav.edit_active:
                    if self._pattern_param_current() == "name":
                        return True
                    self._adjust_pattern_param(+1)
                else:
                    if pattern_nav.index == 0:
                        return True
                    pattern_nav.next_adjustable()
                return True
            if header_nav.focus:
                if header_nav.section == "tabs":
                    self._set_active_tab((self.nav.active_tab + 1) % len(self.nav.tabs))
                    return True
                if header_nav.edit_active:
                    param = header_nav.current_param()
                    if param in ["file", "pattern", "song", "record", "midi"]:
                        return True
                    elif param == "bpm":
                        self.seq.change_bpm(+1)
                    else:
                        self.seq.change_pitch_semitones(+1)
                else:
                    header_nav.next_param()
                return True
            else:
                if self.nav.active_tab == TAB_SONG:
                    self.cursor_x = min(1, self.cursor_x + 1)
                    self._clamp_song_cursor()
                elif self.nav.active_tab == TAB_AUDIO:
                    cols = self._audio_nav_cols()
                    idx = cols.index(self.cursor_x) if self.cursor_x in cols else 0
                    self.cursor_x = cols[(idx + 1) % len(cols)]
                elif self.nav.active_tab == TAB_MIXER:
                    cols = [0, 1, 2, 3, 4, 5]
                    nxt = cols[0]
                    for c in cols:
                        if c > self.cursor_x:
                            nxt = c
                            break
                    self.cursor_x = nxt
                elif self.nav.active_tab == TAB_EXPORT:
                    direction = 1
                    self._export_tab_change(direction)
                else:
                    cols = self._sequencer_nav_cols()
                    if self.cursor_x in cols:
                        idx = cols.index(self.cursor_x)
                    else:
                        idx = 0
                    self.cursor_x = cols[(idx + 1) % len(cols)]
            return True
        if key_code == curses.KEY_LEFT:
            if pattern_nav.focus and self.nav.active_tab == 0:
                if pattern_nav.edit_active:
                    if self._pattern_param_current() == "name":
                        return True
                    self._adjust_pattern_param(-1)
                else:
                    if pattern_nav.index == 0:
                        return True
                    pattern_nav.prev_adjustable()
                return True
            if header_nav.focus:
                if header_nav.section == "tabs":
                    self._set_active_tab((self.nav.active_tab - 1) % len(self.nav.tabs))
                    return True
                if header_nav.edit_active:
                    param = header_nav.current_param()
                    if param in ["file", "pattern", "song", "record", "midi"]:
                        return True
                    elif param == "bpm":
                        self.seq.change_bpm(-1)
                    else:
                        self.seq.change_pitch_semitones(-1)
                else:
                    header_nav.prev_param()
                return True
            else:
                if self.nav.active_tab == TAB_SONG:
                    self.cursor_x = max(0, self.cursor_x - 1)
                    self._clamp_song_cursor()
                elif self.nav.active_tab == TAB_AUDIO:
                    cols = self._audio_nav_cols()
                    idx = cols.index(self.cursor_x) if self.cursor_x in cols else 0
                    self.cursor_x = cols[(idx - 1) % len(cols)]
                elif self.nav.active_tab == TAB_MIXER:
                    cols = [0, 1, 2, 3]
                    prev = cols[-1]
                    for c in reversed(cols):
                        if c < self.cursor_x:
                            prev = c
                            break
                    self.cursor_x = prev
                elif self.nav.active_tab == TAB_EXPORT:
                    direction = -1
                    self._export_tab_change(direction)
                else:
                    cols = self._sequencer_nav_cols()
                    if self.cursor_x in cols:
                        idx = cols.index(self.cursor_x)
                    else:
                        idx = 0
                    self.cursor_x = cols[(idx - 1) % len(cols)]
            return True
        if key_code == curses.KEY_UP:
            if pattern_nav.focus and self.nav.active_tab == 0:
                if pattern_nav.edit_active and self._pattern_param_current() == "name":
                    return True
                nav_result = pattern_nav.move_up()
                if nav_result == "name":
                    return True
                self._focus_header_nav(section="tabs", edit_active=False)
                return True
            if header_nav.focus:
                if header_nav.section == "params" and header_nav.edit_active:
                    param = header_nav.current_param()
                    if param == "bpm":
                        self.seq.change_bpm(+1)
                    elif param == "pitch":
                        self.seq.change_pitch_semitones(+1)
                elif header_nav.section == "tabs":
                    self.nav.header_move_up()
                return True
            if self.cursor_y == 0:
                if self.nav.active_tab == TAB_AUDIO:
                    self.nav.focus_pattern_from_grid()
                else:
                    self._focus_header_nav(section="tabs", edit_active=False)
            else:
                if self.nav.active_tab == TAB_SONG:
                    self.cursor_y = max(0, self.cursor_y - 1)
                elif self.nav.active_tab in [TAB_AUDIO, TAB_MIXER]:
                    self.cursor_y = max(0, self.cursor_y - 1)
                elif self.nav.active_tab == TAB_EXPORT:
                    self.cursor_y = max(0, self.cursor_y - 1)
                else:
                    self.move_cursor(0, -1)
            return True
        if key_code == curses.KEY_DOWN:
            if pattern_nav.focus and self.nav.active_tab == 0:
                if pattern_nav.edit_active:
                    if self._pattern_param_current() == "name":
                        return True
                    self._adjust_pattern_param(-1)
                    return True
                else:
                    # Move down from pattern params to sequencer grid
                    if pattern_nav.move_down() == "grid":
                        self.cursor_y = 0
                    return True
            elif header_nav.focus:
                # Navigate through header sections then to content below
                header_target = self.nav.header_move_down()
                if header_target == "tabs":
                    return True
                elif header_target == "content":
                    # Move from tabs to content area
                    if self.nav.active_tab == 0:
                        self._focus_pattern_params(index=0, edit_active=False)
                    else:
                        self.cursor_y = 0
                    return True
            else:
                if self.nav.active_tab == TAB_SONG:
                    self.cursor_y = min(self._song_nav_row_count() - 1, self.cursor_y + 1)
                elif self.nav.active_tab in [TAB_AUDIO, TAB_MIXER]:
                    self.cursor_y = min(TRACKS - 2, self.cursor_y + 1)
                elif self.nav.active_tab == TAB_EXPORT:
                    self.cursor_y = min(5, self.cursor_y + 1)
                else:
                    self.move_cursor(0, 1)
            return True
        if "TAB" in event_tokens or key_code == 9:
            if pattern_nav.focus and self.nav.active_tab == 0:
                if pattern_nav.edit_active and self._pattern_param_current() == "name":
                    return True
                if pattern_nav.index == 0:
                    return True
                pattern_nav.next_adjustable()
                return True
            if header_nav.focus:
                if header_nav.section == "tabs":
                    self._set_active_tab((self.nav.active_tab + 1) % len(self.nav.tabs))
                elif not header_nav.edit_active:
                    header_nav.next_param()
                return True
            if self.nav.active_tab == TAB_SONG:
                self.cursor_x = 1 if self.cursor_x == 0 else 0
                self._clamp_song_cursor()
                return True
            if self.nav.active_tab == TAB_AUDIO:
                cycle = self._audio_nav_cols()
                idx = cycle.index(self.cursor_x) if self.cursor_x in cycle else -1
                self.cursor_x = cycle[(idx + 1) % len(cycle)]
                return True
            elif self.nav.active_tab == TAB_MIXER:
                cycle = [0, 1, 2, 3, 4, 5]
                next_idx = (cycle.index(self.cursor_x) + 1) % len(cycle) if self.cursor_x in cycle else 0
                self.cursor_x = cycle[next_idx]
                return True
            else:
                if 0 <= self.cursor_x < self.seq.max_step_count:
                    # In sequencer step grid, Tab hops by beat-starts rather than every step.
                    beat_cols = self._sequencer_beat_cols()
                    if self.cursor_x >= beat_cols[-1]:
                        # From last beat, exit grid to first parameter column.
                        self.cursor_x = REC_COL
                        return True
                    if self.cursor_x in beat_cols:
                        idx = beat_cols.index(self.cursor_x)
                    else:
                        idx = -1
                        for i, col in enumerate(beat_cols):
                            if col > self.cursor_x:
                                idx = i - 1
                                break
                        if idx < -1:
                            idx = -1
                    self.cursor_x = beat_cols[(idx + 1) % len(beat_cols)]
                    return True
                cycle = self._sequencer_nav_cols()
                idx = cycle.index(self.cursor_x) if self.cursor_x in cycle else -1
                self.cursor_x = cycle[(idx + 1) % len(cycle)]
                return True
        if "BTAB" in event_tokens or key_code == curses.KEY_BTAB:
            if pattern_nav.focus and self.nav.active_tab == 0:
                if pattern_nav.edit_active and self._pattern_param_current() == "name":
                    return True
                if pattern_nav.index == 0:
                    return True
                pattern_nav.prev_adjustable()
                return True
            if header_nav.focus:
                if header_nav.section == "tabs":
                    self._set_active_tab((self.nav.active_tab - 1) % len(self.nav.tabs))
                elif not header_nav.edit_active:
                    header_nav.prev_param()
                return True
            if self.nav.active_tab == TAB_SONG:
                self.cursor_x = 0 if self.cursor_x == 1 else 1
                self._clamp_song_cursor()
                return True
            if self.nav.active_tab == TAB_AUDIO:
                cycle = self._audio_nav_cols()
                idx = cycle.index(self.cursor_x) if self.cursor_x in cycle else 0
                self.cursor_x = cycle[(idx - 1) % len(cycle)]
                return True
            elif self.nav.active_tab == TAB_MIXER:
                cycle = [0, 1, 2, 3, 4, 5]
                prev_idx = (cycle.index(self.cursor_x) - 1) % len(cycle) if self.cursor_x in cycle else len(cycle) - 1
                self.cursor_x = cycle[prev_idx]
                return True
            else:
                if 0 <= self.cursor_x < self.seq.max_step_count:
                    # Reverse beat-hop for Shift+Tab while cursor is inside sequencer steps.
                    beat_cols = self._sequencer_beat_cols()
                    if self.cursor_x <= beat_cols[0]:
                        # From first beat, exit grid to preview/load columns in reverse order.
                        self.cursor_x = PREVIEW_COL
                        return True
                    if self.cursor_x in beat_cols:
                        idx = beat_cols.index(self.cursor_x)
                    else:
                        idx = 0
                        for i, col in enumerate(beat_cols):
                            if col >= self.cursor_x:
                                idx = i
                                break
                        else:
                            idx = 0
                    self.cursor_x = beat_cols[(idx - 1) % len(beat_cols)]
                    return True
                cycle = self._sequencer_nav_cols()
                idx = cycle.index(self.cursor_x) if self.cursor_x in cycle else 0
                self.cursor_x = cycle[(idx - 1) % len(cycle)]
                return True
        backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
        if pattern_nav.focus and self.nav.active_tab == 0 and self._pattern_param_current() in ["length", "swing"]:
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                pattern_nav.input_buffer = pattern_nav.input_buffer[:-1]
                if pattern_nav.input_buffer:
                    self._apply_pattern_param_input()
                return True
        if key_code == 27:  # ESC
            if pattern_nav.focus:
                self._clear_pattern_param_input()
                pattern_nav.focus = False
                return True
            if self.audio_export_options_active:
                self._close_audio_export_options_dialog()
                return True
            if self.kit_export_options_active:
                self._close_kit_export_options_dialog()
                return True
            if self.track_params_dialog_active:
                self._close_track_params_dialog()
                return True
            if self.audio_track_params_dialog_active:
                self._close_audio_track_params_dialog()
                return True
            self._open_confirm_dialog(texts.prompt.confirm.quit, self._confirm_quit_action)
            return True

        if self.keymap.matches("clear_pattern", event_tokens):
            pat_num = self.seq.view_pattern + 1
            if self.seq.pattern_has_data(self.seq.view_pattern):
                def _do_clear_pattern():
                    self.seq.clear_current_pattern()
                    self.status_message = texts.fmt(texts.status.pattern.cleared, num=pat_num)
                    return True
                self._open_confirm_dialog(texts.prompt.confirm.clear_pattern.format(num=pat_num), _do_clear_pattern)
            else:
                self.seq.clear_current_pattern()
                self.status_message = texts.fmt(texts.status.pattern.cleared, num=pat_num)
            return True

        if isinstance(key, str) and key in ["/", "~"]:
            self.drop_path_active = True
            self.drop_path_input = key
            self.drop_path_last_input_time = time.perf_counter()
            self.status_message = texts.status.generic.drop_path_detected
            return True

        if key_code == ord(' '):
            self.seq.toggle_playback()
            self.status_message = ""
        elif self.keymap.matches("patterns_overlay", event_tokens):
            self.patterns_overlay_active = True
            self.patterns_overlay_index = max(0, min(self.seq.pattern_count() - 1, self.seq.view_pattern))
        elif self.keymap.matches("file_menu", event_tokens):
            header_nav.blur()
            self._open_top_menu("file")
        elif self.keymap.matches("pattern_menu", event_tokens):
            header_nav.blur()
            self._open_top_menu("pattern")
        elif self.keymap.matches("record_menu", event_tokens):
            header_nav.blur()
            if self.record_overlay_active:
                if self.record_capture_active:
                    if self.seq.playing:
                        self.seq.toggle_playback()
                    self._finish_record_capture()
                else:
                    self._close_record_overlay()
            else:
                self._open_record_overlay()
        elif self.keymap.matches("pattern_copy", event_tokens):
            ok, message = self.seq.copy_current_pattern()
            self.status_message = message
        elif self.keymap.matches("pattern_paste", event_tokens):
            ok, message = self.seq.paste_to_current_pattern()
            self.status_message = message
        elif self.keymap.matches("pattern_export", event_tokens):
            def _do_save_project_as(text):
                ok_save, msg_save = self.seq.save_project_as(text)
                self.status_message = msg_save
                return ok_save

            self._open_text_input_dialog(texts.prompt.dialog.save_project_as, _do_save_project_as)
            self.status_message = ""
        elif self.keymap.matches("pattern_load", event_tokens):
            self._open_file_browser("pattern")
            self.status_message = ""
        elif self.keymap.matches("kit_load", event_tokens):
            self._open_file_browser("kit")
            self.status_message = ""
        elif self.keymap.matches("chain_edit", event_tokens):
            def _do_set_chain(text):
                ok_chain, msg_chain = self.seq.set_chain_from_text(text)
                self.status_message = msg_chain
                return ok_chain

            initial_chain = "" if self.seq.chain_display() == "OFF" else self.seq.chain_display()
            self._open_text_input_dialog(texts.prompt.dialog.song_sequence, _do_set_chain, initial_input=initial_chain)
            self.status_message = ""
        elif self.keymap.matches("chain_toggle", event_tokens):
            ok, message = self.seq.toggle_chain()
            self.status_message = message
        elif self.keymap.matches("mode_toggle", event_tokens):
            self._cycle_edit_mode()
        elif self.keymap.matches("pattern_length_dec", event_tokens):
            self.seq.change_current_pattern_length(-1)
        elif self.keymap.matches("pattern_length_inc", event_tokens):
            self.seq.change_current_pattern_length(1)
        elif self.keymap.matches("tempo_inc", event_tokens):
            self.seq.change_bpm(1)
        elif self.keymap.matches("tempo_dec", event_tokens):
            self.seq.change_bpm(-1)
        elif key_code in [
            ord('!'), ord('@'), ord('#'), ord('$'),
            ord('"'), 164,  # common Shift+2 / Shift+4 on some EU layouts
        ]:
            if self.cursor_x < self.seq.max_step_count and self.cursor_y != ACCENT_TRACK:
                quick_ratchet = {
                    ord('!'): 1,
                    ord('@'): 2,
                    ord('#'): 3,
                    ord('$'): 4,
                    ord('"'): 2,
                    164: 4,
                }[key_code]
                self.seq.quick_set_ratchet(self.cursor_y, self.cursor_x, quick_ratchet)
                self.move_cursor(1, 0)
        elif key_code in range(ord('0'), ord('9') + 1):
            velocity = key_code - ord('0')
            if pattern_nav.focus and self.nav.active_tab == 0:
                current = self._pattern_param_current()
                max_lens = {
                    "length": len(str(self.seq.max_step_count)),
                    "swing": 2,
                }
                if current in max_lens:
                    max_len = max_lens[current]
                    digit = chr(key_code)
                    if len(pattern_nav.input_buffer) >= max_len:
                        pattern_nav.input_buffer = digit
                    else:
                        pattern_nav.input_buffer += digit
                    self._apply_pattern_param_input()
                    return True
            # BPM header is now handled by text input dialog only, no live digit typing
            if header_nav.focus and header_nav.section == "params" and header_nav.current_param() == "bpm":
                return True
            track_idx = self._track_for_row(self.cursor_y) if self.nav.active_tab == TAB_AUDIO else self.cursor_y
            if self.nav.active_tab == TAB_MIXER:
                track_idx = max(0, min(TRACKS - 2, self.cursor_y))
                if self.cursor_x == 0 and velocity > 0:
                    self.seq.set_track_pan(track_idx, velocity)
                elif self.cursor_x == 1:
                    self.seq.set_track_volume(track_idx, velocity)
                elif self.cursor_x == 2:
                    self._apply_inline_track_value(REC_COL, velocity)
                elif self.cursor_x == 3:
                    self._apply_inline_track_value(TRACK_PITCH_COL, velocity)
                elif self.cursor_x == 4 and velocity > 0:
                    self.seq.set_audio_track_pan(self.seq.view_pattern, track_idx, velocity)
                elif self.cursor_x == 5:
                    self.seq.set_audio_track_volume(self.seq.view_pattern, track_idx, velocity)
                return True
            if self.nav.active_tab == TAB_AUDIO and self.cursor_x == TRACK_LABEL_COL:
                self.audio_track_params_dialog_active = True
                self.audio_track_params_dialog_track = max(0, min(TRACKS - 2, track_idx))
                self.audio_track_params_dialog_index = 2
                self._apply_audio_track_params_dialog(initial_input_override=velocity)
                return True
            elif self.nav.active_tab == TAB_AUDIO:
                return True
            elif self.cursor_x == PREVIEW_COL:
                pass
            elif self.cursor_x == CLEAR_COL:
                if self.cursor_y != ACCENT_TRACK:
                    self.seq.set_track_group(self.cursor_y, velocity)
            elif self.cursor_x == TRACK_PITCH_COL:
                if self.cursor_y != ACCENT_TRACK:
                    self._apply_inline_track_value(TRACK_PITCH_COL, velocity)
            elif self.cursor_x == REC_COL:
                self._apply_inline_track_value(REC_COL, velocity)
            elif self.cursor_x == LOAD_COL:
                pass
            elif self.edit_mode == "ratchet":
                if self.cursor_y == ACCENT_TRACK:
                    self.seq.set_step_velocity(self.cursor_y, self.cursor_x, velocity)
                elif 1 <= velocity <= 4:
                    self.seq.set_step_ratchet(self.cursor_y, self.cursor_x, velocity)
                self.move_cursor(1, 0)
            elif self.edit_mode == "detune":
                if self.cursor_y != ACCENT_TRACK:
                    self.seq.set_step_detune(self.cursor_y, self.cursor_x, velocity)
                self.move_cursor(1, 0)
            elif self.edit_mode == "pan":
                if self.cursor_y != ACCENT_TRACK:
                    self.seq.set_step_pan(self.cursor_y, self.cursor_x, velocity)
                self.move_cursor(1, 0)
            else:
                self.seq.set_step_velocity(self.cursor_y, self.cursor_x, velocity)
                if velocity > 0:
                    self.seq.set_last_velocity(velocity)
                self.move_cursor(1, 0)
        elif key_code in [10, 13, curses.KEY_ENTER]:
            if pattern_nav.focus and self.nav.active_tab == 0:
                current = self._pattern_param_current()
                if current == "name":
                    pattern_index = self.seq.view_pattern

                    def _do_set_pattern_name(text):
                        self.seq.set_pattern_name(pattern_index, text)
                        self.status_message = texts.fmt(
                            texts.status.pattern.name,
                            name=self.seq.get_pattern_name(pattern_index),
                        )
                        return True

                    self._open_text_input_dialog(
                        texts.prompt.dialog.pattern_name,
                        _do_set_pattern_name,
                        initial_input=self.seq.get_pattern_name(pattern_index),
                        max_length=64,
                    )
                elif current == "mode":
                    self._cycle_edit_mode()
                elif current == "humanize":
                    self.seq.toggle_current_pattern_humanize()
                    state = "ON" if self.seq.current_pattern_humanize_enabled() else "OFF"
                    self.status_message = texts.fmt(texts.status.pattern.humanize, state=state)
                else:
                    pattern_nav.edit_active = not pattern_nav.edit_active
                return True
            if header_nav.focus:
                if header_nav.section == "tabs":
                    if self.nav.active_tab == TAB_SEQUENCER:
                        self.status_message = texts.status.generic.sequencer_view
                    elif self.nav.active_tab == TAB_SONG:
                        self.status_message = texts.status.generic.song_view
                    elif self.nav.active_tab == TAB_AUDIO:
                        self.status_message = texts.status.generic.audio_view
                    elif self.nav.active_tab == TAB_MIXER:
                        self.status_message = texts.status.generic.mixer_view
                    else:
                        self.status_message = texts.status.generic.export_view
                    return True
                param = header_nav.current_param()
                if param == "file":
                    self._open_top_menu("file")
                    header_nav.blur()
                elif param == "pattern":
                    self._open_top_menu("pattern")
                    header_nav.blur()
                elif param == "song":
                    ok, message = self.seq.toggle_chain()
                    self.status_message = message
                    header_nav.edit_active = False
                elif param == "record":
                    if self.record_overlay_active:
                        if self.record_capture_active:
                            if self.seq.playing:
                                self.seq.toggle_playback()
                            self._finish_record_capture()
                        else:
                            self._close_record_overlay()
                    else:
                        self._open_record_overlay()
                    header_nav.blur()
                elif param == "patterns":
                    self.patterns_overlay_active = True
                    self.patterns_overlay_index = max(0, min(self.seq.pattern_count() - 1, self.seq.view_pattern))
                    header_nav.blur()
                elif param == "midi":
                    ok, message = self.seq.toggle_midi_out()
                    self.status_message = message
                    header_nav.edit_active = False
                elif param == "chain_set":
                    def _do_set_chain(text):
                        ok_chain, msg_chain = self.seq.set_chain_from_text(text)
                        self.status_message = msg_chain
                        return ok_chain

                    initial_chain = "" if self.seq.chain_display() == "OFF" else self.seq.chain_display()
                    self._open_text_input_dialog(texts.prompt.dialog.song_sequence, _do_set_chain, initial_input=initial_chain)
                    self.status_message = ""
                    header_nav.blur()
                elif param == "bpm":
                    def _do_set_bpm(text):
                        try:
                            bpm_value = int(text.strip())
                            bpm_value = max(20, min(300, bpm_value))
                            self.seq.set_bpm(bpm_value)
                            self.status_message = texts.fmt(texts.status.tempo.set, bpm=bpm_value)
                            return True
                        except ValueError:
                            self.status_message = texts.status.tempo.invalid
                            return False

                    self._open_text_input_dialog(texts.prompt.dialog.set_bpm, _do_set_bpm, initial_input=str(self.seq.bpm), max_length=3)
                    header_nav.blur()
                else:
                    header_nav.edit_active = not header_nav.edit_active
                return True
            if self.nav.active_tab == TAB_SONG:
                if self.cursor_x == 0:
                    ok, message = self.seq.append_pattern_to_chain(self.cursor_y)
                    self.status_message = message
                    if ok:
                        self.cursor_x = 1
                        self.cursor_y = max(0, len(self.seq.chain) - 1)
                    self._clamp_song_cursor()
                    return True
                ok, message = self.seq.remove_chain_item(self.cursor_y)
                self.status_message = message
                self._clamp_song_cursor()
                return True
            if self.nav.active_tab == TAB_AUDIO:
                track_idx = self._track_for_row(self.cursor_y)
                if self.cursor_x == TRACK_LABEL_COL:
                    self.audio_track_params_dialog_active = True
                    self.audio_track_params_dialog_track = max(0, min(TRACKS - 2, track_idx))
                    self.audio_track_params_dialog_index = 0
                    return True
                if self.cursor_x == PREVIEW_COL:
                    if self.cursor_y != ACCENT_TRACK:
                        ok, message = self.seq.preview_audio_track_slot(self.seq.view_pattern, track_idx)
                        self.status_message = message
                return True
            if self.nav.active_tab == TAB_MIXER:
                self.status_message = texts.status.generic.mixer_hint
                return True
            if self.nav.active_tab == TAB_EXPORT:
                if self.cursor_y == 4:
                    if self.cursor_x == 0:
                        self.export_eq_enabled = not self.export_eq_enabled
                    else:
                        self.export_tape_enabled = not self.export_tape_enabled
                elif self.cursor_y == 5:
                    self.audio_export_options_active = False
                    def _do_export_audio(text):
                        ok_export, msg_export = self.seq.export_current_pattern_audio(
                            text,
                            options={**self.audio_export_options, "eq_enabled": self.export_eq_enabled, "tape_enabled": self.export_tape_enabled, **self.export_settings},
                        )
                        self.status_message = msg_export
                        return ok_export

                    self._open_text_input_dialog(texts.prompt.dialog.export_audio_filename, _do_export_audio)
                return True
            if self.cursor_x == PREVIEW_COL:
                if self.cursor_y != ACCENT_TRACK:
                    self.seq.preview_row(self.cursor_y)
            elif self.cursor_x == TRACK_LABEL_COL:
                self.track_params_dialog_active = True
                self.track_params_dialog_track = self.cursor_y
                self.track_params_dialog_index = 0
                self.track_params_dialog_input = ""
            else:
                self.seq.toggle_step(self.cursor_y, self.cursor_x)
                self.move_cursor(1, 0)
        elif self.keymap.matches("mute_row", event_tokens):
            if self.nav.active_tab == 0:
                self.seq.toggle_mute_row(self.cursor_y)
        elif self.keymap.matches("tab_1", event_tokens):
            self._set_active_tab(TAB_SEQUENCER)
        elif self.keymap.matches("tab_2", event_tokens):
            self._set_active_tab(TAB_SONG)
        elif self.keymap.matches("tab_3", event_tokens):
            self._set_active_tab(TAB_AUDIO)
        elif self.keymap.matches("tab_4", event_tokens):
            self._set_active_tab(TAB_MIXER)
        elif self.keymap.matches("tab_5", event_tokens):
            self._set_active_tab(TAB_EXPORT)
        elif self.keymap.matches("pattern_prev", event_tokens):
            self.seq.select_pattern(max(0, self.seq.view_pattern - 1))
        elif self.keymap.matches("pattern_next", event_tokens):
            self.seq.select_pattern(min(self.seq.pattern_count() - 1, self.seq.view_pattern + 1))
        else:
            for pattern_index, action in enumerate(self.pattern_actions):
                if self.keymap.matches(action, event_tokens):
                    self.seq.select_pattern(pattern_index)
                    break

        return True

# ---------- INPUT ----------
def ui_loop(stdscr, seq, colors=None, export_settings=None):
    """Main curses event/render loop."""
    curses.set_escdelay(25)
    curses.curs_set(0)
    stdscr.nodelay(True)

    _colors = colors if isinstance(colors, dict) else {}
    _export_settings = export_settings if isinstance(export_settings, dict) else {}
    record_input_metering_raw = str(_colors.get("rec_input_metering", "off")).strip().lower()
    record_input_metering_enabled = record_input_metering_raw in {"1", "true", "yes", "on"}
    large_blocks_raw = str(_colors.get("large_blocks", "off")).strip().lower()
    large_blocks_enabled = large_blocks_raw in {"1", "true", "yes", "on"}
    sort_audio_tracks_by_type_raw = str(_colors.get("sort_audio_tracks_by_type", "on")).strip().lower()
    sort_audio_tracks_by_type_enabled = sort_audio_tracks_by_type_raw in {"1", "true", "yes", "on"}
    seq_grid_wide_raw = str(_colors.get("seq_grid_wide", "off")).strip().lower()
    seq_grid_wide_enabled = seq_grid_wide_raw in {"1", "true", "yes", "on"}
    playhead_divider_raw = str(_colors.get("playhead_divider", "on")).strip().lower()
    playhead_divider_enabled = playhead_divider_raw in {"1", "true", "yes", "on"}
    show_steps_outside_pattern_raw = str(_colors.get("show_steps_outside_pattern", "on")).strip().lower()
    show_steps_outside_pattern_enabled = show_steps_outside_pattern_raw in {"1", "true", "yes", "on"}
    dim_overlay_enabled_raw = str(_colors.get("dim_overlay_enabled", "on")).strip().lower()
    dim_overlay_enabled = dim_overlay_enabled_raw in {"1", "true", "yes", "on"}
    theme = {
        "frame": 0,
        "title": 0,
        "text": 0,
        "hint": 0,
        "prompt": 0,
        "selected": curses.A_REVERSE,
        "divider": 0,
        "playhead": 0,
        "muted": curses.A_DIM,
        "accent": 0,
        "chain_on": 0,
        "chain_off": curses.A_DIM,
        "pattern_manual": 0,
        "pattern_chain_off": curses.A_DIM,
        "velocity_low": 0,
        "velocity_high": 0,
        "midi_on": 0,
        "midi_off": curses.A_DIM,
        "record": 0,
        "meter_fill": 0,
        "meter_hot": 0,
        "tertiary_on": 0,
        "tertiary_off": curses.A_DIM,
        "text_bold_enabled": False,
        "text_uppercase_enabled": True,
    }
    ui_options = {
        "record_input_metering_enabled": record_input_metering_enabled,
        "large_blocks_enabled": large_blocks_enabled,
        "sort_audio_tracks_by_type_enabled": sort_audio_tracks_by_type_enabled,
        "seq_grid_wide_enabled": seq_grid_wide_enabled,
        "playhead_divider_enabled": playhead_divider_enabled,
        "show_steps_outside_pattern_enabled": show_steps_outside_pattern_enabled,
        "dim_overlay_enabled": dim_overlay_enabled,
    }
    if curses.has_colors():
        curses.start_color()
        try:
            curses.use_default_colors()
        except curses.error:
            pass
        color_map = {
            "black": curses.COLOR_BLACK,
            "red": curses.COLOR_RED,
            "green": curses.COLOR_GREEN,
            "yellow": curses.COLOR_YELLOW,
            "blue": curses.COLOR_BLUE,
            "magenta": curses.COLOR_MAGENTA,
            "cyan": curses.COLOR_CYAN,
            "white": curses.COLOR_WHITE,
        }

        def resolve_color(name, default_name):
            raw = str(name or default_name).strip().lower()
            is_bright = False
            for prefix in ("bright_", "intense_"):
                if raw.startswith(prefix):
                    raw = raw[len(prefix):]
                    is_bright = True
                    break
            return color_map.get(raw, color_map[default_name]), is_bright

        def pair_attr(pair_id, base_attr=0, bright=False):
            attr = curses.color_pair(pair_id) | base_attr
            return attr

        primary_color, primary_bright = resolve_color(_colors.get("color_primary", "cyan"), "cyan")
        text_color, text_bright = resolve_color(_colors.get("color_text", "white"), "white")
        playhead_color, playhead_bright = resolve_color(_colors.get("color_accent", "green"), "green")
        accent_color, accent_bright = resolve_color(_colors.get("color_accent", "yellow"), "yellow")
        divider_color, divider_bright = resolve_color(_colors.get("color_divider", "blue"), "blue")
        record_color, record_bright = resolve_color(_colors.get("color_record", "red"), "red")
        meter_color, meter_bright = resolve_color(_colors.get("color_meter", "green"), "green")
        selection_fg_color, _selection_fg_bright = resolve_color(_colors.get("color_selection_fg", "white"), "white")
        selection_bg_color, _selection_bg_bright = resolve_color(_colors.get("color_selection_bg", "blue"), "blue")
        tertiary_color, tertiary_bright = resolve_color(_colors.get("color_tertiary", "yellow"), "yellow")
        text_bold_raw = str(_colors.get("text_bold", "off")).strip().lower()
        text_uppercase_raw = str(_colors.get("text_uppercase", "on")).strip().lower()
        text_bold_enabled = text_bold_raw in {"1", "true", "yes", "on"}
        text_uppercase_enabled = text_uppercase_raw in {"1", "true", "yes", "on"}

        curses.init_pair(1, primary_color, -1)               # primary (frame/prompt)
        curses.init_pair(2, text_color, -1)                  # text
        curses.init_pair(3, playhead_color, -1)              # playhead / chain_on / midi_on
        curses.init_pair(4, accent_color, -1)                # accent / hint / high velocity
        curses.init_pair(5, divider_color, -1)               # dividers
        curses.init_pair(6, record_color, -1)                # record / meter_hot
        curses.init_pair(7, meter_color, -1)                 # meter fill
        curses.init_pair(8, selection_fg_color, selection_bg_color)  # selected text
        curses.init_pair(9, tertiary_color, -1)              # tertiary (footer PATTERNS/SONG)

        theme["frame"] = pair_attr(1, bright=primary_bright)
        theme["title"] = pair_attr(1, bright=primary_bright)
        theme["prompt"] = pair_attr(1, bright=primary_bright)
        theme["selected"] = curses.A_REVERSE
        theme["text"] = pair_attr(2, bright=text_bright)
        theme["hint"] = pair_attr(4, bright=accent_bright)
        theme["divider"] = pair_attr(5, bright=divider_bright)
        theme["playhead"] = pair_attr(3, bright=playhead_bright)
        theme["muted"] = pair_attr(2, curses.A_DIM, bright=text_bright)
        theme["accent"] = pair_attr(4, bright=accent_bright)
        theme["chain_on"] = pair_attr(3, bright=playhead_bright)
        theme["chain_off"] = pair_attr(2, curses.A_DIM, bright=text_bright)
        theme["pattern_manual"] = pair_attr(3, bright=playhead_bright)
        theme["pattern_chain_off"] = pair_attr(2, curses.A_DIM, bright=text_bright)
        theme["velocity_low"] = pair_attr(2, curses.A_DIM, bright=text_bright)
        theme["velocity_high"] = pair_attr(2, bright=text_bright)
        theme["midi_on"] = pair_attr(3, bright=playhead_bright)
        theme["midi_off"] = pair_attr(2, curses.A_DIM, bright=text_bright)
        theme["record"] = pair_attr(6, bright=record_bright)
        theme["meter_fill"] = pair_attr(7, bright=meter_bright)
        theme["meter_hot"] = pair_attr(6, bright=record_bright)
        theme["tertiary_on"] = pair_attr(9, bright=tertiary_bright)
        theme["tertiary_off"] = pair_attr(9, curses.A_DIM, bright=tertiary_bright)
        theme["text_bold_enabled"] = text_bold_enabled
        theme["text_uppercase_enabled"] = text_uppercase_enabled

    keymap = Keymap()
    tab_1_binding = str(_colors.get("hotkey_tab_1", "F1")).strip() or "F1"
    tab_2_binding = str(_colors.get("hotkey_tab_2", "F2")).strip() or "F2"
    tab_3_binding = str(_colors.get("hotkey_tab_3", "F3")).strip() or "F3"
    tab_4_binding = str(_colors.get("hotkey_tab_4", "x")).strip() or "x"
    tab_5_binding = str(_colors.get("hotkey_tab_5", "c")).strip() or "c"
    keymap.set_binding("tab_1", tab_1_binding)
    keymap.set_binding("tab_2", tab_2_binding)
    keymap.set_binding("tab_3", tab_3_binding)
    keymap.set_binding("tab_4", tab_4_binding)
    keymap.set_binding("tab_5", tab_5_binding)
    controller = Controller(seq, keymap, _export_settings)
    controller.record_input_metering_enabled = record_input_metering_enabled
    controller.sort_audio_tracks_by_type_enabled = sort_audio_tracks_by_type_enabled
    file_menu_label = keymap.label("file_menu")
    mode_key_label = keymap.label("mode_toggle")
    tab_1_label = keymap.label("tab_1")
    tab_2_label = keymap.label("tab_2")
    tab_3_label = keymap.label("tab_3")
    tab_4_label = keymap.label("tab_4")
    tab_5_label = keymap.label("tab_5")
    clear_key_label = keymap.label("clear_pattern")
    length_dec_label = keymap.label("pattern_length_dec")
    length_inc_label = keymap.label("pattern_length_inc")
    chain_edit_label = keymap.label("chain_edit")

    should_draw = True
    last_step = -1
    last_pattern = -1
    last_next_pattern = None
    last_playing = None
    last_ui_state = None

    while True:
        try:
            key = stdscr.get_wch()
        except curses.error:
            key = -1

        if key != -1:
            if not controller.handle_key(key):
                controller._stop_record_monitor()
                if seq.dirty:
                    seq.save_autosave()
                    seq.dirty = False
                return
            should_draw = True
        else:
            if controller._maybe_auto_open_drop_path():
                should_draw = True

        controller._tick_record_capture()
        if controller.record_overlay_active and not controller.record_capture_active:
            wants_monitor = controller.record_input_metering_enabled and not seq.playing
            if wants_monitor and not controller.record_monitor_running:
                controller._start_record_monitor()
                should_draw = True
            elif not wants_monitor and controller.record_monitor_running:
                controller._stop_record_monitor()
                controller.record_level_db = -60.0
                should_draw = True

        # Engine-duplex monitor path does not use a separate input stream callback,
        # so update meter values here while overlay monitoring is active.
        if (
            controller.record_overlay_active
            and controller.record_monitor_running
            and controller._record_monitor_stream is None
            and seq.engine.using_duplex
            and seq.engine.input_available
        ):
            db = float(seq.engine.get_input_level_db())
            controller.record_level_db = max(-60.0, min(0.0, db))
            controller.record_level_peak_db = controller.record_level_db
            controller.record_level_tick = int(controller.record_level_tick) + 1
            should_draw = True

        ui_state = (
            controller.cursor_x,
            controller.cursor_y,
            controller.nav.header.focus,
            controller.nav.header.section,
            controller.nav.header.param_index,
            controller.nav.pattern.focus,
            controller.nav.pattern.index,
            controller.nav.pattern.edit_active,
            controller.nav.active_tab,
            controller.nav.header.edit_active,
            controller.edit_mode,
            controller.audio_export_options_active,
            controller.audio_export_options_index,
            controller.audio_export_options["bit_depth"],
            controller.audio_export_options["sample_rate"],
            controller.audio_export_options["channels"],
            controller.audio_export_options.get("scope", "pattern"),
            controller.kit_export_options_active,
            controller.kit_export_options_index,
            controller.kit_export_options["bit_depth"],
            controller.kit_export_options["sample_rate"],
            controller.kit_export_options["channels"],
            controller.text_input_dialog_active,
            controller.text_input_dialog_message,
            controller.text_input_dialog_input,
            controller.text_input_dialog_index,
            controller.audio_track_params_dialog_active,
            controller.audio_track_params_dialog_track,
            controller.audio_track_params_dialog_index,
            controller.confirm_dialog_active,
            controller.confirm_dialog_message,
            controller.confirm_dialog_index,
            controller.pattern_menu_active,
            controller.pattern_menu_kind,
            controller.pattern_menu_index,
            controller.patterns_overlay_active,
            controller.patterns_overlay_index,
            controller.import_overlay_active,
            controller.import_overlay_index,
            controller.import_overlay_path,
            controller.import_overlay_can_delete_source,
            controller.import_target_drum_track,
            controller.import_target_audio_track,
            controller.chop_overlay_active,
            controller.chop_overlay_index,
            controller.record_overlay_active,
            tuple(controller.record_device_names),
            controller.record_device_index,
            tuple(src.get("label", "") for src in controller.record_input_sources),
            controller.record_input_source_index,
            controller.record_overlay_index,
            controller.record_action_index,
            controller.record_channels,
            controller.record_precount_enabled,
            controller.record_precount_pattern,
            round(controller.record_level_db, 1),
            controller.record_monitor_running,
            int(controller.record_level_tick),
            controller.record_monitor_info,
            controller.record_capture_active,
            controller.record_capture_stage,
            controller.record_capture_pattern,
            controller.record_capture_track,
            controller.drop_path_active,
            controller.drop_path_input,
            controller.file_browser_active,
            controller.file_browser_mode,
            controller.file_browser_path,
            tuple(item["name"] for item in controller.file_browser_items),
            controller.file_browser_index,
            controller.status_message,
            seq.bpm,
            seq.pattern_length[seq.view_pattern],
            seq.pattern_swing[seq.view_pattern],
            seq.pattern_humanize[seq.view_pattern],
            seq.midi_out_enabled,
            seq.pattern,
            seq.view_pattern,
            seq.next_pattern,
            seq.chain_enabled,
            tuple(seq.chain),
            seq.chain_pos,
            tuple(
                1 if (t < TRACKS - 1 and seq.seq_track_trigger_until[t] > time.perf_counter()) else 0
                for t in range(TRACKS)
            ),
            tuple(
                1 if (t < TRACKS - 1 and seq.audio_track_trigger_until[t] > time.perf_counter()) else 0
                for t in range(TRACKS)
            ),
        )
        if ui_state != last_ui_state:
            should_draw = True

        if (
            seq.step != last_step
            or seq.pattern != last_pattern
            or seq.next_pattern != last_next_pattern
            or seq.playing != last_playing
        ):
            should_draw = True

        if should_draw:
            if controller.drop_path_active:
                prompt_text = f"Import .wav path (auto-opens options, Esc cancels): {controller.drop_path_input}"
            elif controller.track_params_dialog_active:
                track_name = controller._track_params_dialog_track_label()
                prompt_text = texts.track_params_prompt(track_name, controller.track_params_dialog_index)
            elif controller.audio_track_params_dialog_active:
                track_name = controller._audio_track_params_dialog_track_label()
                prompt_text = texts.audio_track_params_prompt(track_name, controller.audio_track_params_dialog_index)
            elif controller.text_input_dialog_active:
                prompt_text = ""
            elif controller.confirm_dialog_active:
                prompt_text = ""
            else:
                prompt_text = ""

            draw(
                stdscr,
                seq,
                controller.cursor_x,
                controller.cursor_y,
                controller.nav,
                controller.edit_mode,
                prompt_text,
                controller.status_message if not controller.drop_path_active and not controller.import_overlay_active and not controller.chop_overlay_active and not controller.audio_export_options_active and not controller.kit_export_options_active and not controller.track_params_dialog_active and not controller.audio_track_params_dialog_active and not controller.text_input_dialog_active and not controller.confirm_dialog_active else "",
                controller.pattern_menu_active,
                controller.pattern_menu_kind,
                controller.pattern_menu_index,
                controller.patterns_overlay_active,
                controller.patterns_overlay_index,
                controller.import_overlay_active,
                controller.import_overlay_index,
                controller.import_overlay_path,
                controller.import_overlay_can_delete_source,
                controller.import_target_drum_track,
                controller.import_target_audio_track,
                controller.chop_overlay_active,
                controller.chop_overlay_index,
                controller.record_overlay_active,
                controller.record_device_names,
                controller.record_device_index,
                controller.record_input_sources,
                controller.record_input_source_index,
                controller.record_overlay_index,
                controller.record_action_index,
                controller.record_channels,
                controller.record_precount_enabled,
                controller.record_precount_pattern,
                controller.record_level_db,
                controller.record_monitor_running,
                controller.record_level_tick,
                controller.record_monitor_info,
                controller.record_capture_active,
                file_menu_label,
                controller.file_browser_active,
                controller.file_browser_mode,
                controller.file_browser_path,
                controller.file_browser_items,
                controller.file_browser_index,
                controller.audio_export_options_active,
                controller.audio_export_options,
                controller.audio_export_options_index,
                controller.kit_export_options_active,
                controller.kit_export_options,
                controller.kit_export_options_index,
                mode_key_label,
                tab_1_label,
                tab_2_label,
                tab_3_label,
                tab_4_label,
                tab_5_label,
                controller.export_eq_enabled,
                controller.export_tape_enabled,
                clear_key_label,
                length_dec_label,
                length_inc_label,
                ui_options,
                controller.track_params_dialog_active,
                controller.track_params_dialog_track,
                controller.track_params_dialog_index,
                controller.track_params_dialog_input,
                controller.audio_track_params_dialog_active,
                controller.audio_track_params_dialog_track,
                controller.audio_track_params_dialog_index,
                controller.text_input_dialog_active,
                controller.text_input_dialog_message,
                controller.text_input_dialog_input,
                controller.text_input_dialog_index,
                controller.confirm_dialog_active,
                controller.confirm_dialog_message,
                controller.confirm_dialog_index,
                theme
            )

            last_step = seq.step
            last_pattern = seq.pattern
            last_next_pattern = seq.next_pattern
            last_playing = seq.playing
            last_ui_state = ui_state
            should_draw = False

        time.sleep(0.002)
