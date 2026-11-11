"""A plain Claude Code session with the plugin loaded, as a stranger would run it."""

import fcntl
import os
import pty
import struct
import termios
import threading
import time

from rig import ROOT, ClaudeSession, log_lines


class PluginSession(ClaudeSession):
    def start(self, timeout: float = 90) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_") and k not in ("CLAUDECODE", "CLAUDE_PID")}
        env.update(CLAUDE_VOICE_NO_BROWSER="1", CLAUDE_VOICE_FRONT=self.front)
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.chdir(self.cwd)
            os.execvpe("claude", ["claude", "--plugin-dir", str(ROOT), *self.args], env)
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 200, 0, 0))
        threading.Thread(target=self._pump, daemon=True).start()
        deadline = time.time() + timeout
        while time.time() < deadline and "claudecode" not in self.flat():
            time.sleep(0.5)
        time.sleep(4)  # the input box is up, and any folder trust dialog answered

    def type(self, text: str) -> None:
        os.write(self.fd, text.encode())
        time.sleep(0.5)
        os.write(self.fd, b"\r")


class JoinedSession(PluginSession):
    """A plain session that joined with /pointe:voice: how people run it, and the path that works where an org blocks channels."""

    def start(self, timeout: float = 90) -> None:
        before = len(log_lines(r"registered .*\(pid \d+"))
        super().start(timeout)
        self.type("/pointe:voice")
        deadline = time.time() + 60
        while time.time() < deadline and len(log_lines(r"registered .*\(pid \d+")) <= before:
            time.sleep(0.5)
        if len(log_lines(r"registered .*\(pid \d+")) <= before:
            raise TimeoutError(f"/pointe:voice did not register the session:\n{self.flat()[-800:]}")
        time.sleep(3)  # the join turn finishes before the first request
