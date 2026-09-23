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
import uuid

SUFFIX = ".pending"
CLAIM = ".claim-"

# A claim older than this is assumed to belong to a run that died mid-send and
# is put back. `tell` takes milliseconds, so nothing healthy is ever reclaimed;
# without it one crashed flush would strand a reply nobody ever sees again.
RECLAIM_SECONDS = 300.0


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

    def _reclaim(self, names):
        """Put back anything a dead run claimed and never finished.

        Returns whether it restored any, because a restored file is not in the
        listing that was just taken and the caller has to look again.
        """
        restored = False
        for name in names:
            if CLAIM not in name:
                continue
            full = os.path.join(self.path, name)
            try:
                if time.time() - os.path.getmtime(full) < RECLAIM_SECONDS:
                    continue
                os.rename(full, os.path.join(self.path, name.split(CLAIM, 1)[0]))
                restored = True
            except OSError:
                continue
        return restored

    def waiting(self):
        """Each held reply as (path, recipient, body), oldest first.

        A file that is not readable JSON is skipped rather than raised on: it
        is one lost reply, and dying here would lose the turn that is running.
        A claimed file belongs to a flush in progress and is not listed.
        """
        try:
            names = sorted(os.listdir(self.path))
        except OSError:
            return []
        if self._reclaim(names):
            try:
                names = sorted(os.listdir(self.path))
            except OSError:
                return []
        names = [name for name in names if name.endswith(".json")]
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

    def _claim(self, path):
        """Take exclusive hold of one held reply, or None if someone else did.

        A rename is the claim. Two flushers can both list a file, but only one
        of them can move it — the other's rename finds nothing there and it
        goes on to the next. Reading a file and deleting it after the send is
        not exclusive consumption, and two runs then deliver the same answer
        twice.
        """
        claimed = f"{path}{CLAIM}{os.getpid()}-{uuid.uuid4().hex[:8]}"
        try:
            os.rename(path, claimed)
        except OSError:
            return None
        return claimed

    @staticmethod
    def _restore(claimed, path):
        """Put a claim back so the next run finds it, in its original order."""
        try:
            os.rename(claimed, path)
        except OSError:
            pass

    def flush(self, send):
        """Try every held reply. Returns (delivered, still waiting).

        `send` answers with a status, 0 for delivered, and is the network
        sender rather than whatever the current call does with its own reply.
        A reply that fails again is put back where it was, in order, and the
        next run tries it.
        """
        delivered = 0
        for path, recipient, body in self.waiting():
            claimed = self._claim(path)
            if claimed is None:
                continue
            try:
                ok = int(send(recipient, body) or 0) == 0
            except OSError:
                self._restore(claimed, path)
                break
            except BaseException:
                self._restore(claimed, path)
                raise
            if not ok:
                self._restore(claimed, path)
                break
            self.drop(claimed)
            delivered += 1
        return delivered, len(self.waiting())

    @staticmethod
    def drop(path):
        try:
            os.unlink(path)
        except OSError:
            pass
