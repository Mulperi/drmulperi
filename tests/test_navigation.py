import unittest

from src.drmulperi.navigation import NavigationModel


class NavigationModelTests(unittest.TestCase):
    def test_focus_header_blurs_pattern(self):
        nav = NavigationModel()

        nav.focus_pattern(index=2, edit_active=True)
        nav.focus_header(section="tabs", edit_active=False)

        self.assertTrue(nav.header.focus)
        self.assertEqual(nav.header.section, "tabs")
        self.assertFalse(nav.pattern.focus)
        self.assertFalse(nav.pattern.edit_active)
        self.assertEqual(nav.pattern.input_buffer, "")

    def test_focus_pattern_from_grid_skips_name_when_unset(self):
        nav = NavigationModel()

        nav.focus_pattern_from_grid()

        self.assertTrue(nav.pattern.focus)
        self.assertEqual(nav.pattern.index, 1)
        self.assertFalse(nav.pattern.edit_active)

    def test_pattern_move_up_lands_on_name_before_header(self):
        nav = NavigationModel()
        nav.focus_pattern(index=3, edit_active=False)

        result = nav.pattern.move_up()

        self.assertEqual(result, "name")
        self.assertTrue(nav.pattern.focus)
        self.assertEqual(nav.pattern.index, 0)

    def test_pattern_move_down_advances_through_params_before_grid(self):
        nav = NavigationModel()
        nav.focus_pattern(index=0, edit_active=False)

        for expected_index in [1, 2, 3, 4]:
            result = nav.pattern.move_down()
            self.assertEqual(result, "params")
            self.assertTrue(nav.pattern.focus)
            self.assertEqual(nav.pattern.index, expected_index)

        result = nav.pattern.move_down()
        self.assertEqual(result, "grid")
        self.assertFalse(nav.pattern.focus)
        self.assertFalse(nav.pattern.edit_active)

    def test_adjustable_pattern_navigation_wraps_without_entering_name(self):
        nav = NavigationModel()
        nav.focus_pattern(index=1, edit_active=False)

        nav.pattern.prev_adjustable()
        self.assertEqual(nav.pattern.index, len(nav.pattern.items) - 1)

        nav.pattern.next_adjustable()
        self.assertEqual(nav.pattern.index, 1)

    def test_header_move_down_transitions_to_tabs_then_content(self):
        nav = NavigationModel()
        nav.focus_header(section="params", edit_active=True)

        self.assertEqual(nav.header_move_down(), "tabs")
        self.assertEqual(nav.header.section, "tabs")
        self.assertFalse(nav.header.edit_active)

        self.assertEqual(nav.header_move_down(), "content")
        self.assertFalse(nav.header.focus)


if __name__ == "__main__":
    unittest.main()