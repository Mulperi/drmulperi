"""Project-wide constants and default key bindings."""

TRACKS = 9
STEPS = 16
CHAIN_MAX_STEPS = 16
PREVIEW_COL = STEPS
LOAD_COL = STEPS + 1
PAN_COL = STEPS + 2
HUMANIZE_COL = STEPS + 3
PROB_COL = STEPS + 4
GROUP_COL = STEPS + 5
TRACK_PITCH_COL = STEPS + 6
GRID_COLS = STEPS + 7
PATTERNS = 4
DEFAULT_KIT_PATH = ""
DEFAULT_PATTERN_NAME = "patterns"
KEYMAP_PATH = "keymap.ini"

ACCENT_TRACK = 8
ACCENT_BOOST = 0.35

DEFAULT_KEYMAP = {
    "help_menu": "H,F1",
    "pattern_menu": "F,F2",
    "pattern_menu_open": "P",
    "sequencer_menu": "S",
    "patterns_overlay": "Q,O",
    "mode_toggle": "T",
    "clear_pattern": "N",
    "pattern_copy": "B",
    "pattern_paste": "V",
    "mute_row": "M",
    "tempo_inc": "U",
    "tempo_dec": "J",
    "chain_toggle": "G",
    "chain_edit": "C",
    "pattern_length_dec": "CODE:-1",
    "pattern_length_inc": "CODE:-1",
    "pattern_export": "X",
    "pattern_load": "L",
    "kit_load": "K",
    "pattern_prev": "W",
    "pattern_next": "E",
    "pattern_1": "Q",
    "pattern_2": "W",
    "pattern_3": "E",
    "pattern_4": "R",
}

FILE_MENU_ITEMS = [
    "1. New Project",
    "2. Load Project",
    "3. Save Project",
    "4. Export",
]

PATTERN_MENU_ITEMS = [
    "1. Patterns Overlay",
    "2. Clear Pattern",
    "3. Copy Pattern",
    "4. Paste Pattern",
]

SEQUENCER_MENU_ITEMS = [
    "1. Save Kit",
    "2. Load Kit",
]

MIDI_NOTES = [36, 37, 38, 39, 40, 41, 42, 43]
