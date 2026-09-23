"""One Gemini conversation per correspondent, remembered across restarts.

A correspondent who gets a new conversation every message gets an agent with no
memory of the last thing it said, which is the whole value of a chat. The store
is the map from a sender to the conversation URL that belongs to them.

It is small, it is JSON, and it is written whole: a turn either records the new
conversation or it does not. A store that cannot be read is treated as empty
and said out loud in the reply, because a wake that dies on its own bookkeeping
loses the message it was woken for.
"""
import json
import os
import tempfile
import time

APP_DIR = "a8s-gemini-web"


def state_root():
    """Where sessions live, off the install directory an update replaces."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, APP_DIR)


class SessionStore:
    """The conversations one a8s seat holds, keyed by correspondent."""

    def __init__(self, seat, root=None):
        self.seat = seat
        self.root = root or state_root()
        self.warning = ""
        self._sessions = None

    @property
    def path(self):
        return os.path.join(self.root, f"{self.seat}.json")

    def _load(self):
        if self._sessions is not None:
            return self._sessions
        self._sessions = {}
        try:
            with open(self.path) as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            return self._sessions
        except (OSError, ValueError) as exc:
            self.warning = (
                f"the session store at {self.path} could not be read ({exc}); "
                "this turn starts a fresh conversation"
            )
            return self._sessions
        sessions = payload.get("sessions") if isinstance(payload, dict) else None
        if not isinstance(sessions, dict):
            self.warning = (
                f"the session store at {self.path} is not in the expected shape; "
                "this turn starts a fresh conversation"
            )
            return self._sessions
        self._sessions = {
            name: entry for name, entry in sessions.items() if isinstance(entry, dict)
        }
        return self._sessions

    def all(self):
        return dict(self._load())

    def get(self, sender):
        return self._load().get(sender.lower())

    def remember(self, sender, url):
        sessions = self._load()
        sessions[sender.lower()] = {
            "url": url,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        self._write(sessions)

    def forget(self, sender):
        sessions = self._load()
        if sessions.pop(sender.lower(), None) is None:
            return False
        self._write(sessions)
        return True

    def _write(self, sessions):
        """Whole-file, atomic: a half-written store is one nobody can read."""
        os.makedirs(self.root, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w", dir=self.root, prefix=f".{self.seat}-", suffix=".json", delete=False
        )
        try:
            with handle:
                json.dump({"sessions": sessions}, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(handle.name, self.path)
        except BaseException:
            try:
                os.unlink(handle.name)
            except OSError:
                pass
            raise
