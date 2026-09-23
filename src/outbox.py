"""Replies that were produced but not delivered.

A turn spends a real conversation with Gemini. If `tell` then fails — the
router down, the broker unreachable — the answer exists and nobody has it, and
re-running the turn to get it again would ask Gemini the same question twice.
So a reply that cannot be handed over is written here, and the next run of this
seat delivers it before it does anything else.

One file per reply, named so they sort oldest first, each written atomically.
There is no read-modify-write and so no lock: a run adds files or removes the
ones it delivered, and two runs doing that at once cannot corrupt each other.
"""
import json
import os
import tempfile
import time

SUFFIX = ".pending"


class Outbox:
    """Undelivered replies for one seat, oldest first."""

    def __init__(self, seat, root):
        self.seat = seat
        self.root = root

    @property
    def path(self):
        return os.path.join(self.root, f"{self.seat}{SUFFIX}")

    def keep(self, recipient, body):
        """Hold a reply that could not be delivered. Returns its file."""
        os.makedirs(self.path, exist_ok=True)
        payload = {
            "to": recipient,
            "body": body,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        handle = tempfile.NamedTemporaryFile(
            "w", dir=self.path, prefix=f"{time.time():014.3f}-", suffix=".tmp", delete=False
        )
        with handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        final = handle.name[: -len(".tmp")] + ".json"
        os.replace(handle.name, final)
        return final

    def waiting(self):
        """Each held reply as (path, recipient, body), oldest first.

        A file that is not readable JSON is skipped rather than raised on: it
        is one lost reply, and dying here would lose the turn that is running.
        """
        try:
            names = sorted(name for name in os.listdir(self.path) if name.endswith(".json"))
        except OSError:
            return []
        held = []
        for name in names:
            full = os.path.join(self.path, name)
            try:
                with open(full) as handle:
                    payload = json.load(handle)
                held.append((full, str(payload["to"]), str(payload["body"])))
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return held

    def flush(self, send):
        """Try every held reply. Returns (delivered, still waiting).

        `send` is the same callable the handler uses and answers with a status:
        0 for delivered. A reply that fails again stays where it is, in order,
        and the next run tries it.
        """
        delivered = 0
        for path, recipient, body in self.waiting():
            if send(recipient, body) != 0:
                break
            self.drop(path)
            delivered += 1
        return delivered, len(self.waiting())

    @staticmethod
    def drop(path):
        try:
            os.unlink(path)
        except OSError:
            pass
