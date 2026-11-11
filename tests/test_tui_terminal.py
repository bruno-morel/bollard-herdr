"""Real curses screens and keyboard input, with no Herdr or agent processes."""

import curses
import errno
import fcntl
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pty
import select
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import patch


def probe(screen):
    from repo_terminal_ui import UI
    from repo_tui_panel import Panel
    from repo_stream_picker import Picker

    def visible():
        return "\n".join(
            screen.instr(y, 0).decode("utf-8", "replace")
            for y in range(screen.getmaxyx()[0])
        )

    result = []
    # No backend method may run: this exercises only local presentation/input.
    with patch("repo_tui_panel.Backend", side_effect=lambda: None):
        panel = Panel(screen, "test", "tool")
    panel.address = "test/t1"
    panel.row = {
        "project_name": "Example",
        "address": panel.address,
        "labels": {"repo-tools.stream": "sample", "repo-tools.role": "work"},
    }
    try:
        for height, width in ((24, 44), (50, 120), (24, 44)):
            curses.resizeterm(height, width)
            panel.key(curses.KEY_RESIZE)
            ui = UI(screen)
            curses.unget_wch("\n")
            curses.ungetch(curses.KEY_DOWN)
            selected = ui.choose(
                "Conversation", [("a", "Planning", ""), ("b", "Implementation", "")]
            )
            assert selected == "b", selected
            assert "Implementation" in visible()
            # Loading is synchronous in this fixture; choices use real curses input.
            ui.busy = lambda title, fn: fn()
            backend = SimpleNamespace(
                inventory=lambda: [panel.row],
                verify=lambda row: row,
                hc=lambda *args: panel.row if args == ("get", panel.address) else None,
            )
            picker = Picker(
                backend,
                ui,
                SimpleNamespace(
                    machine=None, repo=None, role="work", select_only=True, current=None
                ),
            )
            curses.unget_wch("\n")
            curses.ungetch(curses.KEY_DOWN)
            picker.run()
            assert picker.result["address"] == panel.address
            panel.tab = "docs"
            panel.folder = ""
            panel.preview = None
            panel.preview_focus = False
            panel.cache["docs"] = {
                "files": [
                    {"path": "docs/guide.md", "changed": True},
                    {"path": "other.txt", "changed": False},
                ]
            }
            panel.render()
            assert "other.txt" not in visible()
            panel.key("\n")
            assert panel.folder == "docs", panel.folder
            panel.preview = {
                "path": "docs/guide.md",
                "text": "# Hello reader\n\n"
                + "\n\n".join(
                    "Paragraph %s: readable on a phone." % i for i in range(40)
                ),
            }
            panel.preview_focus = True
            panel.offset = 0
            panel.render()
            panel.markdown_future.result(timeout=10)
            panel.render()
            assert panel.markdown_visible
            assert "Hello reader" in visible(), visible()
            panel.key(curses.KEY_NPAGE)
            panel.render()
            assert panel.offset > 0
            panel.key("q")
            assert panel.preview is None and not panel.close_requested
            panel.tab = "docker"
            panel.cache["docker"] = {
                "logs": "\n".join("Log %s" % i for i in range(100))
            }
            panel.key(curses.KEY_END)
            panel.render()
            assert "Log 99" in visible()
            panel.key(curses.KEY_PPAGE)
            panel.render()
            assert "Log 99" not in visible()
            result.append([height, width])
    finally:
        panel.pool.shutdown(wait=True)
    return result


class TerminalTests(unittest.TestCase):
    def test_phone_desktop_resize_keyboard_markdown_and_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 44, 0, 0))
            process = subprocess.Popen(
                [sys.executable, __file__, "--probe", str(report)],
                stdin=slave,
                stdout=slave,
                stderr=slave,
                start_new_session=True,
                env=dict(os.environ, TERM="xterm-256color"),
            )
            os.close(slave)
            output = bytearray()
            deadline = time.monotonic() + 30
            try:
                while time.monotonic() < deadline:
                    if select.select([master], [], [], 0.1)[0]:
                        try:
                            chunk = os.read(master, 65536)
                        except OSError as exc:
                            if exc.errno == errno.EIO:
                                break
                            raise
                        if not chunk:
                            break
                        output.extend(chunk)
                    elif process.poll() is not None:
                        break
                process.wait(timeout=2)
                self.assertEqual(
                    process.returncode, 0, output.decode("utf-8", "replace")
                )
                self.assertEqual(
                    json.loads(report.read_text()), [[24, 44], [50, 120], [24, 44]]
                )
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                os.close(master)


if __name__ == "__main__" and "--probe" in sys.argv:
    Path(sys.argv[-1]).write_text(json.dumps(curses.wrapper(probe)))
