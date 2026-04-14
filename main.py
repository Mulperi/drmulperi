import argparse
import curses

from config import DEFAULT_KIT_PATH, DEFAULT_PATTERN_NAME
from sequencer import Sequencer
from ui import ui_loop


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--kit",
        default=DEFAULT_KIT_PATH,
        help="Sample kit directory (default: kit1)",
    )
    parser.add_argument(
        "--pattern",
        default=DEFAULT_PATTERN_NAME,
        help="Pattern JSON file name/path without or with .json (default: patterns)",
    )
    args = parser.parse_args()

    pattern_path = args.pattern
    if not pattern_path.lower().endswith(".json"):
        pattern_path = f"{pattern_path}.json"

    seq = Sequencer(kit_path=args.kit, pattern_path=pattern_path)
    curses.wrapper(ui_loop, seq)


if __name__ == "__main__":
    main()
