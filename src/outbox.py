"""Replies that were produced but not delivered.

A turn spends a real conversation with Gemini. If `tell` then fails — the
router down, the broker unreachable — the answer exists and nobody has it, and
re-running the turn to get it again would ask Gemini the same question twice.
So a reply that cannot be handed over is written here, and the next run of this
seat delivers it before it does anything else.

One file per reply, named so they sort oldest first, each written atomically.
Two things keep a reply from going out twice:

- **One flusher at a time.** `flush` holds an exclusive lock for its whole run.
  A second run finds it taken and leaves the queue alone rather than racing it.
- **A claim carries its own age.** Inside the lock, a reply is renamed before
  it is sent, and the claim's *name* records when it was taken. A rename keeps
  the file's mtime, so an mtime-based expiry would call the brand-new claim on
  an hour-old reply already stale — and a second run would deliver it again
  while the first send was still in flight. The name is written by the rename
  itself, so there is no window in which a live claim looks abandoned.

Recovery is what the age is for: a run that dies mid-send drops its lock with
it, and the next run puts its claim back once the claim is old enough that
nothing can still be sending it.
"""
import json
import os
import tempfile
import time
import uuid

from store import Busy, FileLock

SUFFIX = ".pending"
CLAIM = ".claim-"

# How long a claim is respected before it is taken to belong to a run that
# died. `tell` takes milliseconds and only one flusher runs at a time, so
# nothing healthy is ever reclaimed; without it a crash would strand a reply.
RECLAIM_SECONDS = 300.0


class Outbox:
    """Undelivered replies for one seat, oldest first."""

    def __init__(self, seat, root):
        self.seat = seat
        self.root = root

    @property
    def path(self):
        return os.path.join(self.root, f"{self.seat}{SUFFIX}")

    @property
    def lock_path(self):
        return os.path.join(self.root, f".{self.seat}.flush.lock")

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
        """Each unclaimed reply as (path, recipient, body), oldest first.

        A file that is not readable JSON is skipped rather than raised on: it
        is one lost reply, and dying here would lose the turn that is running.
        A claimed file belongs to a flush and is not listed; only `flush` puts
        claims back, and only under the lock.
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

        `send` answers with a status, 0 for delivered, and is the network
        sender rather than whatever the current call does with its own reply.
        A reply that fails again is put back where it was, in order, and the
        next run tries it.

        A run that cannot take the lock does nothing at all: another run is
        already working the same queue, and both of them delivering is the
        failure this exists to prevent.
        """
        if not os.path.isdir(self.path):
            return 0, 0
        try:
            with FileLock(self.lock_path):
                self._recover()
                return self._send_each(send)
        except Busy:
            return 0, len(self.waiting())

    def _send_each(self, send):
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

    def _claim(self, path):
        """Take hold of one held reply, stamping the claim with the time.

        The stamp is in the name because the rename that creates it is the same
        act that takes the claim. Reading the age off the file instead would
        read the moment the reply was *enqueued*, which says nothing about when
        somebody started sending it.
        """
        claimed = f"{path}{CLAIM}{time.time():.3f}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        try:
            os.rename(path, claimed)
        except OSError:
            return None
        return claimed

    @staticmethod
    def _claimed_at(name):
        """When a claim was taken, read from its name; None if unreadable."""
        try:
            return float(name.split(CLAIM, 1)[1].split("-", 1)[0])
        except (IndexError, ValueError):
            return None

    def _recover(self):
        """Put back claims old enough that nothing can still be sending them.

        Only called inside the lock. A claim with no readable stamp was not
        made by this code, so it is restored rather than left forever.
        """
        try:
            names = os.listdir(self.path)
        except OSError:
            return
        for name in names:
            if CLAIM not in name:
                continue
            taken = self._claimed_at(name)
            if taken is not None and time.time() - taken < RECLAIM_SECONDS:
                continue
            try:
                os.rename(
                    os.path.join(self.path, name),
                    os.path.join(self.path, name.split(CLAIM, 1)[0]),
                )
            except OSError:
                continue

    @staticmethod
    def _restore(claimed, path):
        """Put a claim back so the next run finds it, in its original order."""
        try:
            os.rename(claimed, path)
        except OSError:
            pass

    @staticmethod
    def drop(path):
        try:
            os.unlink(path)
        except OSError:
            pass
