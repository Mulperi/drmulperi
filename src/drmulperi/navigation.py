from dataclasses import dataclass, field


@dataclass
class HeaderNavigation:
    params: list[str] = field(default_factory=lambda: ["file", "pattern", "song", "record", "bpm", "pitch", "midi"])
    sections: tuple[str, ...] = ("params", "tabs")
    focus: bool = False
    section: str = "params"
    edit_active: bool = False
    param_index: int = 0

    def clamp(self):
        if self.section not in self.sections:
            self.section = self.sections[0]
        if not self.params:
            self.param_index = 0
            return
        self.param_index = max(0, min(len(self.params) - 1, self.param_index))

    def current_param(self):
        self.clamp()
        return self.params[self.param_index] if self.params else "file"

    def focus_section(self, section="params", edit_active=False):
        self.focus = True
        self.section = section
        self.edit_active = bool(edit_active)
        self.clamp()

    def blur(self):
        self.focus = False
        self.edit_active = False

    def next_param(self):
        if self.params:
            self.param_index = (self.param_index + 1) % len(self.params)

    def prev_param(self):
        if self.params:
            self.param_index = (self.param_index - 1) % len(self.params)

    def move_down(self):
        if self.section == "params":
            self.section = "tabs"
            self.edit_active = False
            return "tabs"
        self.blur()
        return "content"

    def move_up(self):
        if self.section == "tabs":
            self.section = "params"
            return "params"
        return self.section

    def move_horizontal(self, delta):
        """Move within header sections. Returns intent for external side effects.

        Intents:
        - "adjust-param": caller should adjust current editable param by delta.
        - None: movement applied locally (tab cycle / param cycle).
        """
        if self.section == "tabs":
            return "tab-delta"
        if self.edit_active:
            return "adjust-param"
        if delta > 0:
            self.next_param()
        else:
            self.prev_param()
        return None

    def tab_cycle(self, reverse=False):
        """Handle Tab/Shift+Tab behavior while header is focused."""
        if self.section == "tabs":
            return "tab-delta"
        if not self.edit_active:
            if reverse:
                self.prev_param()
            else:
                self.next_param()
        return None


@dataclass
class PatternParamsNavigation:
    items: list[str] = field(default_factory=lambda: ["name", "length", "swing", "humanize", "mode"])
    focus: bool = False
    edit_active: bool = False
    index: int = 0
    input_buffer: str = ""

    def clamp(self):
        if not self.items:
            self.index = 0
            return
        self.index = max(0, min(len(self.items) - 1, self.index))

    def current_item(self):
        self.clamp()
        return self.items[self.index] if self.items else "length"

    def clear_input(self):
        self.input_buffer = ""

    def focus_item(self, index=0, edit_active=False):
        self.focus = True
        self.edit_active = bool(edit_active)
        self.index = int(index)
        self.clear_input()
        self.clamp()

    def blur(self):
        self.focus = False
        self.edit_active = False
        self.clear_input()

    def focus_from_grid(self):
        target_index = self.index if self.index != 0 else 1
        self.focus_item(index=target_index, edit_active=False)

    def next_adjustable(self):
        if not self.items or self.index == 0:
            return False
        lo = 1
        hi = len(self.items) - 1
        self.index = lo if self.index >= hi else (self.index + 1)
        self.clear_input()
        return True

    def prev_adjustable(self):
        if not self.items or self.index == 0:
            return False
        lo = 1
        hi = len(self.items) - 1
        self.index = hi if self.index <= lo else (self.index - 1)
        self.clear_input()
        return True

    def move_up(self):
        if not self.edit_active and self.index != 0:
            self.index = 0
            self.clear_input()
            return "name"
        self.edit_active = False
        self.clear_input()
        self.focus = False
        return "header-tabs"

    def move_down(self):
        if self.edit_active:
            return "edit"
        if self.items and self.index < (len(self.items) - 1):
            self.index += 1
            self.clear_input()
            return "params"
        self.blur()
        return "grid"

    def name_row_index(self):
        return 0

    def controls_row_index(self):
        return 1 if len(self.items) > 1 else 0

    def focus_name_row(self):
        self.focus_item(index=self.name_row_index(), edit_active=False)

    def focus_controls_row(self):
        self.focus_item(index=self.controls_row_index(), edit_active=False)

    def move_focus_up(self):
        """Pattern controls UP flow: controls -> name -> header-tabs."""
        if self.current_item() != "name":
            self.index = self.name_row_index()
            self.clear_input()
            return "pattern-name"
        return "header-tabs"

    def move_focus_down(self):
        """Pattern controls DOWN flow: name -> controls -> grid."""
        if self.current_item() == "name":
            self.index = self.controls_row_index()
            self.clear_input()
            return "pattern-controls"
        self.blur()
        return "grid"


@dataclass
class NavigationModel:
    header: HeaderNavigation = field(default_factory=HeaderNavigation)
    pattern: PatternParamsNavigation = field(default_factory=PatternParamsNavigation)
    tabs: tuple[str, ...] = ("pattern", "song", "audio", "mixer", "export")
    active_tab: int = 0

    def clamp(self):
        self.active_tab = max(0, min(len(self.tabs) - 1, int(self.active_tab)))
        self.header.clamp()
        self.pattern.clamp()

    def next_tab(self):
        self.active_tab = (self.active_tab + 1) % len(self.tabs)

    def prev_tab(self):
        self.active_tab = (self.active_tab - 1) % len(self.tabs)

    def focus_header(self, section="params", edit_active=False):
        self.pattern.blur()
        self.header.focus_section(section=section, edit_active=edit_active)

    def focus_pattern(self, index=0, edit_active=False):
        self.header.blur()
        self.pattern.focus_item(index=index, edit_active=edit_active)

    def focus_pattern_from_grid(self):
        self.header.blur()
        self.pattern.focus_from_grid()

    def focus_pattern_name_row(self):
        self.header.blur()
        self.pattern.focus_name_row()

    def focus_pattern_controls_row(self):
        self.header.blur()
        self.pattern.focus_controls_row()

    def pattern_name_row_index(self):
        return self.pattern.name_row_index()

    def pattern_controls_row_index(self):
        return self.pattern.controls_row_index()

    def move_pattern_focus_up(self):
        return self.pattern.move_focus_up()

    def move_pattern_focus_down(self):
        return self.pattern.move_focus_down()

    def leave_pattern_to_grid(self):
        self.pattern.blur()

    def header_move_down(self):
        return self.header.move_down()

    def header_move_up(self):
        return self.header.move_up()

    def move_header_horizontal(self, delta):
        """Move in header context. May return side-effect intent."""
        intent = self.header.move_horizontal(delta)
        if intent == "tab-delta":
            self.active_tab = (self.active_tab + delta) % len(self.tabs)
            return None
        return intent

    def move_header_up(self):
        """Header UP movement. Returns side-effect intent when needed."""
        if self.header.section == "params" and self.header.edit_active:
            return "adjust-param"
        self.header_move_up()
        return None

    def move_header_down(self):
        """Header DOWN movement. Returns section target from header.move_down."""
        return self.header_move_down()

    def cycle_header_with_tab(self, reverse=False):
        """Tab/Shift+Tab while header focused. Handles params locally and tabs via active_tab."""
        delta = -1 if reverse else 1
        intent = self.header.tab_cycle(reverse=reverse)
        if intent == "tab-delta":
            self.active_tab = (self.active_tab + delta) % len(self.tabs)
            return None
        return intent

    @staticmethod
    def cycle_value(current, ordered_values, delta, fallback_index=0):
        """Wrap-cycle current value inside ordered_values by delta (+1/-1).

        If current is missing from ordered_values, fallback_index is used.
        """
        values = list(ordered_values or [])
        if not values:
            return current
        try:
            idx = values.index(current)
        except ValueError:
            idx = max(0, min(len(values) - 1, int(fallback_index)))
        step = 1 if delta >= 0 else -1
        return values[(idx + step) % len(values)]

    @staticmethod
    def directional_value(current, ordered_values, delta):
        """Step to next/prev value by numeric order without wrap search logic duplication.

        For positive delta: return first value > current, else first value.
        For negative delta: return last value < current, else last value.
        """
        values = list(ordered_values or [])
        if not values:
            return current
        if delta >= 0:
            for value in values:
                if value > current:
                    return value
            return values[0]
        for value in reversed(values):
            if value < current:
                return value
        return values[-1]
