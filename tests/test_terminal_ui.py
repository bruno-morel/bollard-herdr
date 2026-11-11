import curses
import unittest
from unittest.mock import patch
import repo_terminal_ui as U


class Screen:
    def __init__(self, keys, width=38, height=20):
        self.keys = iter(keys)
        self.width = width
        self.height = height
        self.output = []

    def getmaxyx(self):
        return self.height, self.width

    def keypad(self, enabled):
        pass

    def erase(self):
        pass

    def refresh(self):
        pass

    def get_wch(self):
        return next(self.keys)

    def addstr(self, y, x, text, style=0):
        self.output.append((y, x, text))


class TerminalUI(unittest.TestCase):
    def setUp(self):
        for name in ("curs_set", "set_escdelay"):
            guard = patch.object(curses, name)
            guard.start()
            self.addCleanup(guard.stop)
        guard = patch.object(curses, "has_colors", return_value=False)
        guard.start()
        self.addCleanup(guard.stop)

    def test_phone_picker_moves_and_returns_opaque_identity(self):
        screen = Screen([curses.KEY_DOWN, "\n"])
        rows = [
            ("host/t1", "First stream", "folder one"),
            ("host/t2", "Second stream", "folder two"),
        ]
        self.assertEqual(U.UI(screen).choose("Streams", rows), "host/t2")
        self.assertTrue(
            all(len(text) <= screen.width - x - 1 for _, x, text in screen.output)
        )

    def test_filter_selects_by_details_not_display_position(self):
        screen = Screen(["/", "b", "e", "t", "a", "\n", "\n"])
        rows = [("one", "Same title", "alpha"), ("two", "Same title", "beta")]
        self.assertEqual(U.UI(screen).choose("Streams", rows), "two")

    def test_empty_or_tiny_screen_can_always_cancel(self):
        for rows in ([], [("one", "A stream", "details")]):
            screen = Screen([curses.KEY_RESIZE, "\x1b"], width=25, height=10)
            self.assertIsNone(U.UI(screen).choose("Streams", rows))

    def test_input_clear_and_backspace(self):
        screen = Screen(["\x15", "n", "e", "w", "x", "\x7f", "\n"])
        self.assertEqual(U.UI(screen).input("Name", "old"), "new")

    def test_width_counts_wide_and_combining_characters(self):
        self.assertEqual(U.clipped("界abc", 3), "界a")
        self.assertEqual(U.clipped("e\u0301x", 1), "e\u0301")
        self.assertNotIn("\x1b", U.clipped("\x1b[31mtext", 80))

    def test_ascii_mode_replaces_toolbar_symbols(self):
        screen = Screen([])
        U.UI(screen, ascii=True).put(1, 1, "● ↑ ↓ ›")
        self.assertEqual(screen.output[-1][2], "* ^ v >")
