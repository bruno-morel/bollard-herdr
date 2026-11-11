"""Curses rendering and input shared by the picker and dashboard panels."""

import curses
import os
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor


def clean(value):
    # Repository names and errors are data, never terminal control sequences.
    return "".join(c if c >= " " and c != "\x7f" else " " for c in str(value))


def clipped(value, width):
    out, used = "", 0
    for c in clean(value):
        size = (
            0
            if unicodedata.combining(c)
            else 2 if unicodedata.east_asian_width(c) in "WF" else 1
        )
        if used + size > max(0, width):
            break
        out += c
        used += size
    return out


class UI:
    def __init__(self, screen, ascii=False):
        self.s = screen
        self.ascii = ascii
        curses.curs_set(0)
        screen.keypad(True)
        curses.set_escdelay(30)
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors()
            for i, c in enumerate(
                (
                    curses.COLOR_CYAN,
                    curses.COLOR_GREEN,
                    curses.COLOR_YELLOW,
                    curses.COLOR_RED,
                ),
                1,
            ):
                curses.init_pair(i, c, -1)
        self.context = ""

    def color(self, n):
        return (
            curses.color_pair(n)
            if curses.has_colors() and not os.environ.get("NO_COLOR")
            else 0
        )

    def icon(self, s, a):
        return a if self.ascii else s

    def put(self, y, x, text, style=0):
        h, w = self.s.getmaxyx()
        if 0 <= y < h and 0 <= x < w:
            try:
                self.s.addstr(
                    y,
                    x,
                    clipped(
                        (
                            str(text).translate(
                                str.maketrans(
                                    {
                                        "●": "*",
                                        "◉": "*",
                                        "◆": "*",
                                        "▣": "#",
                                        "⌂": "@",
                                        "☷": "=",
                                        "⑂": "Y",
                                        "▶": ">",
                                        "…": ".",
                                        "·": "|",
                                        "↑": "^",
                                        "↓": "v",
                                        "×": "x",
                                        "›": ">",
                                    }
                                )
                            )
                            if self.ascii
                            else text
                        ),
                        w - x - 1,
                    ),
                    style,
                )
            except curses.error:
                pass

    def frame(self, title, hint="", footer=""):
        self.s.erase()
        h, w = self.s.getmaxyx()
        self.put(1, 2, title, curses.A_BOLD | self.color(1))
        self.put(2, 2, self.context, curses.A_DIM)
        self.put(3, 2, self.icon("─", "-") * max(0, w - 4), curses.A_DIM)
        self.put(4, 2, hint)
        self.put(h - 3, 2, self.icon("─", "-") * max(0, w - 4), curses.A_DIM)
        self.put(h - 2, 2, footer, curses.A_DIM)

    def choose(self, title, rows, hint="", keys=None, selected=0):
        """Rows: (opaque value, concise title, details). Long paths only in details."""
        keys = keys or {}
        query = ""
        index = selected
        while True:
            filtered = [r for r in rows if query.lower() in (r[1] + " " + r[2]).lower()]
            index = max(0, min(index, len(filtered) - 1))
            h, w = self.s.getmaxyx()
            self.frame(
                title,
                hint,
                (
                    (
                        "↑↓ Enter · / filter · Esc back"
                        if w < 52
                        else "↑↓ move · Enter choose · / filter · Esc back"
                    )
                    if not self.ascii
                    else (
                        "Up/Down Enter / Esc"
                        if w < 52
                        else "Up/Down move | Enter choose | / filter | Esc back"
                    )
                ),
            )
            if h < 16 or w < 32:
                self.put(6, 2, "Needs 32 columns × 16 rows.")
            else:
                self.put(5, 2, ("Filter: " + query) if query else "")
                count = max(1, h - 12)
                start = max(0, min(index - count // 2, len(filtered) - count))
                for i, row in enumerate(filtered[start : start + count], start):
                    active = i == index
                    self.put(
                        6 + i - start,
                        2,
                        (
                            "› "
                            if active and not self.ascii
                            else "> " if active else "  "
                        )
                        + row[1],
                        (curses.A_REVERSE | curses.A_BOLD) if active else 0,
                    )
                if not filtered:
                    self.put(6, 2, "No matching entries.", curses.A_DIM)
                if filtered:
                    detail = filtered[index][2]
                    self.put(h - 5, 2, detail, curses.A_DIM)
                    self.put(h - 4, 2, f"{index+1} / {len(filtered)}", self.color(1))
            self.s.refresh()
            key = self.s.get_wch()
            if key == curses.KEY_MOUSE:
                try:
                    _, mx, my, _, flags = curses.getmouse()
                except curses.error:
                    continue
                if flags & getattr(curses, "BUTTON4_PRESSED", 0):
                    index = max(0, index - 1)
                elif flags & getattr(curses, "BUTTON5_PRESSED", 0):
                    index = min(len(filtered) - 1, index + 1)
                elif (
                    h >= 16
                    and w >= 32
                    and flags & (curses.BUTTON1_RELEASED | curses.BUTTON1_CLICKED)
                ):
                    chosen = start + my - 6
                    if (
                        2 <= mx < w - 2
                        and 6 <= my < 6 + count
                        and chosen < len(filtered)
                    ):
                        return filtered[chosen][0]
                continue
            if key in ("\x1b", "\x03"):
                return None
            if key == curses.KEY_RESIZE:
                continue
            if key in (curses.KEY_DOWN, "j"):
                index = min(index + 1, len(filtered) - 1)
            elif key in (curses.KEY_UP, "k"):
                index = max(0, index - 1)
            elif key == curses.KEY_NPAGE:
                index = min(index + max(1, h - 12), len(filtered) - 1)
            elif key == curses.KEY_PPAGE:
                index = max(0, index - max(1, h - 12))
            elif key in ("\n", "\r", curses.KEY_ENTER) and filtered:
                return filtered[index][0]
            elif key == "/":
                result = self.input("Filter", query)
                if result is not None:
                    query = result
                    index = 0
            elif key in keys:
                return keys[key]

    def input(self, title, initial=""):
        value = initial
        while True:
            self.frame(
                title,
                "Edit the value below.",
                "Enter accept · Esc cancel · Ctrl+U clear",
            )
            self.put(6, 2, value or " ", curses.A_REVERSE)
            self.s.refresh()
            key = self.s.get_wch()
            if key in ("\x1b", "\x03"):
                return None
            if key in ("\n", "\r", curses.KEY_ENTER):
                return value.strip()
            if key in (curses.KEY_BACKSPACE, "\x7f", "\b"):
                value = value[:-1]
            elif key == "\x15":
                value = ""
            elif isinstance(key, str) and key.isprintable():
                value += key

    def message(self, title, text):
        import textwrap

        lines = []
        for line in str(text).splitlines():
            lines.extend(
                textwrap.wrap(clean(line), max(20, self.s.getmaxyx()[1] - 6)) or [""]
            )
        self.choose(
            title, [(i, line, "") for i, line in enumerate(lines)], "Esc to return"
        )

    def busy(self, title, fn):
        with ThreadPoolExecutor(max_workers=1) as pool:
            started = time.monotonic()
            self.progress_text = ""
            f = pool.submit(fn)
            self.s.timeout(100)
            try:
                while not f.done():
                    self.frame(
                        title,
                        (self.progress_text or "Working…")
                        + " · "
                        + str(int(time.monotonic() - started))
                        + "s",
                        "Existing conversations keep running.",
                    )
                    self.s.refresh()
                    self.s.getch()
                return f.result()
            finally:
                self.s.timeout(-1)

    def outside(self, fn):
        curses.def_prog_mode()
        curses.endwin()
        try:
            return fn()
        finally:
            curses.reset_prog_mode()
            self.s.clear()
            self.s.refresh()
