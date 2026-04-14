"""Project-wide constants and default key bindings."""

TRACKS = 9
STEPS = 16
CHAIN_MAX_STEPS = 16
PAN_COL = STEPS
LOAD_COL = STEPS + 1
HUMANIZE_COL = STEPS + 2
PROB_COL = STEPS + 3
GROUP_COL = STEPS + 4
GRID_COLS = STEPS + 5
PATTERNS = 4
DEFAULT_KIT_PATH = "kit1"
DEFAULT_PATTERN_NAME = "patterns"
KEYMAP_PATH = "keymap.ini"

ACCENT_TRACK = 8
ACCENT_BOOST = 0.35

DEFAULT_KEYMAP = {
    "help_menu": "H,F1",
    "pattern_menu": "F2",
    "mode_toggle": "T",
    "clear_pattern": "N",
    "pattern_copy": "B",
    "pattern_paste": "V",
    "mute_row": "M",
    "tempo_inc": "U",
    "tempo_dec": "J",
    "chain_toggle": "G",
    "chain_edit": "C",
    "pattern_length_dec": "[",
    "pattern_length_inc": "]",
    "pattern_export": "X",
    "pattern_load": "L",
    "kit_load": "K",
    "pattern_1": "Q",
    "pattern_2": "W",
    "pattern_3": "E",
    "pattern_4": "R",
}

PATTERN_MENU_ITEMS = [
    "1. Copy Pattern",
    "2. Paste Pattern",
    "3. Erase Pattern",
    "4. Save Pattern As",
    "5. Load Pattern",
    "6. Load Sample Kit",
    "7. Toggle Chain Mode",
    "8. Set Swing",
    "9. Save Pack",
    "10. Toggle MIDI OUT",
    "11. Export Pattern Audio",
]

MIDI_NOTES = [36, 37, 38, 39, 40, 41, 42, 43]
