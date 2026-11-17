"""Exercise real terminal job control with fake agents, never provider calls."""
import errno
import os
import pty
import select
import signal
import sys
import time
import unittest
from repo_process import run_foreground


class ForegroundJob(unittest.TestCase):
    def test_agent_controls_terminal_and_menu_returns_after_exit_and_failure(self):
        pid, master = pty.fork()
        if pid == 0:
            try:
                owner = os.tcgetpgrp(0)
                env = dict(os.environ, HC_TERMINAL_ID='test')
                script = ('import os,sys; '
                          'assert os.getpid()==os.getpgrp()==os.tcgetpgrp(0); '
                          'print("AGENT_READY",flush=True); '
                          'assert input()=="hello"; sys.exit(7)')
                result = run_foreground([sys.executable, '-c', script], cwd='.', env=env)
                assert result.returncode == 7
                assert os.tcgetpgrp(0) == owner
                try:
                    run_foreground(['/nonexistent/bollard-test-agent'], cwd='.', env=env)
                except FileNotFoundError:
                    pass
                else:
                    raise AssertionError('missing executable should fail')
                assert os.tcgetpgrp(0) == owner
                result = run_foreground([sys.executable, '-c',
                    'import signal; signal.signal(signal.SIGINT, signal.SIG_DFL); '
                    'print("INTERRUPT_READY",flush=True); signal.pause()'], cwd='.', env=env)
                assert result.returncode == -signal.SIGINT
                assert os.tcgetpgrp(0) == owner
                # Subsequent launch (resume/switch) also owns the same terminal.
                result = run_foreground([sys.executable, '-c',
                    'import os; assert os.getpid()==os.tcgetpgrp(0)'], cwd='.', env=env)
                assert result.returncode == 0
                assert os.tcgetpgrp(0) == owner
                print('MENU_READY', flush=True)
                assert input() == 'done'
                os._exit(0)
            except BaseException:
                import traceback
                traceback.print_exc()
                os._exit(1)
        output = b''
        sent_agent = sent_menu = sent_interrupt = False
        finished = False
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError as exc:
                        if exc.errno == errno.EIO: break
                        raise
                    if not chunk: break
                    output += chunk
                    if b'AGENT_READY' in output and not sent_agent:
                        os.write(master, b'hello\n'); sent_agent = True
                    if b'INTERRUPT_READY' in output and not sent_interrupt:
                        os.write(master, b'\x03'); sent_interrupt = True
                    if b'MENU_READY' in output and not sent_menu:
                        os.write(master, b'done\n'); sent_menu = True
                waited, status = os.waitpid(pid, os.WNOHANG)
                if waited:
                    finished = True
                    self.assertEqual(os.waitstatus_to_exitcode(status), 0, output.decode())
                    break
            if not finished:
                # PTY EOF can arrive just before the child becomes reapable.
                # Keep the same deadline instead of failing on that scheduling race.
                while time.monotonic() < deadline:
                    waited, status = os.waitpid(pid, os.WNOHANG)
                    if waited:
                        finished = True
                        break
                    time.sleep(.01)
                self.assertTrue(finished, output.decode())
                self.assertEqual(os.waitstatus_to_exitcode(status), 0, output.decode())
            self.assertTrue(sent_menu, output.decode())
        finally:
            os.close(master)
            if not finished:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
