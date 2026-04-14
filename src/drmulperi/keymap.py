import configparser
import curses
import os

from .config import DEFAULT_KEYMAP, KEYMAP_PATH

def _normalize_key_token(token):
    """Normalize a key token from config into an internal matcher format."""
    token = token.strip()
    if not token:
        return None

    upper = token.upper()
    if upper.startswith("CODE:"):
        try:
            code = int(token.split(":", 1)[1].strip())
            return f"CODE:{code}"
        except ValueError:
            return None

    if upper.startswith("CHAR:"):
        value = token.split(":", 1)[1]
        if len(value) == 0:
            return None
        return f"CHAR:{value}"

    if len(token) == 1:
        return f"CHAR:{token}"

    return upper


def _event_tokens(key):
    """Convert a raw `curses` key event into normalized lookup tokens."""
    tokens = set()

    if isinstance(key, str):
        if key:
            tokens.add(f"CHAR:{key}")
            if len(key) == 1 and key.isalpha():
                tokens.add(f"CHAR:{key.lower()}")
                tokens.add(f"CHAR:{key.upper()}")

            if key == " ":
                tokens.add("SPACE")
            elif key in ["\n", "\r"]:
                tokens.add("ENTER")
            elif key == "\t":
                tokens.add("TAB")
    else:
        key_code = key
        tokens.add(f"CODE:{key_code}")

        if key_code == 27:
            tokens.add("ESC")
        elif key_code in [10, 13, curses.KEY_ENTER]:
            tokens.add("ENTER")
        elif key_code == curses.KEY_UP:
            tokens.add("UP")
        elif key_code == curses.KEY_DOWN:
            tokens.add("DOWN")
        elif key_code == curses.KEY_LEFT:
            tokens.add("LEFT")
        elif key_code == curses.KEY_RIGHT:
            tokens.add("RIGHT")
        elif key_code == curses.KEY_BTAB:
            tokens.add("BTAB")
        elif key_code == 32:
            tokens.add("SPACE")

        key_f0 = getattr(curses, "KEY_F0", None)
        if key_f0 is not None and isinstance(key_code, int):
            f_index = key_code - key_f0
            if 1 <= f_index <= 12:
                tokens.add(f"F{f_index}")
        else:
            for i in range(1, 13):
                key_fi = getattr(curses, f"KEY_F{i}", None)
                if key_fi is not None and key_code == key_fi:
                    tokens.add(f"F{i}")
                    break

    return tokens


class Keymap:
    """Loads and resolves key bindings from `keymap.ini`."""
    def __init__(self, path=KEYMAP_PATH):
        self.path = path
        self.bindings = {}
        self.load()

    def _parse_binding(self, raw_value, fallback):
        raw_parts = [part.strip() for part in raw_value.split(",")]
        tokens = []
        for part in raw_parts:
            normalized = _normalize_key_token(part)
            if normalized is not None:
                tokens.append(normalized)

        if tokens:
            return tokens

        fallback_token = _normalize_key_token(fallback)
        return [fallback_token] if fallback_token is not None else []

    def load(self):
        """Load key bindings, creating a default file when missing."""
        parser = configparser.ConfigParser()

        if not os.path.exists(self.path):
            parser["keys"] = DEFAULT_KEYMAP
            with open(self.path, "w") as f:
                parser.write(f)

        parser.read(self.path)
        section = parser["keys"] if "keys" in parser else {}

        for action, fallback in DEFAULT_KEYMAP.items():
            raw_value = section.get(action, fallback)
            self.bindings[action] = self._parse_binding(raw_value, fallback)

    def matches(self, action, event_tokens):
        """Return True when any token bound to `action` is present in `event_tokens`."""
        action_tokens = self.bindings.get(action, [])
        return any(token in event_tokens for token in action_tokens)

    def label(self, action):
        action_tokens = self.bindings.get(action, [])
        if not action_tokens:
            return "?"

        token = action_tokens[0]
        if token.startswith("CHAR:"):
            return token.split(":", 1)[1]
        if token.startswith("CODE:"):
            return token
        return token

    def file_lines(self):
        if not os.path.exists(self.path):
            return ["[keys]"]
        lines = []
        try:
            with open(self.path, "r") as f:
                for line in f:
                    lines.append(line.rstrip("\n"))
        except Exception:
            return ["[keys]"]
        return lines if lines else ["[keys]"]
