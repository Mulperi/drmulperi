"""Project-wide constants and default key bindings."""

TRACKS = 9
CHAIN_MAX_STEPS = 16
# Column IDs for parameter columns in the sequencer grid.
# Negative values never collide with step indices (0..max_step_count-1).
TRACK_LABEL_COL = -6
LOAD_COL        = -1
PREVIEW_COL     = -2
REC_COL        = -3
CLEAR_COL       = -4
TRACK_PITCH_COL = -5
PATTERNS = 4
SETTINGS_PATH = "settings.ini"
KEYMAP_PATH = SETTINGS_PATH

ACCENT_TRACK = 8
ACCENT_BOOST = 0.35

DEFAULT_KEYMAP = {
    "file_menu": "F",
    "edit_menu": "P",
    "record_menu": "R",
    "tab_1": "F1",
    "tab_2": "F2",
    "tab_3": "F3",
    "tab_4": "X",
    "tab_5": "C",
    "tab_next": "]",
    "tab_previous": "[",
    "sample_preview": "SPACE",
    "patterns_overlay": "E,O",
    "mode_toggle": "V",
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
    "pattern_export": "CODE:-1",
    "pattern_load": "L",
    "kit_load": "K",
    "pattern_prev": "Q",
    "pattern_next": "W",
    "pattern_1": "Q",
    "pattern_2": "W",
    "pattern_3": "E",
    "pattern_4": "R",
}

DEFAULT_SETTINGS = {
    "sample_rate": "48000",
    "duplex": "off",
}

FILE_MENU_ITEMS = [
    "1. New Project",
    "2. Load Project",
    "3. Save Project",
    "4. Save Project As",
    "5. Save Kit",
    "6. Load Kit",
    "7. Export",
]

PATTERN_MENU_ITEMS = [
    "1. Patterns Overlay",
    "2. Add Pattern",
    "3. Duplicate Pattern",
    "4. Import From Clipboard",
    "5. Import From Project",
    "6. Copy Patterns To Clipboard",
    "7. Clear Pattern",
    "8. Copy Pattern",
    "9. Paste Pattern (V)",
    "10. Delete Pattern (X)",
]

MIDI_NOTES = [36, 37, 38, 39, 40, 41, 42, 43]
