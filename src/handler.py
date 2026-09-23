"""a8s wake entry point: a tell in, Gemini's answer back out.

Exit status is not cosmetic — a8s acks the envelope on 0 and requeues it on
anything else, so the code says what should happen to the message:

- **0** when the conversation was driven and something was delivered, including
  a reply cut short by the timeout and Gemini's own rate-limit refusal. The
  message reached Gemini; sending it again would type it in twice.
- **0** for a sender who is not on the allowlist. A refusal is a final verdict,
  and a requeue would repeat it three times and arm a backoff that delays the
  senders this seat does answer.
- **1** when the turn could not be run at all — no browser seat configured, the
  profile not signed in, the seat unreachable, another run holding this seat.
  Those are operator-fixable, and the message is worth keeping until they are
  fixed. A failure that lands *after* the message was typed in exits 0 for the
  same reason as the first rule: it is already in the conversation.

Two cases sit between those and are handled rather than guessed at. A send that
fails on the keystroke that submits is *not known* to have failed, so the page
is asked before the message is ever sent again. And a reply that is produced
but cannot be handed to `tell` is held on disk, because the turn that produced
it has already been spent and re-running it would ask Gemini the same question
twice.
"""
import os
import subprocess
import sys

import browser
import gemini
import identity
import store as store_module
from outbox import Outbox
from store import SessionStore, StoreError

MAX_BODY = 4000

# How long a wake waits for another run of this seat to finish its turn. A turn
# is bounded by gemini.TURN_TIMEOUT_SECONDS, so a longer wait here would spend
# this wake queueing; requeueing the message costs nothing and frees the seat.
TURN_LOCK_SECONDS = 30.0

UNCERTAIN_NOTE = (
    "this seat cannot tell whether Gemini received your message. It was NOT sent "
    "again: a duplicate question in a live conversation is worse than one you can "
    "repeat yourself. Check the conversation, and send it again if it is not there."
)


def allowed(sender, spec):
    """An empty allowlist means nobody — this seat drives a signed-in account."""
    names = {name.strip().lower() for name in (spec or "").split(",") if name.strip()}
    return sender.lower() in names


def _tell(recipient, body):
    """Hand one reply to a8s. Returns tell's exit status: 0 is delivered."""
    return subprocess.run(["tell", recipient, "-"], input=body, text=True, check=False).returncode


def _capped(body):
    if len(body) <= MAX_BODY:
        return body
    return body[: MAX_BODY - 40].rstrip() + "\n… (cut at this seat's reply cap)"


def _compose(reply, notes):
    parts = [reply.strip()] if reply.strip() else []
    kept = [note for note in notes if note]
    if kept:
        parts.append("--\n" + "\n".join(kept))
    return _capped("\n\n".join(parts))


def _deliver(send, outbox, recipient, body):
    """Send a reply, and keep it if that fails.

    `send` answers with an exit status; one that answers with nothing counts as
    delivered, which is what an in-process caller means. A reply that cannot be
    handed over is held on disk and delivered by the next run of this seat,
    without asking Gemini anything a second time.
    """
    if int(send(recipient, body) or 0) == 0:
        return True
    path = outbox.keep(recipient, body)
    print(
        f"a8s-gemini-web: tell to {recipient} failed; the reply is held at {path} "
        "and the next run of this seat will try again",
        file=sys.stderr,
    )
    return False


def _reconcile(runner, before, notes, state, exc):
    """Settle whether an uncertain send actually reached the conversation.

    The page is the record. If it grew a turn from this side, the message is in
    and this turn carries on. If it plainly did not, the message was never sent
    and the caller keeps it. If the page cannot be read either, nobody knows,
    and the one thing this must not do is guess "unsent" and ask again.
    """
    try:
        after = gemini.read(runner)
    except (gemini.GeminiError, browser.BrowserError):
        state["typed"] = True
        state["uncertain"] = True
        raise exc from None
    if before and after.counts:
        if after.counts[0] > before[0]:
            notes.append(
                "the browser lost its answer while sending, but the message is in the "
                "conversation, so it was not sent again."
            )
            state["typed"] = True
            return
        raise gemini.GeminiError(
            f"{exc} The conversation does not show it, so it was not sent."
        ) from None
    state["typed"] = True
    state["uncertain"] = True
    raise exc from None


def _round_trip(seat, sender, message, runner, store, model, notes, state):
    """One correspondent's conversation, resumed or created, and one turn in it.

    `state["typed"]` records the moment the message itself reaches Gemini,
    because that is what decides whether a failure after it should be retried.
    """
    entry = store.get(sender) or {}
    label = ""
    baseline = ""
    counts = None
    if entry.get("url"):
        try:
            gemini.open_conversation(runner, entry["url"])
            label, _ = gemini.await_prompt(runner)
            before = gemini.read(runner)
            baseline, counts = before.text, before.counts
        except gemini.GeminiError as exc:
            notes.append(f"the stored conversation was not usable ({exc}); starting a new one")
            entry = {}

    if not entry.get("url"):
        gemini.open_app(runner)
        label, snapshot = gemini.await_prompt(runner)
        notes.append(gemini.choose_model(runner, model, snapshot))
        opening = gemini.send_turn(runner, label, identity.preamble(seat, sender))
        try:
            store.remember(sender, gemini.conversation_url(runner))
        except StoreError as exc:
            # The conversation exists and holds the preamble, but nothing can
            # come back to it. Your message has not been typed yet, so it is
            # kept: fixing the store and retrying costs one stray empty chat.
            raise gemini.GeminiError(
                f"{exc}. Your message was not sent — fix that and it will be retried."
            ) from exc
        if gemini.rate_limited(opening.reply):
            return opening
        baseline, counts = opening.reply, opening.counts

    try:
        gemini.send(runner, label, message)
    except gemini.SendUncertain as exc:
        _reconcile(runner, counts, notes, state, exc)
    else:
        state["typed"] = True
    return gemini.await_reply(runner, message, baseline, counts)


def handle(
    seat,
    sender,
    message,
    browser_seat=None,
    browser_cmd=None,
    allow=None,
    model=None,
    runner=None,
    send=None,
):
    """`browser_seat`, `browser_cmd`, `allow` and `model` come from the
    definition's argv (a8s vars); unset, they fall back to the environment so a
    hand-run `handle` behaves the same way."""
    send = send or _tell
    store = SessionStore(seat)
    outbox = Outbox(seat, store.root)
    outbox.flush(lambda to, body: int(send(to, body) or 0))

    spec = allow if allow is not None else os.environ.get("A8S_GEMINI_ALLOW", "")
    if not allowed(sender, spec):
        _deliver(
            send, outbox, sender,
            f"{seat}: refusing — {sender} is not on this seat's allowlist.",
        )
        return 0

    profile = browser_seat or os.environ.get("A8S_GEMINI_BROWSER_SEAT", "")
    if not profile:
        _deliver(
            send,
            outbox,
            sender,
            f"{seat}: not configured — this node has no browser seat. Set "
            "A8S_GEMINI_BROWSER_SEAT to the a8s-browser seat that is signed in to Gemini.",
        )
        return 1

    model = model if model is not None else os.environ.get("A8S_GEMINI_MODEL", "")
    runner = runner or browser.BrowserSeat(profile, launcher=browser_cmd)

    try:
        with store_module.turn_lock(seat, store.root, timeout=TURN_LOCK_SECONDS):
            return _turn(seat, sender, message, runner, store, model, send, outbox)
    except store_module.Busy:
        # One browser window, one conversation at a time. The message is kept
        # rather than answered, so nothing interleaves in the page.
        print(
            f"a8s-gemini-web: seat {seat!r} is busy with another turn; "
            "this message stays queued",
            file=sys.stderr,
        )
        return 1
    except StoreError as exc:
        _deliver(send, outbox, sender, f"{seat}: {exc}")
        return 1


def _turn(seat, sender, message, runner, store, model, send, outbox):
    notes = []
    state = {}

    try:
        turn = _round_trip(seat, sender, message, runner, store, model, notes, state)
    except (gemini.GeminiError, browser.BrowserError) as exc:
        notes.insert(0, store.warning)
        if state.get("uncertain"):
            notes.append(UNCERTAIN_NOTE)
        _deliver(send, outbox, sender, _compose(f"{seat}: {exc}", notes))
        # Keep the message only while it has not been typed in. Past that
        # point a requeue would ask Gemini the same question twice.
        return 0 if state.get("typed") else 1
    notes.insert(0, store.warning)

    if gemini.rate_limited(turn.reply):
        _deliver(
            send,
            outbox,
            sender,
            _capped(
                f"{seat}: Gemini is rate-limiting this seat, so your message was not "
                f"answered. Retry later.\n\nGemini said: {turn.reply.strip()}"
            ),
        )
        return 0

    notes.append(turn.note)
    hit = gemini.trouble(turn.reply)
    if hit:
        notes.append(f"Gemini's own trouble wording is in this reply ({hit!r}).")
    reply = turn.reply.strip() or f"{seat}: nothing came back from Gemini for this message."
    _deliver(send, outbox, sender, _compose(reply, notes))
    return 0
