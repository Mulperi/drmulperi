import curses
import os
import time

from .config import (
    ACCENT_TRACK,
    GRID_COLS,
    GROUP_COL,
    HUMANIZE_COL,
    LOAD_COL,
    PAN_COL,
    PATTERN_MENU_ITEMS,
    PATTERNS,
    PROB_COL,
    STEPS,
    TRACKS,
)
from .keymap import Keymap, _event_tokens

def draw(
    stdscr,
    seq,
    cursor_x,
    cursor_y,
    header_focus,
    header_param,
    header_edit_active,
    edit_mode,
    clear_confirm,
    esc_confirm,
    pattern_load_prompt,
    status_message,
    pattern_menu_active,
    pattern_menu_index,
    pattern_menu_key_label,
    help_active,
    help_lines,
    help_key_label,
    file_browser_active,
    file_browser_mode,
    file_browser_path,
    file_browser_items,
    file_browser_index,
    audio_export_options_active,
    audio_export_options,
    audio_export_options_index,
    mode_key_label,
    clear_key_label,
    length_dec_label,
    length_inc_label,
    theme
):
    """Render full terminal UI frame from current sequencer/controller state."""
    stdscr.clear()
    h, w = stdscr.getmaxyx()

    def safe_add(y, x, text, attr=0):
        if y < 0 or y >= h or x < 0 or x >= w:
            return
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
        safe_add(y0, x0, "╭", attr)
        safe_add(y0, x1, "╮", attr)
        safe_add(y1, x0, "╰", attr)
        safe_add(y1, x1, "╯", attr)
        for y in range(y0 + 1, y1):
            safe_add(y, x0, "│", attr)
            safe_add(y, x1, "│", attr)

    if h < 16 or w < 80:
        safe_add(0, 0, "Terminal too small for outlined layout")
        stdscr.refresh()
        return

    outer_left = 0
    outer_top = 0
    outer_right = w - 1
    outer_bottom = h - 1
    draw_box(outer_left, outer_top, outer_right, outer_bottom, theme["frame"])

    header_left = 2
    header_right = w - 3
    header_top = 1
    header_bottom = 6
    draw_box(header_left, header_top, header_right, header_bottom, theme["frame"])

    grid_left = 2
    grid_right = w - 3
    grid_top = 7
    grid_bottom = h - 2
    draw_box(grid_left, grid_top, grid_right, grid_bottom, theme["frame"])

    content_x = header_left + 2
    status = "PLAY" if seq.playing else "STOP"
    beat = (seq.step // 4) + 1
    mode = "RATCHET" if edit_mode == "ratchet" else "VELOCITY"

    safe_add(2, content_x, "DR. MULPERI", theme["title"])
    kit_name = os.path.basename(os.path.normpath(seq.kit_path))
    line3_parts = [
        ("pattern_bank", "PATTERN BANK: "),
        ("pattern_bank", f"{seq.pattern_name}  "),
        ("kit", "KIT: "),
        ("kit", f"{kit_name}"),
    ]
    x_line3 = content_x
    for key, text in line3_parts:
        attr = theme["text"]
        if header_focus and key == header_param:
            attr = attr | curses.A_REVERSE
        safe_add(3, x_line3, text[:max(0, header_right - x_line3)], attr)
        x_line3 += len(text)
        if x_line3 >= header_right:
            break
    midi_text = "MIDI OUT"
    midi_attr = theme["midi_on"] if seq.midi_out_enabled else theme["midi_off"]
    midi_x = header_right - len(midi_text) - 1
    safe_add(3, midi_x, midi_text, midi_attr)
    info_parts = [
        ("bpm", f"BPM:{seq.bpm}  "),
        ("base", f"{status}  {beat}/4  "),
        ("length", f"LEN:{seq.pattern_length[seq.view_pattern]}  "),
        ("swing", f"SW:{seq.current_pattern_swing_ui()}  "),
        ("pitch", f"PITCH:{seq.pitch_semitones:+d}st  "),
        ("mode", f"MODE:{mode}  "),
        ("menu", "MENU  "),
        ("help", "HELP"),
    ]
    x_info = content_x
    for key, text in info_parts:
        attr = theme["text"]
        if header_focus and key == header_param:
            attr = attr | curses.A_REVERSE
        safe_add(4, x_info, text[:max(0, header_right - x_info)], attr)
        x_info += len(text)
        if x_info >= header_right:
            break

    pattern_line = "PATTERN: "
    queue_flash_on = int(time.time() * 2) % 2 == 0
    for i in range(PATTERNS):
        if seq.view_pattern == i:
            pattern_line += f"[{i+1}] "
        elif (not seq.chain_enabled) and seq.playing and seq.next_pattern == i:
            pattern_line += f"({i+1}) " if queue_flash_on else f" {i+1}  "
        else:
            pattern_line += f" {i+1}  "

    pattern_attr = theme["pattern_manual"] if not seq.chain_enabled else theme["pattern_chain_off"]
    safe_add(5, content_x, pattern_line[:header_right - content_x], pattern_attr)

    chain_text = f"CHAIN:{seq.chain_display()}"
    chain_attr = theme["chain_on"] if seq.chain_enabled else theme["chain_off"]
    chain_x = content_x + len(pattern_line) + 2
    safe_add(5, chain_x, chain_text[:header_right - chain_x], chain_attr)

    grid_content_x = grid_left + 2
    playhead_y = grid_top + 1
    current_length = seq.pattern_length[seq.view_pattern]
    show_playhead = seq.playing and (seq.view_pattern == seq.pattern)
    x = grid_content_x
    safe_add(playhead_y, x, "  ", theme["text"])
    x += 2

    def col_cell_width(col):
        if col == PAN_COL:
            return 2
        if col == LOAD_COL:
            return 1
        if col == HUMANIZE_COL:
            return 3
        if col == PROB_COL:
            return 4
        if col == GROUP_COL:
            return 1
        return 3

    for s in range(GRID_COLS):
        sep = "| " if (s == current_length and s < STEPS) else "  "
        sep_attr = theme["hint"] if sep.strip() else theme["text"]
        safe_add(playhead_y, x, sep, sep_attr)
        x += 2
        cell_w = col_cell_width(s)
        if s < STEPS:
            body = ("  v  " if show_playhead and s == seq.step else "     ")
            if cell_w != 3:
                body = " " * (cell_w + 2)
        else:
            body = " " * (cell_w + 2)
        body_attr = theme["playhead"] if show_playhead and s == seq.step else theme["muted"]
        safe_add(playhead_y, x, body, body_attr)
        x += len(body)

    row_start = grid_top + 2
    now_pc = time.perf_counter()
    for t in range(TRACKS):
        y = row_start + t
        if y >= grid_bottom:
            continue

        row_attr = theme["accent"] if t == ACCENT_TRACK else theme["text"]
        if seq.muted_rows[t]:
            row_attr = theme["muted"]

        x = grid_content_x
        row_label = "A " if t == ACCENT_TRACK else f"{t+1} "
        label_attr = row_attr
        if (
            t < TRACKS - 1
            and not seq.muted_rows[t]
            and getattr(seq, "track_trigger_until", [0.0] * TRACKS)[t] > now_pc
        ):
            label_attr = theme["playhead"]
        safe_add(y, x, row_label, label_attr)
        x += len(row_label)

        def velocity_attr(value):
            if value <= 0:
                return theme["muted"]
            if value < 4:
                return theme["velocity_low"]
            return theme["velocity_high"]

        for s in range(GRID_COLS):
            if s == PAN_COL:
                if t == ACCENT_TRACK:
                    char = ""
                else:
                    pan_val = seq.track_pan[t]
                    char = f"P{pan_val}"
                cell_attr = row_attr
            elif s == LOAD_COL:
                char = "↓" if t != ACCENT_TRACK else ""
                cell_attr = row_attr
            elif s == HUMANIZE_COL:
                char = f"{seq.track_humanize[t]}" if t != ACCENT_TRACK else ""
                cell_attr = row_attr
            elif s == PROB_COL:
                char = f"%{seq.track_probability[t]}" if t != ACCENT_TRACK else ""
                cell_attr = row_attr
            elif s == GROUP_COL:
                char = str(seq.track_group[t]) if t != ACCENT_TRACK else ""
                cell_attr = row_attr
            else:
                val = seq.grid[seq.view_pattern][t][s]
                ratchet = seq.ratchet_grid[seq.view_pattern][t][s]
                if val == 0:
                    char = "."
                elif ratchet > 1:
                    char = f"{val}x{ratchet}"
                else:
                    char = str(val)
                if t == ACCENT_TRACK:
                    cell_attr = theme["accent"] | (curses.A_BOLD if val > 0 else 0)
                else:
                    cell_attr = velocity_attr(val)

                if s >= seq.pattern_length[seq.view_pattern]:
                    cell_attr = theme["muted"]

            sep = "| " if s in [PAN_COL, LOAD_COL, HUMANIZE_COL, PROB_COL, GROUP_COL] or (s < STEPS and s % 4 == 0) else "  "
            safe_add(y, x, sep, theme["divider"])
            x += len(sep)
            cell_w = col_cell_width(s)
            body = f"[{char:>{cell_w}}]" if cursor_x == s and cursor_y == t else f" {char:>{cell_w}} "
            if cursor_x == s and cursor_y == t:
                cell_attr = cell_attr | curses.A_REVERSE
            safe_add(y, x, body, cell_attr)
            x += len(body)

        mute_mark = "M" if seq.muted_rows[t] else " "
        safe_add(y, x, f" {mute_mark}", row_attr)

    prompt_line = ""
    help_line = ""
    if header_focus:
        if header_param == "pattern_bank":
            help_line = "Header: Left/Right select field. Enter opens pattern bank browser. Down returns to grid."
        elif header_param == "kit":
            help_line = "Header: Left/Right select field. Enter opens kit browser. Down returns to grid."
        elif header_param == "length":
            if header_edit_active:
                help_line = "Header edit: Left/Right or Up/Down changes LEN. Enter exits edit."
            else:
                help_line = "Header: Left/Right select field. Enter edits LEN. Down returns to grid."
        elif header_param == "bpm":
            if header_edit_active:
                help_line = "Header edit: Left/Right or Up/Down changes BPM. Enter exits edit."
            else:
                help_line = "Header: Left/Right select field. Enter edits BPM. Down returns to grid."
        elif header_param == "swing":
            if header_edit_active:
                help_line = "Header edit: Left/Right or Up/Down changes swing. Enter exits edit."
            else:
                help_line = "Header: Left/Right select field. Enter edits swing. Down returns to grid."
        elif header_param == "mode":
            help_line = "Header: Left/Right select field. Enter toggles mode (velocity/ratchet). Down returns to grid."
        elif header_param == "menu":
            help_line = "Header: Left/Right select field. Enter opens pattern menu. Down returns to grid."
        elif header_param == "help":
            help_line = "Header: Left/Right select field. Enter opens help. Down returns to grid."
        else:
            if header_edit_active:
                help_line = "Header edit: Left/Right or Up/Down tunes pitch. Enter exits edit."
            else:
                help_line = "Header: Left/Right select field. Enter edits pitch. Down returns to grid."
    elif cursor_x == LOAD_COL:
        help_line = "Load sample"
    elif cursor_x == PAN_COL:
        help_line = "Pan: 1=left, 5=center, 9=right. Type 1-9 to set."
    elif cursor_x == HUMANIZE_COL:
        help_line = "H Humanize: timing/velocity randomization per track (0-100). Type digits to set."
    elif cursor_x == PROB_COL:
        help_line = "% Probability: chance that a step triggers on this track (0-100). Type digits to set."
    elif cursor_x == GROUP_COL:
        help_line = "Group: 0=off, 1-9=mute group. Tracks with same group choke each other."
    elif cursor_y < TRACKS - 1:
        help_line = f"SAMPLE: {seq.engine.sample_names[cursor_y]}  (P preview, Enter on ↓ to load)"
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
        prompt_y = row_start + TRACKS
        if prompt_y < grid_bottom:
            safe_add(prompt_y, grid_content_x, prompt_line[:grid_right - grid_content_x], theme["hint"])
        else:
            safe_add(5, content_x, prompt_line[:header_right - content_x], theme["hint"])

    if help_active:
        visible_lines = [line for line in help_lines if line.strip() != ""]
        if not visible_lines:
            visible_lines = ["[keys]"]

        header = f"HELP ({help_key_label}/Esc to close)"
        content = [header, ""] + visible_lines
        max_line_len = max(len(line) for line in content)
        box_width = min(w - 6, max(40, max_line_len + 4))
        box_height = min(h - 6, len(content) + 3)
        box_left = max(1, (w - box_width) // 2)
        box_top = max(1, (h - box_height) // 2)
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1

        draw_box(box_left, box_top, box_right, box_bottom, theme["frame"])
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])
        line_y = box_top + 1
        for i, line in enumerate(content):
            if line_y + i >= box_bottom:
                break
            safe_add(line_y + i, box_left + 2, line[: box_width - 4], theme["text"])

    if pattern_menu_active:
        items = PATTERN_MENU_ITEMS
        title = f"PATTERN MENU ({pattern_menu_key_label}/Esc close)"
        max_item_len = max(len(title), *(len(item) for item in items))
        box_width = min(w - 8, max(40, max_item_len + 6))
        box_height = min(h - 4, len(items) + 4)
        box_left = max(1, (w - box_width) // 2)
        box_top = max(1, (h - box_height) // 2)
        box_right = box_left + box_width - 1
        box_bottom = box_top + box_height - 1

        draw_box(box_left, box_top, box_right, box_bottom, theme["frame"])
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])
        safe_add(box_top + 1, box_left + 2, title[: box_width - 4], theme["text"])
        for i, item in enumerate(items):
            item_attr = theme["text"]
            if i == pattern_menu_index:
                item_attr = item_attr | curses.A_REVERSE
            safe_add(box_top + 3 + i, box_left + 2, item[: box_width - 4], item_attr)

    if file_browser_active:
        if file_browser_mode == "pattern":
            mode_name = "PATTERN"
        elif file_browser_mode == "sample":
            mode_name = "SAMPLE"
        else:
            mode_name = "KIT"
        title = f"{mode_name} BROWSER (Enter open/select, <-/-> or Backspace up, Esc close)"
        if file_browser_mode == "sample":
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

        draw_box(box_left, box_top, box_right, box_bottom, theme["frame"])
        for y in range(box_top + 1, box_bottom):
            safe_add(y, box_left + 1, " " * (box_width - 2), theme["text"])

        safe_add(box_top + 1, box_left + 2, title[: box_width - 4], theme["text"])
        path_line = f"Path: {file_browser_path}"
        safe_add(box_top + 2, box_left + 2, path_line[: box_width - 4], theme["muted"])

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
                item_attr = item_attr | curses.A_REVERSE
            safe_add(row, box_left + 2, label[: box_width - 4], item_attr)

    if audio_export_options_active:
        title = "AUDIO EXPORT OPTIONS (Arrows/Space change, Enter export, Esc cancel)"
        bit_depth = int(audio_export_options.get("bit_depth", 16))
        sample_rate = int(audio_export_options.get("sample_rate", seq.engine.sr))
        channels = int(audio_export_options.get("channels", 2))
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
        export_attr = theme["text"] | (curses.A_REVERSE if audio_export_options_index == (row_count - 1) else 0)
        safe_add(box_top + 7, box_left + 4, "[ Export -> Filename ]", export_attr)

    stdscr.refresh()

# ---------- CONTROLLER ----------
class Controller:
    """Owns transient UI/dialog state and translates key input into actions."""
    def __init__(self, sequencer, keymap):
        self.seq = sequencer
        self.keymap = keymap
        self.cursor_x = 0
        self.cursor_y = 0
        self.edit_mode = "velocity"
        self.clear_confirm = False
        self.esc_confirm = False
        self.pattern_save_active = False
        self.pattern_save_input = ""
        self.pattern_load_active = False
        self.pattern_load_input = ""
        self.kit_load_active = False
        self.kit_load_input = ""
        self.pack_save_active = False
        self.pack_save_input = ""
        self.audio_export_active = False
        self.audio_export_input = ""
        self.audio_export_options_active = False
        self.audio_export_options = {
            "bit_depth": 16,
            "sample_rate": self.seq.engine.sr,
            "channels": 2,
        }
        self.audio_export_options_index = 0
        self.humanize_edit_active = False
        self.humanize_edit_input = ""
        self.probability_edit_active = False
        self.probability_edit_input = ""
        self.chain_edit_active = False
        self.chain_edit_input = ""
        self.swing_edit_active = False
        self.swing_edit_input = ""
        self.pattern_menu_active = False
        self.pattern_menu_index = 0
        self.help_active = False
        self.file_browser_active = False
        self.file_browser_mode = None
        self.file_browser_target_track = None
        self.file_browser_path = os.getcwd()
        self.file_browser_items = []
        self.file_browser_index = 0
        self.header_focus = False
        self.header_edit_active = False
        self.header_params = ["pattern_bank", "kit", "bpm", "length", "swing", "pitch", "mode", "menu", "help"]
        self.header_param_index = 0
        self.inline_value_buffer = ""
        self.inline_value_target = None  # (row, col)
        self.inline_value_time = 0.0
        self.status_message = ""
        self.pattern_actions = [f"pattern_{i+1}" for i in range(PATTERNS)]

    def move_cursor(self, dx, dy):
        self.cursor_x = (self.cursor_x + dx) % GRID_COLS
        self.cursor_y = (self.cursor_y + dy) % TRACKS

    def _apply_inline_track_value(self, col, digit):
        """Apply inline numeric typing for H/Prob columns without Enter."""
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
        value = max(0, min(100, value))

        if col == HUMANIZE_COL:
            self.seq.set_track_humanize(self.cursor_y, value)
        elif col == PROB_COL:
            self.seq.set_track_probability(self.cursor_y, value)

    def _close_pattern_dialog(self):
        self.pattern_load_active = False
        self.pattern_load_input = ""

    def _close_pattern_save_dialog(self):
        self.pattern_save_active = False
        self.pattern_save_input = ""

    def _close_kit_dialog(self):
        self.kit_load_active = False
        self.kit_load_input = ""

    def _close_pack_dialog(self):
        self.pack_save_active = False
        self.pack_save_input = ""

    def _close_audio_export_dialog(self):
        self.audio_export_active = False
        self.audio_export_input = ""
        self.audio_export_options_active = False

    def _close_audio_export_options_dialog(self):
        self.audio_export_options_active = False

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
                elif self.file_browser_mode == "sample" and e.name.lower().endswith(".wav"):
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
        self.pack_save_active = False
        self.pack_save_input = ""
        self.audio_export_active = False
        self.audio_export_input = ""
        self.audio_export_options_active = False
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

    def _close_swing_dialog(self):
        self.swing_edit_active = False
        self.swing_edit_input = ""

    def _run_pattern_menu_action(self):
        if self.pattern_menu_index == 0:
            ok, message = self.seq.copy_current_pattern()
        elif self.pattern_menu_index == 1:
            ok, message = self.seq.paste_to_current_pattern()
        elif self.pattern_menu_index == 2:
            self.seq.clear_current_pattern()
            ok, message = True, f"Cleared pattern {self.seq.view_pattern + 1}"
        elif self.pattern_menu_index == 3:
            self.pattern_save_active = True
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.pack_save_active = False
            self.pack_save_input = ""
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
            ok, message = True, ""
        elif self.pattern_menu_index == 4:
            self._open_file_browser("pattern")
            ok, message = True, ""
        elif self.pattern_menu_index == 5:
            self._open_file_browser("kit")
            ok, message = True, ""
        elif self.pattern_menu_index == 6:
            ok, message = self.seq.toggle_chain()
        elif self.pattern_menu_index == 7:
            self.swing_edit_active = True
            self.swing_edit_input = ""
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.pack_save_active = False
            self.pack_save_input = ""
            self.audio_export_active = False
            self.audio_export_input = ""
            self.audio_export_options_active = False
            self.chain_edit_active = False
            self.chain_edit_input = ""
            self.humanize_edit_active = False
            self.humanize_edit_input = ""
            self.probability_edit_active = False
            self.probability_edit_input = ""
            ok, message = True, ""
        elif self.pattern_menu_index == 8:
            self.pack_save_active = True
            self.pack_save_input = ""
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
            ok, message = True, ""
        elif self.pattern_menu_index == 9:
            ok, message = self.seq.toggle_midi_out()
        else:
            self.audio_export_options_active = True
            self.audio_export_options_index = 0
            self.audio_export_options = {
                "bit_depth": 16,
                "sample_rate": self.seq.engine.sr,
                "channels": 2,
            }
            self.audio_export_active = False
            self.audio_export_input = ""
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.pack_save_active = False
            self.pack_save_input = ""
            self.chain_edit_active = False
            self.chain_edit_input = ""
            self.swing_edit_active = False
            self.swing_edit_input = ""
            self.humanize_edit_active = False
            self.humanize_edit_input = ""
            self.probability_edit_active = False
            self.probability_edit_input = ""
            ok, message = True, ""
        self.status_message = message

    def handle_key(self, key):
        """Handle a single key event. Returns False when app should exit."""
        event_tokens = _event_tokens(key)
        key_code = key if isinstance(key, int) else ord(key)
        if key_code != 27 and self.esc_confirm:
            self.esc_confirm = False
        if self.status_message and key_code != -1:
            self.status_message = ""

        if self.help_active:
            if key_code == 27 or self.keymap.matches("help_menu", event_tokens):
                self.help_active = False
            return True

        if self.audio_export_options_active:
            row_count = 4
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
                if self.audio_export_options_index == 3:
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
                return True
            return True

        if self.file_browser_active:
            if key_code == 27:
                self._close_file_browser()
                return True
            if "SPACE" in event_tokens or key_code == 32:
                if self.file_browser_mode == "sample" and self.file_browser_items:
                    item = self.file_browser_items[self.file_browser_index]
                    if (not item.get("is_parent")) and (not item.get("is_action")) and (not item["is_dir"]):
                        ok, message = self.seq.preview_sample_file(item["path"], self.file_browser_target_track)
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
            if key_code == 27 or self.keymap.matches("pattern_menu", event_tokens):
                self._close_pattern_menu()
                return True
            if key_code == curses.KEY_UP:
                self.pattern_menu_index = (self.pattern_menu_index - 1) % len(PATTERN_MENU_ITEMS)
                return True
            if key_code == curses.KEY_DOWN:
                self.pattern_menu_index = (self.pattern_menu_index + 1) % len(PATTERN_MENU_ITEMS)
                return True
            if key_code in [10, 13, curses.KEY_ENTER]:
                self._run_pattern_menu_action()
                self._close_pattern_menu()
                return True
            if ord("1") <= key_code <= ord("9"):
                idx = key_code - ord("1")
                if idx < len(PATTERN_MENU_ITEMS):
                    self.pattern_menu_index = idx
                    self._run_pattern_menu_action()
                    self._close_pattern_menu()
                    return True
            return True

        if key_code == curses.KEY_RIGHT:
            if self.header_focus:
                if self.header_edit_active:
                    param = self.header_params[self.header_param_index]
                    if param in ["pattern_bank", "kit", "mode", "menu", "help"]:
                        return True
                    elif param == "bpm":
                        self.seq.change_bpm(+1)
                    elif param == "length":
                        self.seq.change_current_pattern_length(+1)
                    elif param == "swing":
                        self.seq.change_current_pattern_swing(+1)
                    else:
                        self.seq.change_pitch_semitones(+1)
                else:
                    self.header_param_index = (self.header_param_index + 1) % len(self.header_params)
            else:
                self.move_cursor(1, 0)
            return True
        if key_code == curses.KEY_LEFT:
            if self.header_focus:
                if self.header_edit_active:
                    param = self.header_params[self.header_param_index]
                    if param in ["pattern_bank", "kit", "mode", "menu", "help"]:
                        return True
                    elif param == "bpm":
                        self.seq.change_bpm(-1)
                    elif param == "length":
                        self.seq.change_current_pattern_length(-1)
                    elif param == "swing":
                        self.seq.change_current_pattern_swing(-1)
                    else:
                        self.seq.change_pitch_semitones(-1)
                else:
                    self.header_param_index = (self.header_param_index - 1) % len(self.header_params)
            else:
                self.move_cursor(-1, 0)
            return True
        if key_code == curses.KEY_UP:
            if self.header_focus:
                if self.header_edit_active:
                    param = self.header_params[self.header_param_index]
                    if param == "bpm":
                        self.seq.change_bpm(+1)
                    elif param == "length":
                        self.seq.change_current_pattern_length(+1)
                    elif param == "swing":
                        self.seq.change_current_pattern_swing(+1)
                    elif param == "pitch":
                        self.seq.change_pitch_semitones(+1)
                return True
            if self.cursor_y == 0:
                self.header_focus = True
                self.header_edit_active = False
            else:
                self.move_cursor(0, -1)
            return True
        if key_code == curses.KEY_DOWN:
            if self.header_focus:
                if self.header_edit_active:
                    param = self.header_params[self.header_param_index]
                    if param == "bpm":
                        self.seq.change_bpm(-1)
                    elif param == "length":
                        self.seq.change_current_pattern_length(-1)
                    elif param == "swing":
                        self.seq.change_current_pattern_swing(-1)
                    elif param == "pitch":
                        self.seq.change_pitch_semitones(-1)
                else:
                    self.header_focus = False
                    self.header_edit_active = False
            else:
                self.move_cursor(0, 1)
            return True
        if "TAB" in event_tokens or key_code == 9:
            if self.header_focus:
                if not self.header_edit_active:
                    self.header_param_index = (self.header_param_index + 1) % len(self.header_params)
                return True
            cycle = [0, 4, 8, 12, PAN_COL, LOAD_COL, HUMANIZE_COL, PROB_COL, GROUP_COL]
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
                if not self.header_edit_active:
                    self.header_param_index = (self.header_param_index - 1) % len(self.header_params)
                return True
            cycle = [0, 4, 8, 12, PAN_COL, LOAD_COL, HUMANIZE_COL, PROB_COL, GROUP_COL]
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
            if self.pack_save_active:
                self._close_pack_dialog()
                return True
            if self.audio_export_active:
                self._close_audio_export_dialog()
                return True
            if self.audio_export_options_active:
                self._close_audio_export_options_dialog()
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
            if self.clear_confirm:
                self.clear_confirm = False
                return True
            if self.edit_mode == "ratchet":
                self.edit_mode = "velocity"
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

        if self.pack_save_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                ok, message = self.seq.save_pack(self.pack_save_input)
                self.status_message = message
                self._close_pack_dialog()
                return True

            backspace_keys = {curses.KEY_BACKSPACE, 127, 8}
            if key_code in backspace_keys or key in ["\b", "\x7f"]:
                self.pack_save_input = self.pack_save_input[:-1]
                return True

            if isinstance(key, str) and key.isprintable() and key not in ["\n", "\r", "\t"]:
                if len(self.pack_save_input) < 120:
                    self.pack_save_input += key
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

        if self.humanize_edit_active:
            if key_code in [10, 13, curses.KEY_ENTER]:
                try:
                    value = int(self.humanize_edit_input.strip())
                except ValueError:
                    self.status_message = "Humanize must be 0-100"
                    self._close_humanize_dialog()
                    return True
                if self.cursor_y == ACCENT_TRACK:
                    self.status_message = "Accent track has no humanize"
                else:
                    self.seq.set_track_humanize(self.cursor_y, value)
                    self.status_message = f"Track {self.cursor_y + 1} humanize: {max(0, min(100, value))}"
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

        if self.keymap.matches("clear_pattern", event_tokens):
            if self.clear_confirm:
                self.seq.clear_current_pattern()
                self.clear_confirm = False
            else:
                self.clear_confirm = True
            return True

        if self.clear_confirm and key_code != -1:
            self.clear_confirm = False

        if key_code == ord(' '):
            self.seq.toggle_playback()
            self.status_message = ""
        elif self.keymap.matches("pattern_menu", event_tokens):
            self.header_focus = False
            self.header_edit_active = False
            self.pattern_menu_active = True
            self.pattern_menu_index = 0
            self.pattern_save_active = False
            self.pattern_save_input = ""
            self.pattern_load_active = False
            self.pattern_load_input = ""
            self.kit_load_active = False
            self.kit_load_input = ""
            self.pack_save_active = False
            self.pack_save_input = ""
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
        elif self.keymap.matches("help_menu", event_tokens):
            self.header_focus = False
            self.header_edit_active = False
            self.help_active = True
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
            self.pack_save_active = False
            self.pack_save_input = ""
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
            self.pack_save_active = False
            self.pack_save_input = ""
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
            self.pack_save_active = False
            self.pack_save_input = ""
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
            self.pack_save_active = False
            self.pack_save_input = ""
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
            if self.cursor_x < STEPS:
                if self.edit_mode == "velocity":
                    self.edit_mode = "ratchet"
                else:
                    self.edit_mode = "velocity"
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
            curses.KEY_F1, curses.KEY_F2, curses.KEY_F3, curses.KEY_F4
        ]:
            if self.cursor_x < STEPS and self.cursor_y != ACCENT_TRACK:
                quick_ratchet = {
                    ord('!'): 1,
                    ord('@'): 2,
                    ord('#'): 3,
                    ord('$'): 4,
                    ord('"'): 2,
                    164: 4,
                    curses.KEY_F1: 1,
                    curses.KEY_F2: 2,
                    curses.KEY_F3: 3,
                    curses.KEY_F4: 4
                }[key_code]
                self.seq.quick_set_ratchet(self.cursor_y, self.cursor_x, quick_ratchet)
        elif key_code in range(ord('0'), ord('9') + 1):
            velocity = key_code - ord('0')
            if self.cursor_x == PAN_COL:
                if velocity > 0:
                    self.seq.set_track_pan(self.cursor_y, velocity)
            elif self.cursor_x == GROUP_COL:
                if self.cursor_y != ACCENT_TRACK:
                    self.seq.set_track_group(self.cursor_y, velocity)
            elif self.cursor_x == HUMANIZE_COL:
                self._apply_inline_track_value(HUMANIZE_COL, velocity)
            elif self.cursor_x == PROB_COL:
                self._apply_inline_track_value(PROB_COL, velocity)
            elif self.cursor_x == LOAD_COL:
                pass
            elif self.edit_mode == "ratchet":
                if self.cursor_y == ACCENT_TRACK:
                    self.seq.set_step_velocity(self.cursor_y, self.cursor_x, velocity)
                elif 1 <= velocity <= 4:
                    self.seq.set_step_ratchet(self.cursor_y, self.cursor_x, velocity)
            else:
                self.seq.set_step_velocity(self.cursor_y, self.cursor_x, velocity)
                if velocity > 0:
                    self.seq.set_last_velocity(velocity)
        elif key_code in [10, 13, curses.KEY_ENTER]:
            if self.header_focus:
                param = self.header_params[self.header_param_index]
                if param == "pattern_bank":
                    self._open_file_browser("pattern")
                    self.header_focus = False
                    self.header_edit_active = False
                elif param == "kit":
                    self._open_file_browser("kit")
                    self.header_focus = False
                    self.header_edit_active = False
                elif param == "mode":
                    if self.edit_mode == "velocity":
                        self.edit_mode = "ratchet"
                    else:
                        self.edit_mode = "velocity"
                    self.header_edit_active = False
                elif param == "menu":
                    self.pattern_menu_active = True
                    self.pattern_menu_index = 0
                    self.header_focus = False
                    self.header_edit_active = False
                elif param == "help":
                    self.help_active = True
                    self.header_focus = False
                    self.header_edit_active = False
                else:
                    self.header_edit_active = not self.header_edit_active
                return True
            if self.cursor_x == PAN_COL:
                self.seq.set_track_pan(self.cursor_y, 5)
            elif self.cursor_x == LOAD_COL:
                if self.cursor_y != ACCENT_TRACK:
                    self._open_file_browser("sample", target_track=self.cursor_y)
            elif self.cursor_x == HUMANIZE_COL:
                if self.cursor_y == ACCENT_TRACK:
                    self.status_message = "Accent track has no humanize"
                else:
                    self.humanize_edit_active = True
                    self.humanize_edit_input = ""
            elif self.cursor_x == PROB_COL:
                if self.cursor_y == ACCENT_TRACK:
                    self.status_message = "Accent track has no probability"
                else:
                    self.probability_edit_active = True
                    self.probability_edit_input = ""
            elif self.cursor_x == GROUP_COL:
                self.status_message = "Set group with number keys 0-9 (0 = off)"
            else:
                self.seq.toggle_step(self.cursor_y, self.cursor_x)
        elif key_code in [ord('p'), ord('P')]:
            self.seq.preview_row(self.cursor_y)
        elif self.keymap.matches("mute_row", event_tokens):
            self.seq.toggle_mute_row(self.cursor_y)
        else:
            for pattern_index, action in enumerate(self.pattern_actions):
                if self.keymap.matches(action, event_tokens):
                    self.seq.select_pattern(pattern_index)
                    break

        return True

# ---------- INPUT ----------
def ui_loop(stdscr, seq):
    """Main curses event/render loop."""
    curses.set_escdelay(25)
    curses.curs_set(0)
    stdscr.nodelay(True)

    theme = {
        "frame": 0,
        "title": curses.A_BOLD,
        "text": 0,
        "hint": curses.A_BOLD,
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
    }
    if curses.has_colors():
        curses.start_color()
        try:
            curses.use_default_colors()
        except curses.error:
            pass
        curses.init_pair(1, curses.COLOR_CYAN, -1)    # frames
        curses.init_pair(2, curses.COLOR_WHITE, -1)   # text
        curses.init_pair(3, curses.COLOR_GREEN, -1)   # playhead
        curses.init_pair(4, curses.COLOR_YELLOW, -1)  # accent/high velocity
        curses.init_pair(5, curses.COLOR_BLUE, -1)    # dividers

        theme["frame"] = curses.color_pair(1)
        theme["title"] = curses.color_pair(1) | curses.A_BOLD
        theme["text"] = curses.color_pair(2)
        theme["hint"] = curses.color_pair(4) | curses.A_BOLD
        theme["divider"] = curses.color_pair(5)
        theme["playhead"] = curses.color_pair(3) | curses.A_BOLD
        theme["muted"] = curses.color_pair(2) | curses.A_DIM
        theme["accent"] = curses.color_pair(4) | curses.A_BOLD
        theme["chain_on"] = curses.color_pair(3) | curses.A_BOLD
        theme["chain_off"] = curses.color_pair(2) | curses.A_DIM
        theme["pattern_manual"] = curses.color_pair(3) | curses.A_BOLD
        theme["pattern_chain_off"] = curses.color_pair(2) | curses.A_DIM
        theme["velocity_low"] = curses.color_pair(2) | curses.A_DIM
        theme["velocity_high"] = curses.color_pair(2) | curses.A_BOLD
        theme["midi_on"] = curses.color_pair(3) | curses.A_BOLD
        theme["midi_off"] = curses.color_pair(2) | curses.A_DIM

    keymap = Keymap()
    controller = Controller(seq, keymap)
    help_lines = keymap.file_lines()
    help_key_label = keymap.label("help_menu")
    pattern_menu_label = keymap.label("pattern_menu")
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
                if seq.dirty:
                    seq.save()
                    seq.dirty = False
                return
            should_draw = True

        ui_state = (
            controller.cursor_x,
            controller.cursor_y,
            controller.header_focus,
            controller.header_param_index,
            controller.header_edit_active,
            controller.edit_mode,
            controller.clear_confirm,
            controller.esc_confirm,
            controller.pattern_save_active,
            controller.pattern_load_active,
            controller.kit_load_active,
            controller.pack_save_active,
            controller.audio_export_active,
            controller.audio_export_options_active,
            controller.audio_export_options_index,
            controller.audio_export_options["bit_depth"],
            controller.audio_export_options["sample_rate"],
            controller.audio_export_options["channels"],
            controller.humanize_edit_active,
            controller.probability_edit_active,
            controller.chain_edit_active,
            controller.swing_edit_active,
            controller.pattern_menu_active,
            controller.pattern_menu_index,
            controller.help_active,
            controller.file_browser_active,
            controller.file_browser_mode,
            controller.file_browser_path,
            tuple(item["name"] for item in controller.file_browser_items),
            controller.file_browser_index,
            controller.pattern_save_input,
            controller.pattern_load_input,
            controller.kit_load_input,
            controller.pack_save_input,
            controller.audio_export_input,
            controller.humanize_edit_input,
            controller.probability_edit_input,
            controller.chain_edit_input,
            controller.swing_edit_input,
            controller.status_message,
            seq.bpm,
            seq.pattern_length[seq.view_pattern],
            seq.pattern_swing[seq.view_pattern],
            seq.midi_out_enabled,
            seq.pattern,
            seq.view_pattern,
            seq.next_pattern,
            seq.chain_enabled,
            tuple(seq.chain),
            seq.chain_pos,
            tuple(
                1 if (t < TRACKS - 1 and seq.track_trigger_until[t] > time.perf_counter()) else 0
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
            draw(
                stdscr,
                seq,
                controller.cursor_x,
                controller.cursor_y,
                controller.header_focus,
                controller.header_params[controller.header_param_index],
                controller.header_edit_active,
                controller.edit_mode,
                controller.clear_confirm,
                controller.esc_confirm,
                (
                    f"Save pattern bank filename (Esc cancels): {controller.pattern_save_input}"
                    if controller.pattern_save_active
                    else (
                        f"Give chain sequence ({chain_edit_label}, Esc cancels): {controller.chain_edit_input}"
                        if controller.chain_edit_active
                        else (
                            f"Give pattern bank filename (Esc cancels): {controller.pattern_load_input}"
                            if controller.pattern_load_active
                            else (
                                f"Give sample folder name (Esc cancels): {controller.kit_load_input}"
                                if controller.kit_load_active
                                else (
                                    f"Save pack folder name (Esc cancels): {controller.pack_save_input}"
                                    if controller.pack_save_active
                                    else (
                                        f"Export audio filename (Esc cancels): {controller.audio_export_input}"
                                        if controller.audio_export_active
                                        else (
                                            f"Humanize 0-100 (Esc cancels): {controller.humanize_edit_input}"
                                            if controller.humanize_edit_active
                                            else (
                                                f"Probability 0-100 (Esc cancels): {controller.probability_edit_input}"
                                                if controller.probability_edit_active
                                                else (
                                                    f"Swing 0-10 (Esc cancels): {controller.swing_edit_input}"
                                                    if controller.swing_edit_active
                                                    else ""
                                                )
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
                ),
                controller.status_message if not controller.pattern_save_active and not controller.chain_edit_active and not controller.pattern_load_active and not controller.kit_load_active and not controller.pack_save_active and not controller.audio_export_active and not controller.audio_export_options_active and not controller.humanize_edit_active and not controller.probability_edit_active and not controller.swing_edit_active else "",
                controller.pattern_menu_active,
                controller.pattern_menu_index,
                pattern_menu_label,
                controller.help_active,
                help_lines,
                help_key_label,
                controller.file_browser_active,
                controller.file_browser_mode,
                controller.file_browser_path,
                controller.file_browser_items,
                controller.file_browser_index,
                controller.audio_export_options_active,
                controller.audio_export_options,
                controller.audio_export_options_index,
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
