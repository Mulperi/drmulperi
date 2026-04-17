import curses
import os
import shlex
import subprocess
import time
from urllib.parse import unquote, urlparse

from .config import (
    ACCENT_TRACK,
    FILE_MENU_ITEMS,
    GRID_COLS,
    GROUP_COL,
    LOAD_COL,
    PAN_COL,
    PREVIEW_COL,
    PATTERN_MENU_ITEMS,
    PATTERNS,
    PROB_COL,
    STEPS,
    TRACK_PITCH_COL,
    TRACKS,
)
from .keymap import Keymap, _event_tokens
from . import recorder


# Audio tab volume column.
AUDIO_VOLUME_COL = STEPS + 3


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
    header_focus,
    header_section,
    header_param,
    active_tab,
    header_edit_active,
    edit_mode,
    clear_confirm,
    esc_confirm,
    pattern_load_prompt,
    status_message,
    pattern_menu_active,
    pattern_menu_kind,
    pattern_menu_index,
    patterns_overlay_active,
    patterns_overlay_index,
    patterns_overlay_delete_confirm_index,
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
    clear_key_label,
    length_dec_label,
    length_inc_label,
    theme
):
    """Render full terminal UI frame from current sequencer/controller state."""
    stdscr.clear()
    h, w = stdscr.getmaxyx()

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

    if h < 16 or w < 80:
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
    grid_left = 2
    grid_right = w - 3
    grid_top = 2
    grid_bottom = h - 3
    draw_box(grid_left, grid_top, grid_right, grid_bottom, frame_attr)

    mode = {
        "velocity": "VELOCITY",
        "ratchet": "RATCHET",
        "blocks": "BLOCKS",
        "detune": "DETUNE",
    }.get(edit_mode, "VELOCITY")
    top_menus = [
        ("file", " FILE "),
        ("pattern", " PATTERN "),
        ("song", " SONG "),
        ("record", " STOP " if record_capture_active else " RECORD "),
        ("bpm", f" BPM:{seq.bpm} "),
        ("length", f" {seq.pattern_length[seq.view_pattern]} "),
        ("swing", f" ~{seq.current_pattern_swing_ui()} "),
        ("humanize", f" H:{seq.current_pattern_humanize()} "),
        ("pitch", f" {seq.pitch_semitones:+d}st "),
        ("mode", f" {mode} "),
        ("midi", " MIDI OUT "),
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
        if menu_key in {"file", "pattern"} and len(menu_label) > 2:
            safe_add(outer_top, menu_x + 1, menu_label[1], menu_attr | curses.A_UNDERLINE)
        menu_x += len(menu_label) + 1

    tabs = ["Sequencer", "Audio", "Mixer"]
    tx = 3
    for i, label in enumerate(tabs):
        tab_text = f"┌ {label} ┐"
        attr = theme["muted"]
        if i == active_tab:
            attr = theme["title"]
        if header_focus and header_section == "tabs" and i == active_tab:
            attr = attr | theme["selected"]
        safe_add(area_menubar, tx, tab_text, attr)
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

    controls_y = area_menubar

    grid_content_x = grid_left + 2
    playhead_y = grid_top + 1
    current_length = seq.pattern_length[seq.view_pattern]
    show_playhead = seq.playing and (seq.view_pattern == seq.pattern)
    x = grid_content_x
    safe_add(playhead_y, x, "  ", theme["text"])
    x += 2

    def col_cell_width(col):
        if col < STEPS:
            return 1
        if col == PREVIEW_COL:
            return 1
        if col == LOAD_COL:
            return 1
        if col == PAN_COL:
            return 2
        if col == AUDIO_VOLUME_COL:
            return 3
        if col == PROB_COL:
            return 4
        if col == GROUP_COL:
            return 1
        if col == TRACK_PITCH_COL:
            return 3
        return 3

    if active_tab == 0:
        # Sequencer view: reserve preview-slot width before step grid (next to track label).
        safe_add(playhead_y, x, " ", theme["text"])
        x += 1
        safe_add(playhead_y, x, " ", theme["divider"])
        x += 1
        step_x = x
        safe_add(playhead_y, step_x, " " * STEPS, theme["muted"])
        if show_playhead and 0 <= seq.step < STEPS:
            safe_add(playhead_y, step_x + seq.step, "v", theme["playhead"])
        if 1 <= current_length < STEPS:
            safe_add(playhead_y, step_x + current_length - 1, "|", theme["hint"])
    elif active_tab == 1:
        # Keep Audio rows aligned with sequencer rows; no heading on playhead line.
        pass
    else:
        safe_add(playhead_y, grid_content_x + 4, "Sequencer Tracks", theme["title"])
        safe_add(playhead_y, grid_content_x + 28, "Audio Tracks", theme["title"])
        safe_add(playhead_y, grid_content_x + 21, "│", theme["divider"])

    row_start = grid_top + 2
    visible_rows = TRACKS if active_tab == 0 else (TRACKS - 1)
    if active_tab == 0:
        track_order = [t for t in range(TRACKS - 1)]
    elif active_tab == 1:
        track_order = (
            [t for t in range(TRACKS - 1) if seq.audio_track_mode[t] == 0]
            + [t for t in range(TRACKS - 1) if seq.audio_track_mode[t] == 1]
        )
    else:
        track_order = [t for t in range(TRACKS - 1)]
    first_song_row = None
    if active_tab == 1:
        for idx, tr in enumerate(track_order):
            if seq.audio_track_mode[tr] == 1:
                first_song_row = idx
                break
    now_pc = time.perf_counter()
    for row_idx in range(visible_rows):
        y = row_start + row_idx
        if y >= grid_bottom:
            continue
        t = row_idx if active_tab == 0 else track_order[row_idx]

        row_attr = theme["accent"] if t == ACCENT_TRACK else theme["text"]
        if seq.muted_rows[t]:
            row_attr = theme["muted"]
        if active_tab == 1 and seq.audio_track_mode[t] == 1:
            row_attr = theme["chain_on"]
        # No extra separator line in Audio view; ordering + color indicate grouping.

        x = grid_content_x
        if active_tab == 1:
            row_label = f"{t+1} "
        elif active_tab == 2:
            row_label = f"{t+1} "
        else:
            row_label = "A " if t == ACCENT_TRACK else f"{t+1} "
        label_attr = row_attr
        trigger_arr = getattr(
            seq,
            "audio_track_trigger_until" if active_tab == 1 else "seq_track_trigger_until",
            [0.0] * TRACKS,
        )
        if t < TRACKS - 1 and not seq.muted_rows[t] and trigger_arr[t] > now_pc:
            label_attr = theme["playhead"]
        safe_add(y, x, row_label, label_attr)
        x += len(row_label)

        def velocity_attr(value):
            if value <= 0:
                return theme["muted"]
            if value < 4:
                return theme["velocity_low"]
            return theme["velocity_high"]

        if active_tab == 1:
            sample_name = seq.get_audio_track_name(seq.view_pattern, t)
            ch_tag = "◯◯" if seq.get_audio_track_channels(seq.view_pattern, t) >= 2 else "◯"
            sample_width = 30
            sample_field = f"{ch_tag} {sample_name}"[:sample_width].ljust(sample_width)
            safe_add(y, x, "  ", theme["divider"])
            x += 2
            body = f"[{sample_field}]" if (cursor_x == 0 and cursor_y == row_idx) else f" {sample_field} "
            attr = row_attr | (theme["selected"] if (cursor_x == 0 and cursor_y == row_idx) else 0)
            safe_add(y, x, body, attr, transform_case=False)
            x += len(body)
            cols = [
                (PREVIEW_COL, "▶"),
                (LOAD_COL, "↓"),
                (PAN_COL, f"P{seq.get_audio_track_pan(seq.view_pattern, t)}"),
                (AUDIO_VOLUME_COL, f"V{seq.get_audio_track_volume(seq.view_pattern, t)}"),
                (PROB_COL, "●"),
                (GROUP_COL, "X"),
                (TRACK_PITCH_COL, f"↔{seq.get_audio_track_shift(seq.view_pattern, t):02d}"),
            ]
            for col, char in cols:
                safe_add(y, x, "| ", theme["divider"])
                x += 2
                cell_w = col_cell_width(col)
                cell_attr = (theme["record"] if col == PROB_COL else row_attr) | (theme["selected"] if (cursor_x == col and cursor_y == row_idx) else 0)
                safe_add(y, x, f" {char:>{cell_w}} ", cell_attr)
                x += cell_w + 2
        elif active_tab == 2:
            seq_pan = seq.seq_track_pan[t]
            seq_vol = seq.seq_track_volume[t]
            aud_pan = seq.get_audio_track_pan(seq.view_pattern, t)
            aud_vol = seq.get_audio_track_volume(seq.view_pattern, t)
            safe_add(y, x, "  ", theme["divider"])
            x += 2

            mix_cells = [
                (0, f"P{seq_pan}", row_attr),
                (1, f"V{seq_vol}", row_attr),
                (2, f"P{aud_pan}", row_attr),
                (3, f"V{aud_vol}", row_attr),
            ]
            for idx, text, base_attr in mix_cells:
                if idx == 2:
                    safe_add(y, x, " │ ", theme["divider"])
                    x += 3
                elif idx > 0:
                    safe_add(y, x, "  ", theme["divider"])
                    x += 2
                cell_attr = base_attr | (theme["selected"] if (cursor_x == idx and cursor_y == row_idx) else 0)
                safe_add(y, x, f"{text:>2}", cell_attr)
                x += 2
        else:
            # Sequencer view: preview button is shown next to track label (before steps).
            preview_char = "▶" if t != ACCENT_TRACK else " "
            preview_attr = row_attr
            if cursor_x == PREVIEW_COL and cursor_y == t:
                preview_attr = preview_attr | theme["selected"]
            safe_add(y, x, f"{preview_char:>1}", preview_attr)
            x += 1
            safe_add(y, x, " ", theme["divider"])
            x += 1

            # Sequencer grid: compact 1-char step cells.
            for s in range(STEPS):
                val = seq.grid[seq.view_pattern][t][s]
                ratchet = seq.ratchet_grid[seq.view_pattern][t][s]
                detune = seq.detune_grid[seq.view_pattern][t][s]
                if edit_mode == "blocks":
                    char = "▪" if val > 0 else "."
                elif edit_mode == "ratchet":
                    char = str(ratchet if val > 0 else ".")
                elif edit_mode == "detune":
                    char = str(detune) if val > 0 else "."
                else:
                    char = str(val) if val > 0 else "."

                if t == ACCENT_TRACK:
                    if edit_mode == "blocks":
                        char = "▪" if val > 0 else "."
                    else:
                        char = "1" if val > 0 else "."
                    cell_attr = theme["accent"] | (curses.A_BOLD if val > 0 else 0)
                else:
                    cell_attr = velocity_attr(val)

                if s >= seq.pattern_length[seq.view_pattern]:
                    cell_attr = theme["muted"]
                elif val == 0 and (s % 4 == 0):
                    # Highlight each beat-start dot so the rhythm grid is easier to read.
                    cell_attr = theme["text"]
                if cursor_x == s and cursor_y == t:
                    cell_attr = cell_attr | theme["selected"]
                safe_add(y, x, char, cell_attr)
                x += 1

            # Parameter area.
            safe_add(y, x, " ", theme["divider"])
            x += 1
            param_cols = [LOAD_COL, PAN_COL, PROB_COL, GROUP_COL, TRACK_PITCH_COL]
            for s in param_cols:
                if s == LOAD_COL:
                    char = "↓" if t != ACCENT_TRACK else ""
                    cell_attr = row_attr
                elif s == PAN_COL:
                    char = f"P{seq.seq_track_pan[t]}" if t != ACCENT_TRACK else ""
                    cell_attr = row_attr
                elif s == PROB_COL:
                    char = f"%{seq.seq_track_probability[t]}" if t != ACCENT_TRACK else ""
                    cell_attr = row_attr
                elif s == GROUP_COL:
                    char = str(seq.seq_track_group[t]) if t != ACCENT_TRACK else ""
                    cell_attr = row_attr
                else:
                    char = f"{seq.seq_track_pitch[t] + 12}" if t != ACCENT_TRACK else ""
                    cell_attr = row_attr

                safe_add(y, x, "|", theme["divider"])
                x += 1
                cell_w = col_cell_width(s)
                body = f"{char:>{cell_w}}"
                if cursor_x == s and cursor_y == t:
                    cell_attr = cell_attr | theme["selected"]
                safe_add(y, x, body, cell_attr)
                x += len(body)

            mute_mark = "M" if seq.muted_rows[t] else " "
            safe_add(y, x, f" {mute_mark}", row_attr)

    prompt_line = ""
    help_line = ""
    prompt_transform_case = True

    def current_preview_name():
        """Return the current sample name for preview help text in Audio and Sequencer views."""
        if active_tab == 1:
            if cursor_y < TRACKS - 1 and track_order:
                active_track = track_order[max(0, min(len(track_order) - 1, cursor_y))]
                return str(seq.get_audio_track_name(seq.view_pattern, active_track))
            return "-"
        if cursor_y < TRACKS - 1 and 0 <= cursor_y < len(seq.engine.sample_names):
            return str(seq.engine.sample_names[cursor_y])
        return "Accent track"
    if header_focus:
        if header_section == "tabs":
            help_line = "Tabs: Left/Right switch view tabs. Down enters header controls."
        elif header_param == "patterns":
            help_line = "Enter opens pattern overlay."
        elif header_param == "length":
            if header_edit_active:
                help_line = "Header edit: Left/Right or Up/Down changes LEN. Enter exits edit."
            else:
                help_line = "Pattern length."
        elif header_param == "bpm":
            if header_edit_active:
                help_line = "Header edit: Left/Right or Up/Down changes BPM. Enter exits edit."
            else:
                help_line = "Enter edits BPM."
        elif header_param == "swing":
            if header_edit_active:
                help_line = "Header edit: Left/Right or Up/Down changes swing. Enter exits edit."
            else:
                help_line = "Enter edits swing."
        elif header_param == "humanize":
            if header_edit_active:
                help_line = "Header edit: Left/Right or Up/Down changes humanize. Enter exits edit."
            else:
                help_line = "Pattern humanize."
        elif header_param == "mode":
            help_line = "Enter rotates mode (velocity/ratchet/blocks/detune)."
        elif header_param == "midi":
            help_line = "Enter toggles MIDI OUT."
        elif header_param == "file":
            help_line = "Enter opens File menu."
        elif header_param == "pattern":
            help_line = "Enter opens Pattern menu."
        elif header_param == "song":
            help_line = "Enter toggles SONG mode."
        elif header_param == "record":
            help_line = "Enter opens Record menu."
        elif header_param == "chain_set":
            help_line = "Enter sets song order."
        else:
            if header_edit_active:
                help_line = "Header edit: Left/Right or Up/Down tunes pitch. Enter exits edit."
            else:
                help_line = "Enter edits pitch."
    elif active_tab == 2 and cursor_x == 0:
        help_line = "Mixer: Sequencer track pan (1-9). Type number to set."
    elif active_tab == 2 and cursor_x == 1:
        help_line = "Mixer: Sequencer track volume (0-9). Type number to set."
    elif active_tab == 2 and cursor_x == 2:
        help_line = "Mixer: Audio track pan (1-9). Type number to set."
    elif active_tab == 2 and cursor_x == 3:
        help_line = "Mixer: Audio track volume (0-9). Type number to set."
    elif active_tab == 1 and cursor_x == 0:
        help_line = "Toggle track mode: Pattern/Song. Song tracks play only when SONG mode is ON."
    elif active_tab == 1 and cursor_x == PREVIEW_COL:
        help_line = f"Preview sample: {current_preview_name()}"
        prompt_transform_case = False
    elif active_tab == 1 and cursor_x == LOAD_COL:
        help_line = "Load sample"
    elif active_tab == 1 and cursor_x == PAN_COL:
        help_line = "Pan: 1=left, 5=center, 9=right. Type 1-9 to set."
    elif active_tab == 1 and cursor_x == AUDIO_VOLUME_COL:
        help_line = "Volume: 0..9. Type 0-9 to set."
    elif active_tab == 1 and cursor_x == PROB_COL:
        help_line = "Record input device / level monitor (2-pass capture)"
    elif active_tab == 1 and cursor_x == GROUP_COL:
        help_line = "Clear current audio track sample"
    elif active_tab == 1 and cursor_x == TRACK_PITCH_COL:
        help_line = "Start shift: 0..50 (12=center). 1 step = 5ms. Higher trims sample start, lower adds delay."
    elif active_tab == 1 and cursor_y < TRACKS - 1:
        active_track = track_order[max(0, min(len(track_order) - 1, cursor_y))]
        help_line = f"AUDIO TRACK SAMPLE: {seq.get_audio_track_name(seq.view_pattern, active_track)}"
        prompt_transform_case = False
    elif cursor_x == PREVIEW_COL:
        help_line = f"Preview sample: {current_preview_name()}"
        prompt_transform_case = False
    elif cursor_x == LOAD_COL:
        help_line = "Load sample"
    elif cursor_x == PAN_COL:
        help_line = "Pan: 1=left, 5=center, 9=right. Type 1-9 to set."
    elif cursor_x == PROB_COL:
        help_line = "% Probability: chance that a step triggers on this track (0-100). Type digits to set."
    elif cursor_x == GROUP_COL:
        help_line = "Group: 0=off, 1-9=mute group. Tracks with same group choke each other."
    elif cursor_x == TRACK_PITCH_COL:
        help_line = "Track pitch: 0..24 scale (12 = no shift). Type digits to set."
    elif cursor_y < TRACKS - 1:
        help_line = f"SAMPLE: {seq.engine.sample_names[cursor_y]}  (Enter on ▶ preview, Enter on ↓ load)"
        prompt_transform_case = False
    else:
        help_line = "SAMPLE: Accent track (no sample file)"

    if clear_confirm:
        prompt_line = f"Clear current pattern? Press {clear_key_label} again to confirm."
    elif esc_confirm:
        prompt_line = "Press Esc again to exit."
    elif pattern_load_prompt:
        prompt_line = pattern_load_prompt
    elif status_message:
        prompt_line = f"{status_message} | {help_line}"
    else:
        prompt_line = help_line

    if prompt_line:
        prompt_col = 0
        safe_add(area_prompt, prompt_col, prompt_line[:max(0, w - 1)], theme["prompt"], transform_case=prompt_transform_case)

    # Always-visible current sample label at bottom-right of sequencer area.
    if active_tab == 1 and cursor_y < TRACKS - 1 and track_order:
        active_track = track_order[max(0, min(len(track_order) - 1, cursor_y))]
        current_sample_name = seq.get_audio_track_name(seq.view_pattern, active_track)
    elif cursor_y < TRACKS - 1:
        current_sample_name = seq.engine.sample_names[cursor_y]
    else:
        current_sample_name = "Accent track"
    sample_label = f"SAMPLE: {current_sample_name}"
    sample_y = grid_bottom - 1
    sample_x = max(grid_left + 2, grid_right - len(sample_label) - 1)
    safe_add(sample_y, sample_x, sample_label[: max(0, grid_right - sample_x)], theme["muted"], transform_case=False)

    if pattern_menu_active:
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

    if patterns_overlay_active:
        count = seq.pattern_count()
        title = "PATTERNS (A:Add, D:Duplicate, X:Delete)"
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
            confirm_tag = "X!" if i == patterns_overlay_delete_confirm_index else "  "
            rows.append(
                f"{i+1:>2}. {view_tag} {play_tag} {confirm_tag} {state} LEN:{length:>2} SW:{swing:>2} HITS:{hits:>3}"
            )
            row_is_empty.append(is_empty)
        if not rows:
            rows = ["(no patterns)"]
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
            safe_add(y, box_left + 2, rows[i][: box_width - 4], attr)

    if chop_overlay_active:
        title = "IMPORT CHOPS (Space preview, Enter action)"
        rows = []
        for i in range(8):
            name = "-"
            if i < len(seq.chop_preview_names):
                name = seq.chop_preview_names[i]
            rows.append(f"{i+1:>2}. ▶ {name}")
        rows.append("[ Use Samples ]")
        rows.append("[ Cancel ]")
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
        safe_add(box_top + 2, box_left + 2, f"Source: {src}"[: box_width - 4], theme["muted"], transform_case=False)
        for i, row in enumerate(rows):
            y = box_top + 3 + i
            if y >= box_bottom:
                break
            attr = theme["text"]
            if i == chop_overlay_index:
                attr = attr | theme["selected"]
            safe_add(y, box_left + 2, row[: box_width - 4], attr)

    if import_overlay_active:
        title = "IMPORT AUDIO (Arrows move, <-/-> track, Space preview, Enter select)"
        src = os.path.basename(import_overlay_path) if import_overlay_path else "-"
        audio_mode_label = "Song" if (0 <= import_target_audio_track < (TRACKS - 1) and seq.audio_track_mode[import_target_audio_track] == 1) else f"Pattern {seq.view_pattern + 1}"
        rows = [
            "Chop audio to 8 drum tracks",
            f"Import to single drum track: {import_target_drum_track + 1}",
            f"Import to audio track: {import_target_audio_track + 1} ({audio_mode_label})",
            "[ Cancel ]",
        ]
        if import_overlay_can_delete_source:
            rows.append("[ Cancel + Delete Recording ]")
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
        safe_add(box_top + 2, box_left + 2, f"Source: {src}"[: box_width - 4], theme["muted"], transform_case=False)
        for i, row in enumerate(rows):
            y = box_top + 3 + i
            if y >= box_bottom:
                break
            attr = theme["text"]
            if i == import_overlay_index:
                attr = attr | theme["selected"]
            safe_add(y, box_left + 2, row[: box_width - 4], attr)

    if record_overlay_active:
        title = "RECORD (Up/Down row, Left/Right change, Enter action)"
        devices = record_device_names if record_device_names else ["(no input devices)"]
        selected_dev = devices[record_device_index] if devices else "(no input devices)"
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

        meter_y = box_bottom - 2
        meter_left = box_left + 2
        meter_width = max(10, box_width - 26)
        norm = max(0.0, min(1.0, (record_level_db + 60.0) / 60.0))
        fill = int(round(norm * meter_width))
        hot_start = max(0, int(round(meter_width * 0.82)))
        # DEBUG METER FIELDS: keep tick/monitor info visible to diagnose input callback path quickly.
        if record_monitor_running:
            peak_db = float(getattr(seq, "record_level_peak_db", -60.0)) if hasattr(seq, "record_level_peak_db") else None
            if peak_db is None:
                db_text = f"{record_level_db:>5.1f} dBFS t:{int(record_level_tick)}"
            else:
                db_text = f"{record_level_db:>5.1f} dBFS pk:{peak_db:>5.1f} t:{int(record_level_tick)}"
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
        # DEBUG METER FIELDS: includes active monitor stream device/samplerate/channels.
        tail = f"{db_text} {record_monitor_info}".strip()
        safe_add(meter_y, meter_x + meter_width + 2, tail[: max(0, box_width - 4)], theme["hint"])
        btn_y = box_bottom - 1
        record_label = "[ Stop ]" if record_capture_active else "[ Record ]"
        action_row = (record_overlay_index == 5)
        cancel_attr = theme["text"] if (action_row and record_action_index == 0) else theme["muted"]
        record_attr = theme["record"] if (action_row and record_action_index == 1) else theme["muted"]
        safe_add(btn_y, box_left + 2, "[ Cancel ]", cancel_attr)
        rec_x = box_right - len(record_label) - 2
        safe_add(btn_y, rec_x, record_label, record_attr)

    if file_browser_active:
        if file_browser_mode == "pattern":
            mode_name = "PATTERN"
        elif file_browser_mode in ["sample", "audio_track"]:
            mode_name = "SAMPLE"
        else:
            mode_name = "KIT"
        title = f"{mode_name} BROWSER (Enter open/select, <-/-> or Backspace up, Esc close)"
        if file_browser_mode in ["sample", "audio_track"]:
            title = f"{mode_name} BROWSER (Space preview, Enter select, <-/-> up/down, Esc close)"
        visible_items = file_browser_items if file_browser_items else [{"name": "(empty)", "is_dir": False, "is_parent": False}]
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
        path_line = f"Path: {file_browser_path}"
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

    if audio_export_options_active:
        title = "AUDIO EXPORT OPTIONS (Arrows/Space change, Enter export, Esc cancel)"
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
        safe_add(box_top + 2, box_left + 2, "Use arrows to pick values.", theme["muted"])

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
            [("8-bit  ", 8), ("16-bit", 16)],
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
        safe_add(box_top + 8, box_left + 4, "[ Export -> Filename ]", export_attr)

    if kit_export_options_active:
        title = "KIT EXPORT OPTIONS (Arrows/Space change, Enter export, Esc cancel)"
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
        safe_add(box_top + 2, box_left + 2, "Use arrows to pick values.", theme["muted"])

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
            [("8-bit", 8), ("16-bit", 16)],
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
        safe_add(box_top + 7, box_left + 4, "[ Export Kit -> Folder ]", export_attr)

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
    project_label = f"PROJECT:{project_dir}"
    project_x = max(outer_left + 2, outer_right - len(project_label) - 2)
    safe_add(footer_row, project_x, project_label, theme["muted"])

    stdscr.refresh()

# ---------- CONTROLLER ----------
class Controller:
    """Owns transient UI/dialog state and translates key input into actions."""
    def __init__(self, sequencer, keymap):
        self.seq = sequencer
        self.keymap = keymap
        self.cursor_x = 0
        self.cursor_y = 0
        self.edit_mode = "blocks"
        self.clear_confirm = False
        self.esc_confirm = False
        self.pattern_save_active = False
        self.pattern_save_input = ""
        self.pattern_load_active = False
        self.pattern_load_input = ""
        self.kit_load_active = False
        self.kit_load_input = ""
        self.project_save_as_active = False
        self.project_save_as_input = ""
        self.audio_export_active = False
        self.audio_export_input = ""
        self.audio_export_options_active = False
        self.audio_export_options = {
            "bit_depth": 16,
            "sample_rate": self.seq.engine.sr,
            "channels": 2,
            "scope": "pattern",
        }
        self.audio_export_options_index = 0
        self.kit_export_active = False
        self.kit_export_input = ""
        self.kit_export_options_active = False
        self.kit_export_options = {
            "bit_depth": 16,
            "sample_rate": self.seq.engine.sr,
            "channels": 1,
        }
        self.kit_export_options_index = 0
        self.humanize_edit_active = False
        self.humanize_edit_input = ""
        self.probability_edit_active = False
        self.probability_edit_input = ""
        self.chain_edit_active = False
        self.chain_edit_input = ""
        self.swing_edit_active = False
        self.swing_edit_input = ""
        self.track_rename_active = False
        self.track_rename_input = ""
        self.pattern_menu_active = False
        self.pattern_menu_kind = "file"
        self.pattern_menu_index = 0
        self.file_browser_active = False
        self.file_browser_mode = None
        self.file_browser_target_track = None
        self.file_browser_path = os.getcwd()
        self.file_browser_items = []
        self.file_browser_index = 0
        self.header_focus = False
        self.header_section = "params"
        self.header_edit_active = False
        self.active_tab = 0
        self.header_params = ["file", "pattern", "song", "record", "bpm", "length", "swing", "humanize", "pitch", "mode", "midi"]
        self.header_param_index = 0
        self.inline_value_buffer = ""
        self.inline_value_target = None  # (row, col)
        self.inline_value_time = 0.0
        self.patterns_overlay_active = False
        self.patterns_overlay_index = 0
        self.patterns_overlay_delete_confirm_index = -1
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
        self.clear_audio_confirm_active = False
        self.clear_audio_force_confirm_active = False
        self.clear_audio_confirm_pattern = 0
        self.clear_audio_confirm_track = 0
        self.clear_audio_confirm_path = None
        self.clipboard_import_confirm_active = False
        self.clipboard_import_text = ""
        self.clipboard_import_count = 0
        self.status_message = ""
        self.pattern_actions = [f"pattern_{i+1}" for i in range(PATTERNS)]

    def move_cursor(self, dx, dy):
        self.cursor_x = (self.cursor_x + dx) % GRID_COLS
        self.cursor_y = (self.cursor_y + dy) % TRACKS

    def _sequencer_nav_cols(self):
        """Sequencer navigation order matching visual layout (preview, steps, params)."""
        return [PREVIEW_COL] + list(range(STEPS)) + [LOAD_COL, PAN_COL, PROB_COL, GROUP_COL, TRACK_PITCH_COL]

    def _sequencer_beat_cols(self):
        """Return beat-start step columns for current visible pattern length."""
        try:
            current_len = int(self.seq.pattern_length[self.seq.view_pattern])
        except Exception:
            current_len = STEPS
        step_span = max(1, min(STEPS, current_len))
        cols = list(range(0, step_span, 4))
        return cols if cols else [0]

    def _cycle_edit_mode(self):
        """Rotate sequencer edit mode through all available step views."""
        modes = ["velocity", "ratchet", "blocks", "detune"]
        try:
            idx = modes.index(self.edit_mode)
        except ValueError:
            idx = 0
        self.edit_mode = modes[(idx + 1) % len(modes)]

    def _set_active_tab(self, tab_index):
        """Switch active top tab and clamp cursor for that view."""
        self.active_tab = max(0, min(2, int(tab_index)))
        if self.active_tab == 0 and self.cursor_x == AUDIO_VOLUME_COL:
            self.cursor_x = PROB_COL
        if self.active_tab in [1, 2]:
            self.cursor_y = min(self.cursor_y, TRACKS - 2)
        if self.active_tab == 1 and self.cursor_x > TRACK_PITCH_COL:
            self.cursor_x = PREVIEW_COL
        if self.active_tab == 2 and self.cursor_x > 3:
            self.cursor_x = 0

    def _tracks_order(self):
        """Return display order for Audio view (Pattern lanes first, Song lanes after)."""
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
            self.status_message = "Accent track has no parameter here"
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
        if col == PROB_COL:
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

        if col == PAN_COL:
            if value > 0:
                self.seq.set_audio_track_pan(self.seq.view_pattern, track_idx, max(1, min(9, value)))
        elif col == AUDIO_VOLUME_COL:
            self.seq.set_audio_track_volume(self.seq.view_pattern, track_idx, max(0, min(9, value)))
        elif col == TRACK_PITCH_COL:
            self.seq.set_audio_track_shift(self.seq.view_pattern, track_idx, max(0, min(50, value)))

    def _close_pattern_dialog(self):
        self.pattern_load_active = False
        self.pattern_load_input = ""

    def _close_pattern_save_dialog(self):
        self.pattern_save_active = False
        self.pattern_save_input = ""

    def _close_kit_dialog(self):
        self.kit_load_active = False
        self.kit_load_input = ""

    def _close_project_save_as_dialog(self):
        self.project_save_as_active = False
        self.project_save_as_input = ""

    def _close_audio_export_dialog(self):
        self.audio_export_active = False
        self.audio_export_input = ""
        self.audio_export_options_active = False

    def _close_audio_export_options_dialog(self):
        self.audio_export_options_active = False

    def _close_kit_export_dialog(self):
        self.kit_export_active = False
        self.kit_export_input = ""
        self.kit_export_options_active = False

    def _close_kit_export_options_dialog(self):
        self.kit_export_options_active = False

    def _close_humanize_dialog(self):
        self.humanize_edit_active = False
        self.humanize_edit_input = ""

    def _close_probability_dialog(self):
        self.probability_edit_active = False
        self.probability_edit_input = ""

    def _close_chain_dialog(self):
        self.chain_edit_active = False
        self.chain_edit_input = ""

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
            self.status_message = "Select a .wav file to import"
            return False
        self.import_overlay_active = True
        self.import_overlay_index = 0
        self.import_overlay_path = src
        self.import_overlay_can_delete_source = bool(can_delete_source)
        self.drop_path_active = False
        self.drop_path_input = ""
        if self.active_tab == 1:
            default_track = self._track_for_row(self.cursor_y)
        else:
            default_track = self.cursor_y if 0 <= self.cursor_y < (TRACKS - 1) else 0
        self.import_target_drum_track = default_track
        self.import_target_audio_track = default_track
        self.status_message = f"Import source ready: {os.path.basename(src)}"
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
            self.status_message = f"Browse failed: {exc}"
            entries = []

        dirs = []
        files = []
        for e in entries:
            if e.name.startswith("."):
                continue
            if e.is_dir(follow_symlinks=False):
                dirs.append(e)
            elif e.is_file(follow_symlinks=False):
                if self.file_browser_mode == "pattern" and e.name.lower().endswith(".json"):
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
        self.pattern_load_active = False
        self.pattern_load_input = ""
        self.kit_load_active = False
        self.kit_load_input = ""
        self.project_save_as_active = False
        self.project_save_as_input = ""
        self.audio_export_active = False
        self.audio_export_input = ""
        self.audio_export_options_active = False
        self.kit_export_active = False
        self.kit_export_input = ""
        self.kit_export_options_active = False
        self.humanize_edit_active = False
        self.humanize_edit_input = ""
        self.probability_edit_active = False
        self.probability_edit_input = ""
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

        if self.file_browser_mode == "kit":
            return

        if self.file_browser_mode == "sample":
            track = self.file_browser_target_track
            if track is None:
                self.status_message = "No target track selected"
                self._close_file_browser()
                return
            ok, message = self.seq.load_single_sample_to_track(track, item["path"])
            self.status_message = message
            self._close_file_browser()
            return

        if self.file_browser_mode == "audio_track":
            track = self.file_browser_target_track
            if track is None:
                self.status_message = "No target track selected"
                self._close_file_browser()
                return
            ok, message = self.seq.load_audio_track_sample(self.seq.view_pattern, track, item["path"])
            self.status_message = message
            self._close_file_browser()
            return

    def _tick_record_capture(self):
        recorder.tick_record_capture(self)

    def _close_swing_dialog(self):
        self.swing_edit_active = False
        self.swing_edit_input = ""

    def _close_track_rename_dialog(self):
        self.track_rename_active = False
        self.track_rename_input = ""

    def _open_clear_audio_confirm(self, pattern_index, track):
        """Open Y/N confirmation prompt for clearing an audio track sample."""
        self.clear_audio_confirm_active = True
        self.clear_audio_force_confirm_active = False
        self.clear_audio_confirm_pattern = int(pattern_index)
        self.clear_audio_confirm_track = int(track)
        self.clear_audio_confirm_path = self.seq.get_audio_track_path(pattern_index, track)

    def _close_clipboard_import_confirm(self):
        """Close clipboard-import confirmation prompt state."""
        self.clipboard_import_confirm_active = False
        self.clipboard_import_text = ""
        self.clipboard_import_count = 0

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
        self.header_focus = True
        self.header_section = "params"
        self.header_edit_active = False
        try:
            self.header_param_index = self.header_params.index(kind)
        except ValueError:
            self.header_param_index = 0

    def _run_pattern_menu_action(self):
        if self.pattern_menu_kind == "pattern":
            if self.pattern_menu_index == 0:
                self.patterns_overlay_active = True
                self.patterns_overlay_index = max(0, min(self.seq.pattern_count() - 1, self.seq.view_pattern))
                self.patterns_overlay_delete_confirm_index = -1
                ok, message = True, ""
            elif self.pattern_menu_index == 1:
                clip_text = _read_system_clipboard_text()
                ok_parse, parse_message, parsed = self.seq.parse_patterns_from_text(clip_text)
                if not ok_parse:
                    ok, message = False, f"Clipboard import failed: {parse_message}"
                else:
                    self.clipboard_import_confirm_active = True
                    self.clipboard_import_text = clip_text
                    self.clipboard_import_count = len(parsed)
                    ok, message = True, ""
            elif self.pattern_menu_index == 2:
                self.seq.clear_current_pattern()
                ok, message = True, f"Cleared pattern {self.seq.view_pattern + 1}"
            elif self.pattern_menu_index == 3:
                ok, message = self.seq.copy_current_pattern()
            elif self.pattern_menu_index == 4:
                ok, message = self.seq.paste_to_current_pattern()
            else:
                ok, message = False, "Invalid Pattern menu option"
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
                ok, message = True, f"Saved {os.path.basename(self.seq.pattern_path)}"
            except Exception as exc:
                ok, message = False, f"Save failed: {exc}"
        elif self.pattern_menu_index == 3:
            self.project_save_as_active = True
            self.project_save_as_input = ""
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.audio_export_active = False
            self.audio_export_input = ""
            self.audio_export_options_active = False
            self.chain_edit_active = False
            self.chain_edit_input = ""
            self.swing_edit_active = False
            self.swing_edit_input = ""
            self.humanize_edit_active = False
            self.humanize_edit_input = ""
            self.probability_edit_active = False
            self.probability_edit_input = ""
            self.kit_export_active = False
            self.kit_export_input = ""
            self.kit_export_options_active = False
            ok, message = True, ""
        elif self.pattern_menu_index == 4:
            self.kit_export_options_active = True
            self.kit_export_options_index = 0
            self.kit_export_options = {
                "bit_depth": 16,
                "sample_rate": self.seq.engine.sr,
                "channels": 1,
            }
            self.kit_export_active = False
            self.kit_export_input = ""
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
            self.audio_export_active = False
            self.audio_export_input = ""
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.project_save_as_active = False
            self.project_save_as_input = ""
            self.chain_edit_active = False
            self.chain_edit_input = ""
            self.swing_edit_active = False
            self.swing_edit_input = ""
            self.humanize_edit_active = False
            self.humanize_edit_input = ""
            self.probability_edit_active = False
            self.probability_edit_input = ""
            self.kit_export_active = False
            self.kit_export_input = ""
            self.kit_export_options_active = False
            ok, message = True, ""
        else:
            ok, message = False, "Invalid File menu option"
        self.status_message = message

    def handle_key(self, key):
        """Handle a single key event. Returns False when app should exit."""
        event_tokens = _event_tokens(key)
        key_code = key if isinstance(key, int) else ord(key)
        if self.active_tab == 0 and self.cursor_x == AUDIO_VOLUME_COL:
            self.cursor_x = PROB_COL
        if key_code != 27 and self.esc_confirm:
            self.esc_confirm = False
        if self.status_message and key_code != -1:
            self.status_message = ""
        if self.active_tab in [1, 2] and self.cursor_y >= (TRACKS - 1):
            self.cursor_y = TRACKS - 2

        if self.clear_audio_confirm_active:
            if key_code == 27:
                self.clear_audio_confirm_active = False
                self.clear_audio_force_confirm_active = False
                self.status_message = "Clear canceled"
                return True
            if self.clear_audio_force_confirm_active:
                if isinstance(key, str) and key.lower() in ["y", "n"]:
                    if key.lower() == "y":
                        ok, message = self.seq.force_delete_audio_path(self.clear_audio_confirm_path)
                        self.status_message = message
                    else:
                        self.status_message = "Force delete canceled (file kept)"
                    self.clear_audio_confirm_active = False
                    self.clear_audio_force_confirm_active = False
                    return True
            else:
                if isinstance(key, str) and key.lower() in ["y", "n"]:
                    delete_file = (key.lower() == "y")
                    ok, message, needs_force = self.seq.clear_audio_track_sample(
                        self.clear_audio_confirm_pattern,
                        self.clear_audio_confirm_track,
                        delete_file=delete_file,
                    )
                    self.status_message = message
                    if needs_force:
                        self.clear_audio_force_confirm_active = True
                    else:
                        self.clear_audio_confirm_active = False
                        self.clear_audio_force_confirm_active = False
                    return True
            return True

        if self.clipboard_import_confirm_active:
            if key_code == 27:
                self._close_clipboard_import_confirm()
                self.status_message = "Clipboard import canceled"
                return True
            if isinstance(key, str) and key.lower() in ["y", "n"]:
                if key.lower() == "y":
                    ok, message = self.seq.import_patterns_from_text(self.clipboard_import_text)
                    self.status_message = message
                else:
                    self.status_message = "Clipboard import canceled"
                self._close_clipboard_import_confirm()
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
                    self.status_message = "Record menu closed"
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
                        self.status_message = "Record menu closed"
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
                self.status_message = "Import canceled"
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
                    self.status_message = "Import canceled"
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
                            self.status_message = "Import canceled and recording deleted"
                        else:
                            self.status_message = "Recording file was already missing"
                    except Exception as exc:
                        self.status_message = f"Delete failed: {exc}"
                    return True
                self._close_import_overlay()
                self.status_message = "Import canceled"
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
                self.status_message = "Import canceled"
                return True
            return True

        if self.drop_path_active:
            if key_code == 27:
                self.drop_path_active = False
                self.drop_path_input = ""
                self.status_message = "Drop canceled"
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
                self.patterns_overlay_delete_confirm_index = -1
                return True
            if key_code == curses.KEY_UP:
                if count > 0:
                    self.patterns_overlay_index = (self.patterns_overlay_index - 1) % count
                self.patterns_overlay_delete_confirm_index = -1
                return True
            if key_code == curses.KEY_DOWN:
                if count > 0:
                    self.patterns_overlay_index = (self.patterns_overlay_index + 1) % count
                self.patterns_overlay_delete_confirm_index = -1
                return True
            if key_code in [10, 13, curses.KEY_ENTER]:
                if count > 0:
                    self.seq.select_pattern(self.patterns_overlay_index)
                self.patterns_overlay_delete_confirm_index = -1
                return True
            if key_code == 32:
                if not self.seq.playing and count > 0:
                    self.seq.select_pattern(self.patterns_overlay_index)
                self.seq.toggle_playback()
                self.patterns_overlay_delete_confirm_index = -1
                return True
            if key_code in [ord("a"), ord("A")]:
                ok, message = self.seq.add_pattern(copy_from_view=False)
                self.status_message = message
                self.patterns_overlay_index = self.seq.view_pattern
                self.patterns_overlay_delete_confirm_index = -1
                return True
            if key_code in [ord("d"), ord("D")]:
                ok, message = self.seq.add_pattern(copy_from_view=True)
                self.status_message = message
                self.patterns_overlay_index = self.seq.view_pattern
                self.patterns_overlay_delete_confirm_index = -1
                return True
            if key_code in [ord("x"), ord("X")]:
                if count <= 0:
                    return True
                idx = self.patterns_overlay_index
                if self.patterns_overlay_delete_confirm_index != idx:
                    self.patterns_overlay_delete_confirm_index = idx
                    if self.seq.pattern_has_data(idx):
                        self.status_message = f"Pattern {idx + 1} has data. Press X again to delete (X! marker shown)."
                    else:
                        self.status_message = f"Press X again to delete pattern {idx + 1}."
                    return True
                ok, message = self.seq.delete_pattern(idx)
                self.status_message = message
                self.patterns_overlay_delete_confirm_index = -1
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
                    self.audio_export_active = True
                    self.audio_export_input = ""
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
                    self.kit_export_active = True
                    self.kit_export_input = ""
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

        if key_code == curses.KEY_RIGHT:
            if self.header_focus:
                if self.header_section == "tabs":
                    self._set_active_tab((self.active_tab + 1) % 3)
                    return True
                if self.header_edit_active:
                    param = self.header_params[self.header_param_index]
                    if param in ["file", "pattern", "song", "record", "mode", "midi"]:
                        return True
                    elif param == "bpm":
                        self.seq.change_bpm(+1)
                    elif param == "length":
                        self.seq.change_current_pattern_length(+1)
                    elif param == "swing":
                        self.seq.change_current_pattern_swing(+1)
                    elif param == "humanize":
                        self.seq.change_current_pattern_humanize(+1)
                    else:
                        self.seq.change_pitch_semitones(+1)
                else:
                    self.header_param_index = (self.header_param_index + 1) % len(self.header_params)
            else:
                if self.active_tab == 1:
                    cols = [0, PREVIEW_COL, LOAD_COL, PAN_COL, AUDIO_VOLUME_COL, PROB_COL, GROUP_COL, TRACK_PITCH_COL]
                    nxt = cols[0]
                    for c in cols:
                        if c > self.cursor_x:
                            nxt = c
                            break
                    self.cursor_x = nxt
                elif self.active_tab == 2:
                    cols = [0, 1, 2, 3]
                    nxt = cols[0]
                    for c in cols:
                        if c > self.cursor_x:
                            nxt = c
                            break
                    self.cursor_x = nxt
                else:
                    cols = self._sequencer_nav_cols()
                    if self.cursor_x in cols:
                        idx = cols.index(self.cursor_x)
                    else:
                        idx = 0
                    self.cursor_x = cols[(idx + 1) % len(cols)]
            return True
        if key_code == curses.KEY_LEFT:
            if self.header_focus:
                if self.header_section == "tabs":
                    self._set_active_tab((self.active_tab - 1) % 3)
                    return True
                if self.header_edit_active:
                    param = self.header_params[self.header_param_index]
                    if param in ["file", "pattern", "song", "record", "mode", "midi"]:
                        return True
                    elif param == "bpm":
                        self.seq.change_bpm(-1)
                    elif param == "length":
                        self.seq.change_current_pattern_length(-1)
                    elif param == "swing":
                        self.seq.change_current_pattern_swing(-1)
                    elif param == "humanize":
                        self.seq.change_current_pattern_humanize(-1)
                    else:
                        self.seq.change_pitch_semitones(-1)
                else:
                    self.header_param_index = (self.header_param_index - 1) % len(self.header_params)
            else:
                if self.active_tab == 1:
                    cols = [0, PREVIEW_COL, LOAD_COL, PAN_COL, AUDIO_VOLUME_COL, PROB_COL, GROUP_COL, TRACK_PITCH_COL]
                    prev = cols[-1]
                    for c in reversed(cols):
                        if c < self.cursor_x:
                            prev = c
                            break
                    self.cursor_x = prev
                elif self.active_tab == 2:
                    cols = [0, 1, 2, 3]
                    prev = cols[-1]
                    for c in reversed(cols):
                        if c < self.cursor_x:
                            prev = c
                            break
                    self.cursor_x = prev
                else:
                    cols = self._sequencer_nav_cols()
                    if self.cursor_x in cols:
                        idx = cols.index(self.cursor_x)
                    else:
                        idx = 0
                    self.cursor_x = cols[(idx - 1) % len(cols)]
            return True
        if key_code == curses.KEY_UP:
            if self.header_focus:
                if self.header_section == "params" and self.header_edit_active:
                    param = self.header_params[self.header_param_index]
                    if param == "bpm":
                        self.seq.change_bpm(+1)
                    elif param == "length":
                        self.seq.change_current_pattern_length(+1)
                    elif param == "swing":
                        self.seq.change_current_pattern_swing(+1)
                    elif param == "humanize":
                        self.seq.change_current_pattern_humanize(+1)
                    elif param == "pitch":
                        self.seq.change_pitch_semitones(+1)
                elif self.header_section == "tabs":
                    self.header_section = "params"
                return True
            if self.cursor_y == 0:
                self.header_focus = True
                self.header_section = "tabs"
                self.header_edit_active = False
            else:
                if self.active_tab in [1, 2]:
                    self.cursor_y = max(0, self.cursor_y - 1)
                else:
                    self.move_cursor(0, -1)
            return True
        if key_code == curses.KEY_DOWN:
            if self.header_focus:
                if self.header_section == "params":
                    if self.header_edit_active:
                        param = self.header_params[self.header_param_index]
                        if param == "bpm":
                            self.seq.change_bpm(-1)
                        elif param == "length":
                            self.seq.change_current_pattern_length(-1)
                        elif param == "swing":
                            self.seq.change_current_pattern_swing(-1)
                        elif param == "humanize":
                            self.seq.change_current_pattern_humanize(-1)
                        elif param == "pitch":
                            self.seq.change_pitch_semitones(-1)
                    else:
                        self.header_section = "tabs"
                else:
                    self.header_focus = False
                    self.header_section = "params"
                    self.header_edit_active = False
            else:
                if self.active_tab in [1, 2]:
                    self.cursor_y = min(TRACKS - 2, self.cursor_y + 1)
                else:
                    self.move_cursor(0, 1)
            return True
        if "TAB" in event_tokens or key_code == 9:
            if self.header_focus:
                if self.header_section == "tabs":
                    self._set_active_tab((self.active_tab + 1) % 3)
                elif not self.header_edit_active:
                    self.header_param_index = (self.header_param_index + 1) % len(self.header_params)
                return True
            if self.active_tab == 1:
                cycle = [0, PREVIEW_COL, LOAD_COL, PAN_COL, AUDIO_VOLUME_COL, PROB_COL, GROUP_COL, TRACK_PITCH_COL]
            elif self.active_tab == 2:
                cycle = [0, 1, 2, 3]
            else:
                if 0 <= self.cursor_x < STEPS:
                    # In sequencer step grid, Tab hops by beat-starts rather than every step.
                    beat_cols = self._sequencer_beat_cols()
                    if self.cursor_x == beat_cols[-1]:
                        # From last beat, exit grid to first parameter column.
                        self.cursor_x = LOAD_COL
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
                if self.cursor_x in cycle:
                    idx = cycle.index(self.cursor_x)
                else:
                    idx = -1
                self.cursor_x = cycle[(idx + 1) % len(cycle)]
                return True
            next_idx = 0
            for i, col in enumerate(cycle):
                if col > self.cursor_x:
                    next_idx = i
                    break
            else:
                next_idx = 0
            self.cursor_x = cycle[next_idx]
            return True
        if "BTAB" in event_tokens or key_code == curses.KEY_BTAB:
            if self.header_focus:
                if self.header_section == "tabs":
                    self._set_active_tab((self.active_tab - 1) % 3)
                elif not self.header_edit_active:
                    self.header_param_index = (self.header_param_index - 1) % len(self.header_params)
                return True
            if self.active_tab == 1:
                cycle = [0, PREVIEW_COL, LOAD_COL, PAN_COL, AUDIO_VOLUME_COL, PROB_COL, GROUP_COL, TRACK_PITCH_COL]
            elif self.active_tab == 2:
                cycle = [0, 1, 2, 3]
            else:
                if 0 <= self.cursor_x < STEPS:
                    # Reverse beat-hop for Shift+Tab while cursor is inside sequencer steps.
                    beat_cols = self._sequencer_beat_cols()
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
                if self.cursor_x in cycle:
                    idx = cycle.index(self.cursor_x)
                else:
                    idx = 0
                self.cursor_x = cycle[(idx - 1) % len(cycle)]
                return True
            prev_idx = len(cycle) - 1
            for i in range(len(cycle) - 1, -1, -1):
                if cycle[i] < self.cursor_x:
                    prev_idx = i
                    break
            self.cursor_x = cycle[prev_idx]
            return True
        if key_code == 27:  # ESC
            if self.header_edit_active:
                self.header_edit_active = False
                return True
            if self.chain_edit_active:
                self._close_chain_dialog()
                return True
            if self.pattern_save_active:
                self._close_pattern_save_dialog()
                return True
            if self.kit_load_active:
                self._close_kit_dialog()
                return True
            if self.project_save_as_active:
                self._close_project_save_as_dialog()
                return True
            if self.audio_export_active:
                self._close_audio_export_dialog()
                return True
            if self.kit_export_active:
                self._close_kit_export_dialog()
                return True
            if self.track_rename_active:
                self._close_track_rename_dialog()
                return True
            if self.audio_export_options_active:
                self._close_audio_export_options_dialog()
                return True
            if self.kit_export_options_active:
                self._close_kit_export_options_dialog()
                return True
            if self.humanize_edit_active:
                self._close_humanize_dialog()
                return True
            if self.probability_edit_active:
                self._close_probability_dialog()
                return True
            if self.pattern_load_active:
                self._close_pattern_dialog()
                return True
            if self.swing_edit_active:
                self._close_swing_dialog()
                return True
            if self.clipboard_import_confirm_active:
                self._close_clipboard_import_confirm()
                return True
            if self.clear_confirm:
                self.clear_confirm = False
                return True
            if self.esc_confirm:
                return False
            self.esc_confirm = True
            self.status_message = "Press Esc again to exit."
            return True

        if self.pattern_load_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                ok, message = self.seq.load_project_file(self.pattern_load_input)
                self.status_message = message
                self._close_pattern_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.pattern_load_input = self.pattern_load_input[:-1]
                return True

            if isinstance(key, str) and key.isprintable() and key not in ["\n", "\r", "\t"]:
                if len(self.pattern_load_input) < 120:
                    self.pattern_load_input += key
                return True

            return True

        if self.chain_edit_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                ok, message = self.seq.set_chain_from_text(self.chain_edit_input)
                self.status_message = message
                self._close_chain_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.chain_edit_input = self.chain_edit_input[:-1]
                return True

            if isinstance(key, str) and key.isprintable() and key not in ["\n", "\r", "\t"]:
                if len(self.chain_edit_input) < 120:
                    self.chain_edit_input += key
                return True

            return True

        if self.swing_edit_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                ok, message = self.seq.set_current_pattern_swing_from_text(self.swing_edit_input)
                self.status_message = message
                self._close_swing_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.swing_edit_input = self.swing_edit_input[:-1]
                return True

            if isinstance(key, str) and key.isdigit():
                if len(self.swing_edit_input) < 3:
                    self.swing_edit_input += key
                return True

            return True

        if self.pattern_save_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                ok, message = self.seq.save_project_file(self.pattern_save_input)
                self.status_message = message
                self._close_pattern_save_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.pattern_save_input = self.pattern_save_input[:-1]
                return True

            if isinstance(key, str) and key.isprintable() and key not in ["\n", "\r", "\t"]:
                if len(self.pattern_save_input) < 120:
                    self.pattern_save_input += key
                return True

            return True

        if self.kit_load_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                ok, message = self.seq.load_kit_folder(self.kit_load_input)
                self.status_message = message
                self._close_kit_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.kit_load_input = self.kit_load_input[:-1]
                return True

            if isinstance(key, str) and key.isprintable() and key not in ["\n", "\r", "\t"]:
                if len(self.kit_load_input) < 120:
                    self.kit_load_input += key
                return True

            return True

        if self.project_save_as_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                ok, message = self.seq.save_project_as(self.project_save_as_input)
                self.status_message = message
                self._close_project_save_as_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.project_save_as_input = self.project_save_as_input[:-1]
                return True

            if isinstance(key, str) and key.isprintable() and key not in ["\n", "\r", "\t"]:
                if len(self.project_save_as_input) < 120:
                    self.project_save_as_input += key
                return True

            return True

        if self.audio_export_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                ok, message = self.seq.export_current_pattern_audio(
                    self.audio_export_input,
                    options=self.audio_export_options,
                )
                self.status_message = message
                self._close_audio_export_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.audio_export_input = self.audio_export_input[:-1]
                return True

            if isinstance(key, str) and key.isprintable() and key not in ["\n", "\r", "\t"]:
                if len(self.audio_export_input) < 120:
                    self.audio_export_input += key
                return True

            return True

        if self.kit_export_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                ok, message = self.seq.export_current_kit(
                    self.kit_export_input,
                    options=self.kit_export_options,
                )
                self.status_message = message
                self._close_kit_export_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.kit_export_input = self.kit_export_input[:-1]
                return True

            if isinstance(key, str) and key.isprintable() and key not in ["\n", "\r", "\t"]:
                if len(self.kit_export_input) < 120:
                    self.kit_export_input += key
                return True

            return True

        if self.humanize_edit_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                try:
                    value = int(self.humanize_edit_input.strip())
                except ValueError:
                    self.status_message = "Humanize must be 0-100"
                    self._close_humanize_dialog()
                    return True
                self.seq.set_current_pattern_humanize(value)
                self.status_message = f"Pattern humanize: {max(0, min(100, value))}"
                self._close_humanize_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.humanize_edit_input = self.humanize_edit_input[:-1]
                return True
            if isinstance(key, str) and key.isdigit():
                if len(self.humanize_edit_input) < 3:
                    self.humanize_edit_input += key
                return True
            return True

        if self.probability_edit_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                try:
                    value = int(self.probability_edit_input.strip())
                except ValueError:
                    self.status_message = "Probability must be 0-100"
                    self._close_probability_dialog()
                    return True
                if self.cursor_y == ACCENT_TRACK:
                    self.status_message = "Accent track has no probability"
                else:
                    self.seq.set_track_probability(self.cursor_y, value)
                    self.status_message = f"Track {self.cursor_y + 1} probability: {max(0, min(100, value))}%"
                self._close_probability_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.probability_edit_input = self.probability_edit_input[:-1]
                return True
            if isinstance(key, str) and key.isdigit():
                if len(self.probability_edit_input) < 3:
                    self.probability_edit_input += key
                return True
            return True

        if self.track_rename_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                track = self._track_for_row(self.cursor_y)
                ok, message = self.seq.rename_audio_track_sample(
                    self.seq.view_pattern,
                    track,
                    self.track_rename_input,
                )
                self.status_message = message
                self._close_track_rename_dialog()
                return True
            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.track_rename_input = self.track_rename_input[:-1]
                return True
            if isinstance(key, str) and key.isprintable() and key not in ["\n", "\r", "\t"]:
                if len(self.track_rename_input) < 120:
                    self.track_rename_input += key
                return True
            return True

        if self.keymap.matches("clear_pattern", event_tokens):
            if self.clear_confirm:
                self.seq.clear_current_pattern()
                self.clear_confirm = False
            else:
                self.clear_confirm = True
            return True

        if self.clear_confirm and key_code != -1:
            self.clear_confirm = False

        if isinstance(key, str) and key in ["/", "~"]:
            self.drop_path_active = True
            self.drop_path_input = key
            self.drop_path_last_input_time = time.perf_counter()
            self.status_message = "Drop path detected. Import options open automatically (Esc cancels)."
            return True

        if key_code == ord(' '):
            self.seq.toggle_playback()
            self.status_message = ""
        elif self.keymap.matches("patterns_overlay", event_tokens):
            self.patterns_overlay_active = True
            self.patterns_overlay_index = max(0, min(self.seq.pattern_count() - 1, self.seq.view_pattern))
            self.patterns_overlay_delete_confirm_index = -1
        elif self.keymap.matches("file_menu", event_tokens):
            self.header_focus = False
            self.header_section = "params"
            self.header_edit_active = False
            self._open_top_menu("file")
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.project_save_as_active = False
            self.project_save_as_input = ""
            self.audio_export_active = False
            self.audio_export_input = ""
            self.audio_export_options_active = False
            self.kit_export_active = False
            self.kit_export_input = ""
            self.kit_export_options_active = False
            self.humanize_edit_active = False
            self.humanize_edit_input = ""
            self.probability_edit_active = False
            self.probability_edit_input = ""
            self.chain_edit_active = False
            self.chain_edit_input = ""
            self.swing_edit_active = False
            self.swing_edit_input = ""
        elif self.keymap.matches("pattern_menu", event_tokens):
            self.header_focus = False
            self.header_section = "params"
            self.header_edit_active = False
            self._open_top_menu("pattern")
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.project_save_as_active = False
            self.project_save_as_input = ""
            self.audio_export_active = False
            self.audio_export_input = ""
            self.audio_export_options_active = False
            self.kit_export_active = False
            self.kit_export_input = ""
            self.kit_export_options_active = False
            self.humanize_edit_active = False
            self.humanize_edit_input = ""
            self.probability_edit_active = False
            self.probability_edit_input = ""
            self.chain_edit_active = False
            self.chain_edit_input = ""
            self.swing_edit_active = False
            self.swing_edit_input = ""
        elif self.keymap.matches("record_menu", event_tokens):
            self.header_focus = False
            self.header_section = "params"
            self.header_edit_active = False
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
            self.pattern_save_active = True
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.project_save_as_active = False
            self.project_save_as_input = ""
            self.audio_export_active = False
            self.audio_export_input = ""
            self.audio_export_options_active = False
            self.humanize_edit_active = False
            self.humanize_edit_input = ""
            self.probability_edit_active = False
            self.probability_edit_input = ""
            self.chain_edit_active = False
            self.chain_edit_input = ""
            self.swing_edit_active = False
            self.swing_edit_input = ""
            self.status_message = ""
        elif self.keymap.matches("pattern_load", event_tokens):
            self._open_file_browser("pattern")
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.project_save_as_active = False
            self.project_save_as_input = ""
            self.audio_export_active = False
            self.audio_export_input = ""
            self.audio_export_options_active = False
            self.humanize_edit_active = False
            self.humanize_edit_input = ""
            self.probability_edit_active = False
            self.probability_edit_input = ""
            self.chain_edit_active = False
            self.chain_edit_input = ""
            self.swing_edit_active = False
            self.swing_edit_input = ""
            self.status_message = ""
        elif self.keymap.matches("kit_load", event_tokens):
            self._open_file_browser("kit")
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.project_save_as_active = False
            self.project_save_as_input = ""
            self.audio_export_active = False
            self.audio_export_input = ""
            self.audio_export_options_active = False
            self.humanize_edit_active = False
            self.humanize_edit_input = ""
            self.probability_edit_active = False
            self.probability_edit_input = ""
            self.chain_edit_active = False
            self.chain_edit_input = ""
            self.swing_edit_active = False
            self.swing_edit_input = ""
            self.status_message = ""
        elif self.keymap.matches("chain_edit", event_tokens):
            self.chain_edit_active = True
            self.chain_edit_input = ""
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.project_save_as_active = False
            self.project_save_as_input = ""
            self.audio_export_active = False
            self.audio_export_input = ""
            self.audio_export_options_active = False
            self.humanize_edit_active = False
            self.humanize_edit_input = ""
            self.probability_edit_active = False
            self.probability_edit_input = ""
            self.swing_edit_active = False
            self.swing_edit_input = ""
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
            if self.cursor_x < STEPS and self.cursor_y != ACCENT_TRACK:
                quick_ratchet = {
                    ord('!'): 1,
                    ord('@'): 2,
                    ord('#'): 3,
                    ord('$'): 4,
                    ord('"'): 2,
                    164: 4,
                }[key_code]
                self.seq.quick_set_ratchet(self.cursor_y, self.cursor_x, quick_ratchet)
        elif key_code in range(ord('0'), ord('9') + 1):
            velocity = key_code - ord('0')
            track_idx = self._track_for_row(self.cursor_y) if self.active_tab == 1 else self.cursor_y
            if self.active_tab == 2:
                track_idx = max(0, min(TRACKS - 2, self.cursor_y))
                if self.cursor_x == 0 and velocity > 0:
                    self.seq.set_track_pan(track_idx, velocity)
                elif self.cursor_x == 1:
                    self.seq.set_track_volume(track_idx, velocity)
                elif self.cursor_x == 2 and velocity > 0:
                    self.seq.set_audio_track_pan(self.seq.view_pattern, track_idx, velocity)
                elif self.cursor_x == 3:
                    self.seq.set_audio_track_volume(self.seq.view_pattern, track_idx, velocity)
                return True
            if self.active_tab == 1 and self.cursor_x == PAN_COL:
                if self.cursor_y != ACCENT_TRACK:
                    self._apply_inline_audio_track_value(PAN_COL, velocity)
            elif self.active_tab == 1 and self.cursor_x == AUDIO_VOLUME_COL:
                if self.cursor_y != ACCENT_TRACK:
                    self._apply_inline_audio_track_value(AUDIO_VOLUME_COL, velocity)
            elif self.active_tab == 1 and self.cursor_x == PROB_COL:
                pass
            elif self.active_tab == 1 and self.cursor_x == TRACK_PITCH_COL:
                if self.cursor_y != ACCENT_TRACK:
                    self._apply_inline_audio_track_value(TRACK_PITCH_COL, velocity)
            elif self.cursor_x == PREVIEW_COL:
                pass
            elif self.cursor_x == PAN_COL:
                if velocity > 0:
                    self.seq.set_track_pan(self.cursor_y, velocity)
            elif self.cursor_x == GROUP_COL:
                if self.cursor_y != ACCENT_TRACK:
                    self.seq.set_track_group(self.cursor_y, velocity)
            elif self.cursor_x == TRACK_PITCH_COL:
                if self.cursor_y != ACCENT_TRACK:
                    self._apply_inline_track_value(TRACK_PITCH_COL, velocity)
            elif self.cursor_x == PROB_COL:
                self._apply_inline_track_value(PROB_COL, velocity)
            elif self.cursor_x == LOAD_COL:
                pass
            elif self.edit_mode == "ratchet":
                if self.cursor_y == ACCENT_TRACK:
                    self.seq.set_step_velocity(self.cursor_y, self.cursor_x, velocity)
                elif 1 <= velocity <= 4:
                    self.seq.set_step_ratchet(self.cursor_y, self.cursor_x, velocity)
            elif self.edit_mode == "detune":
                if self.cursor_y != ACCENT_TRACK:
                    self.seq.set_step_detune(self.cursor_y, self.cursor_x, velocity)
            else:
                self.seq.set_step_velocity(self.cursor_y, self.cursor_x, velocity)
                if velocity > 0:
                    self.seq.set_last_velocity(velocity)
        elif key_code in [10, 13, curses.KEY_ENTER]:
            if self.header_focus:
                if self.header_section == "tabs":
                    if self.active_tab == 0:
                        self.status_message = "Sequencer view"
                    elif self.active_tab == 1:
                        self.status_message = "Audio view"
                    else:
                        self.status_message = "Mixer view"
                    return True
                param = self.header_params[self.header_param_index]
                if param == "file":
                    self._open_top_menu("file")
                    self.header_focus = False
                    self.header_section = "params"
                    self.header_edit_active = False
                elif param == "pattern":
                    self._open_top_menu("pattern")
                    self.header_focus = False
                    self.header_section = "params"
                    self.header_edit_active = False
                elif param == "song":
                    ok, message = self.seq.toggle_chain()
                    self.status_message = message
                    self.header_edit_active = False
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
                    self.header_focus = False
                    self.header_section = "params"
                    self.header_edit_active = False
                elif param == "patterns":
                    self.patterns_overlay_active = True
                    self.patterns_overlay_index = max(0, min(self.seq.pattern_count() - 1, self.seq.view_pattern))
                    self.patterns_overlay_delete_confirm_index = -1
                    self.header_focus = False
                    self.header_section = "params"
                    self.header_edit_active = False
                elif param == "mode":
                    self._cycle_edit_mode()
                    self.header_edit_active = False
                elif param == "midi":
                    ok, message = self.seq.toggle_midi_out()
                    self.status_message = message
                    self.header_edit_active = False
                elif param == "chain_set":
                    self.chain_edit_active = True
                    self.chain_edit_input = ""
                    self.pattern_save_active = False
                    self.pattern_save_input = ""
                    self.pattern_load_active = False
                    self.pattern_load_input = ""
                    self.kit_load_active = False
                    self.kit_load_input = ""
                    self.project_save_as_active = False
                    self.project_save_as_input = ""
                    self.audio_export_active = False
                    self.audio_export_input = ""
                    self.audio_export_options_active = False
                    self.humanize_edit_active = False
                    self.humanize_edit_input = ""
                    self.probability_edit_active = False
                    self.probability_edit_input = ""
                    self.swing_edit_active = False
                    self.swing_edit_input = ""
                    self.status_message = ""
                    self.header_focus = False
                    self.header_section = "params"
                    self.header_edit_active = False
                else:
                    self.header_edit_active = not self.header_edit_active
                return True
            if self.active_tab == 1:
                track_idx = self._track_for_row(self.cursor_y)
                if self.cursor_x == 0:
                    ok, message = self.seq.toggle_audio_track_mode(self.seq.view_pattern, track_idx)
                    self.status_message = message
                    self.cursor_y = self._row_for_track(track_idx)
                    return True
                if self.cursor_x == PREVIEW_COL:
                    if self.cursor_y != ACCENT_TRACK:
                        ok, message = self.seq.preview_audio_track_slot(self.seq.view_pattern, track_idx)
                        self.status_message = message
                elif self.cursor_x == LOAD_COL:
                    if self.cursor_y != ACCENT_TRACK:
                        self._open_file_browser("audio_track", target_track=track_idx)
                elif self.cursor_x == PAN_COL:
                    self.seq.set_audio_track_pan(self.seq.view_pattern, track_idx, 5)
                elif self.cursor_x == AUDIO_VOLUME_COL:
                    self.seq.set_audio_track_volume(self.seq.view_pattern, track_idx, 9)
                elif self.cursor_x == PROB_COL:
                    self._open_record_overlay(target_track=track_idx, from_audio_view=True)
                elif self.cursor_x == GROUP_COL:
                    self._open_clear_audio_confirm(self.seq.view_pattern, track_idx)
                elif self.cursor_x == TRACK_PITCH_COL:
                    self.seq.set_audio_track_shift(self.seq.view_pattern, track_idx, 12)
                return True
            if self.active_tab == 2:
                self.status_message = "Mixer: type 1-9 for pan, 0-9 for volume"
                return True
            if self.cursor_x == PREVIEW_COL:
                if self.cursor_y != ACCENT_TRACK:
                    self.seq.preview_row(self.cursor_y)
            elif self.cursor_x == PAN_COL:
                self.seq.set_track_pan(self.cursor_y, 5)
            elif self.cursor_x == LOAD_COL:
                if self.cursor_y != ACCENT_TRACK:
                    self._open_file_browser("sample", target_track=self.cursor_y)
            elif self.cursor_x == PROB_COL:
                if self.cursor_y == ACCENT_TRACK:
                    self.status_message = "Accent track has no probability"
                else:
                    self.probability_edit_active = True
                    self.probability_edit_input = ""
            elif self.cursor_x == GROUP_COL:
                self.status_message = "Set group with number keys 0-9 (0 = off)"
            elif self.cursor_x == TRACK_PITCH_COL:
                self.status_message = "Track pitch: type 0..24 (12 = no shift)"
            else:
                self.seq.toggle_step(self.cursor_y, self.cursor_x)
        elif self.keymap.matches("mute_row", event_tokens):
            if self.active_tab == 0:
                self.seq.toggle_mute_row(self.cursor_y)
        elif self.keymap.matches("tab_1", event_tokens):
            self._set_active_tab(0)
        elif self.keymap.matches("tab_2", event_tokens):
            self._set_active_tab(1)
        elif self.keymap.matches("tab_3", event_tokens):
            self._set_active_tab(2)
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
def ui_loop(stdscr, seq, colors=None):
    """Main curses event/render loop."""
    curses.set_escdelay(25)
    curses.curs_set(0)
    stdscr.nodelay(True)

    _colors = colors if isinstance(colors, dict) else {}
    theme = {
        "frame": 0,
        "title": curses.A_BOLD,
        "text": 0,
        "hint": curses.A_BOLD,
        "prompt": curses.A_BOLD,
        "selected": curses.A_REVERSE,
        "divider": 0,
        "playhead": curses.A_BOLD,
        "muted": curses.A_DIM,
        "accent": curses.A_BOLD,
        "chain_on": curses.A_BOLD,
        "chain_off": curses.A_DIM,
        "pattern_manual": curses.A_BOLD,
        "pattern_chain_off": curses.A_DIM,
        "velocity_low": 0,
        "velocity_high": curses.A_BOLD,
        "midi_on": curses.A_BOLD,
        "midi_off": curses.A_DIM,
        "record": curses.A_BOLD,
        "meter_fill": curses.A_BOLD,
        "meter_hot": curses.A_BOLD,
        "tertiary_on": curses.A_BOLD,
        "tertiary_off": curses.A_DIM,
        "text_bold_enabled": False,
        "text_uppercase_enabled": True,
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
            if bright:
                attr |= curses.A_BOLD
            return attr

        primary_color, primary_bright = resolve_color(_colors.get("color_primary", "cyan"), "cyan")
        text_color, text_bright = resolve_color(_colors.get("color_text", "white"), "white")
        playhead_color, playhead_bright = resolve_color(_colors.get("color_playhead", "green"), "green")
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
        theme["title"] = pair_attr(1, curses.A_BOLD, bright=primary_bright)
        theme["prompt"] = pair_attr(1, curses.A_BOLD, bright=primary_bright)
        theme["selected"] = curses.A_REVERSE
        theme["text"] = pair_attr(2, bright=text_bright)
        theme["hint"] = pair_attr(4, curses.A_BOLD, bright=accent_bright)
        theme["divider"] = pair_attr(5, bright=divider_bright)
        theme["playhead"] = pair_attr(3, curses.A_BOLD, bright=playhead_bright)
        theme["muted"] = pair_attr(2, curses.A_DIM, bright=text_bright)
        theme["accent"] = pair_attr(4, curses.A_BOLD, bright=accent_bright)
        theme["chain_on"] = pair_attr(3, curses.A_BOLD, bright=playhead_bright)
        theme["chain_off"] = pair_attr(2, curses.A_DIM, bright=text_bright)
        theme["pattern_manual"] = pair_attr(3, curses.A_BOLD, bright=playhead_bright)
        theme["pattern_chain_off"] = pair_attr(2, curses.A_DIM, bright=text_bright)
        theme["velocity_low"] = pair_attr(2, curses.A_DIM, bright=text_bright)
        theme["velocity_high"] = pair_attr(2, curses.A_BOLD, bright=text_bright)
        theme["midi_on"] = pair_attr(3, curses.A_BOLD, bright=playhead_bright)
        theme["midi_off"] = pair_attr(2, curses.A_DIM, bright=text_bright)
        theme["record"] = pair_attr(6, curses.A_BOLD, bright=record_bright)
        theme["meter_fill"] = pair_attr(7, curses.A_BOLD, bright=meter_bright)
        theme["meter_hot"] = pair_attr(6, curses.A_BOLD, bright=record_bright)
        theme["tertiary_on"] = pair_attr(9, curses.A_BOLD, bright=tertiary_bright)
        theme["tertiary_off"] = pair_attr(9, curses.A_DIM, bright=tertiary_bright)
        theme["text_bold_enabled"] = text_bold_enabled
        theme["text_uppercase_enabled"] = text_uppercase_enabled

    keymap = Keymap()
    controller = Controller(seq, keymap)
    file_menu_label = keymap.label("file_menu")
    mode_key_label = keymap.label("mode_toggle")
    clear_key_label = keymap.label("clear_pattern")
    length_dec_label = keymap.label("pattern_length_dec")
    length_inc_label = keymap.label("pattern_length_inc")
    chain_edit_label = keymap.label("chain_edit")
    pattern_export_label = keymap.label("pattern_export")

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
        if (
            controller.record_overlay_active
            and controller.record_monitor_running
            and not controller.record_capture_active
            and seq.playing
            and controller._record_monitor_stream is None
        ):
            controller._stop_record_monitor()
            controller.record_level_db = -60.0

        ui_state = (
            controller.cursor_x,
            controller.cursor_y,
            controller.header_focus,
            controller.header_section,
            controller.header_param_index,
            controller.active_tab,
            controller.header_edit_active,
            controller.edit_mode,
            controller.clear_confirm,
            controller.esc_confirm,
            controller.pattern_save_active,
            controller.pattern_load_active,
            controller.kit_load_active,
            controller.project_save_as_active,
            controller.audio_export_active,
            controller.audio_export_options_active,
            controller.audio_export_options_index,
            controller.audio_export_options["bit_depth"],
            controller.audio_export_options["sample_rate"],
            controller.audio_export_options["channels"],
            controller.audio_export_options.get("scope", "pattern"),
            controller.kit_export_active,
            controller.kit_export_options_active,
            controller.kit_export_options_index,
            controller.kit_export_options["bit_depth"],
            controller.kit_export_options["sample_rate"],
            controller.kit_export_options["channels"],
            controller.humanize_edit_active,
            controller.probability_edit_active,
            controller.track_rename_active,
            controller.chain_edit_active,
            controller.swing_edit_active,
            controller.clear_audio_confirm_active,
            controller.clear_audio_force_confirm_active,
            controller.clipboard_import_confirm_active,
            controller.clipboard_import_count,
            controller.clipboard_import_text,
            controller.pattern_menu_active,
            controller.pattern_menu_kind,
            controller.pattern_menu_index,
            controller.patterns_overlay_active,
            controller.patterns_overlay_index,
            controller.patterns_overlay_delete_confirm_index,
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
            controller.pattern_save_input,
            controller.pattern_load_input,
            controller.kit_load_input,
            controller.project_save_as_input,
            controller.audio_export_input,
            controller.kit_export_input,
            controller.humanize_edit_input,
            controller.probability_edit_input,
            controller.track_rename_input,
            controller.chain_edit_input,
            controller.swing_edit_input,
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
            elif controller.pattern_save_active:
                prompt_text = f"Save pattern bank filename (Esc cancels): {controller.pattern_save_input}"
            elif controller.chain_edit_active:
                prompt_text = f"Give song sequence ({chain_edit_label}, Esc cancels): {controller.chain_edit_input}"
            elif controller.pattern_load_active:
                prompt_text = f"Give pattern bank filename (Esc cancels): {controller.pattern_load_input}"
            elif controller.kit_load_active:
                prompt_text = f"Give sample folder name (Esc cancels): {controller.kit_load_input}"
            elif controller.project_save_as_active:
                prompt_text = f"Save Project As folder name (Esc cancels): {controller.project_save_as_input}"
            elif controller.audio_export_active:
                prompt_text = f"Export audio filename (Esc cancels): {controller.audio_export_input}"
            elif controller.kit_export_active:
                prompt_text = f"Export kit folder name (Esc cancels): {controller.kit_export_input}"
            elif controller.humanize_edit_active:
                prompt_text = f"Humanize 0-100 (Esc cancels): {controller.humanize_edit_input}"
            elif controller.probability_edit_active:
                prompt_text = f"Probability 0-100 (Esc cancels): {controller.probability_edit_input}"
            elif controller.track_rename_active:
                prompt_text = f"Rename track sample (Esc cancels): {controller.track_rename_input}"
            elif controller.swing_edit_active:
                prompt_text = f"Swing 0-10 (Esc cancels): {controller.swing_edit_input}"
            elif controller.clear_audio_confirm_active:
                path_name = os.path.basename(controller.clear_audio_confirm_path) if controller.clear_audio_confirm_path else "(no file)"
                if controller.clear_audio_force_confirm_active:
                    prompt_text = f"File used elsewhere. Force delete everywhere? Y/N (Esc cancels): {path_name}"
                else:
                    prompt_text = f"Delete sample file too? Y/N (Esc cancels): {path_name}"
            elif controller.clipboard_import_confirm_active:
                if controller.clipboard_import_count > 1:
                    prompt_text = (
                        f"Import {controller.clipboard_import_count} patterns from clipboard? "
                        "This replaces all patterns and enables song mode. Y/N (Esc cancels)"
                    )
                else:
                    prompt_text = "Import clipboard to current pattern? This overwrites it. Y/N (Esc cancels)"
            else:
                prompt_text = ""

            draw(
                stdscr,
                seq,
                controller.cursor_x,
                controller.cursor_y,
                controller.header_focus,
                controller.header_section,
                controller.header_params[controller.header_param_index],
                controller.active_tab,
                controller.header_edit_active,
                controller.edit_mode,
                controller.clear_confirm,
                controller.esc_confirm,
                prompt_text,
                controller.status_message if not controller.drop_path_active and not controller.import_overlay_active and not controller.chop_overlay_active and not controller.pattern_save_active and not controller.chain_edit_active and not controller.pattern_load_active and not controller.kit_load_active and not controller.project_save_as_active and not controller.audio_export_active and not controller.audio_export_options_active and not controller.kit_export_active and not controller.kit_export_options_active and not controller.humanize_edit_active and not controller.probability_edit_active and not controller.track_rename_active and not controller.swing_edit_active and not controller.clear_audio_confirm_active and not controller.clipboard_import_confirm_active else "",
                controller.pattern_menu_active,
                controller.pattern_menu_kind,
                controller.pattern_menu_index,
                controller.patterns_overlay_active,
                controller.patterns_overlay_index,
                controller.patterns_overlay_delete_confirm_index,
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
                clear_key_label,
                length_dec_label,
                length_inc_label,
                theme
            )

            last_step = seq.step
            last_pattern = seq.pattern
            last_next_pattern = seq.next_pattern
            last_playing = seq.playing
            last_ui_state = ui_state
            should_draw = False

        time.sleep(0.002)
