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


@dataclass
class NavigationModel:
    header: HeaderNavigation = field(default_factory=HeaderNavigation)
    pattern: PatternParamsNavigation = field(default_factory=PatternParamsNavigation)
    tabs: tuple[str, ...] = ("sequencer", "audio", "mixer", "export")
    active_tab: int = 0

    def clamp(self):
        self.active_tab = max(0, min(3, int(self.active_tab)))
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

    def leave_pattern_to_grid(self):
        self.pattern.blur()

    def header_move_down(self):
        return self.header.move_down()

    def header_move_up(self):
        return self.header.move_up()
