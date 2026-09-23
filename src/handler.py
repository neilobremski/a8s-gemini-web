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
  profile not signed in, the seat unreachable. Those are operator-fixable, and
  the message is worth keeping until they are fixed. A failure that lands
  *after* the message was typed in exits 0 for the same reason as the first
  rule: it is already in the conversation.
"""
import os
import subprocess

import browser
import gemini
import identity
from store import SessionStore

MAX_BODY = 4000


def allowed(sender, spec):
    """An empty allowlist means nobody — this seat drives a signed-in account."""
    names = {name.strip().lower() for name in (spec or "").split(",") if name.strip()}
    return sender.lower() in names


def _tell(recipient, body):
    subprocess.run(["tell", recipient, "-"], input=body, text=True, check=False)


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


def _round_trip(seat, sender, message, runner, store, model, notes, typed):
    """One correspondent's conversation, resumed or created, and one turn in it.

    `typed` records the moment the message itself reaches Gemini, because that
    is what decides whether a failure after it should be retried.
    """
    entry = store.get(sender) or {}
    label = ""
    baseline = ""
    if entry.get("url"):
        try:
            gemini.open_conversation(runner, entry["url"])
            label = gemini.prompt_label(gemini.page_snapshot(runner), runner.seat)
            baseline = gemini.read(runner).text
        except gemini.GeminiError as exc:
            notes.append(f"the stored conversation was not usable ({exc}); starting a new one")
            entry = {}

    if not entry.get("url"):
        gemini.open_app(runner)
        snapshot = gemini.page_snapshot(runner)
        label = gemini.prompt_label(snapshot, runner.seat)
        notes.append(gemini.choose_model(runner, model, snapshot))
        opening = gemini.send_turn(runner, label, identity.preamble(seat, sender))
        store.remember(sender, gemini.conversation_url(runner))
        if gemini.rate_limited(opening.reply):
            return opening
        baseline = opening.reply

    gemini.send(runner, label, message)
    typed.append(True)
    return gemini.await_reply(runner, message, baseline)


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
    spec = allow if allow is not None else os.environ.get("A8S_GEMINI_ALLOW", "")
    if not allowed(sender, spec):
        send(sender, f"{seat}: refusing — {sender} is not on this seat's allowlist.")
        return 0

    profile = browser_seat or os.environ.get("A8S_GEMINI_BROWSER_SEAT", "")
    if not profile:
        send(
            sender,
            f"{seat}: not configured — this node has no browser seat. Set "
            "A8S_GEMINI_BROWSER_SEAT to the a8s-browser seat that is signed in to Gemini.",
        )
        return 1

    model = model if model is not None else os.environ.get("A8S_GEMINI_MODEL", "")
    runner = runner or browser.BrowserSeat(profile, launcher=browser_cmd)
    store = SessionStore(seat)
    notes = []
    typed = []

    try:
        turn = _round_trip(seat, sender, message, runner, store, model, notes, typed)
    except (gemini.GeminiError, browser.BrowserError) as exc:
        notes.insert(0, store.warning)
        send(sender, _compose(f"{seat}: {exc}", notes))
        # Keep the message only while it has not been typed in. Past that
        # point a requeue would ask Gemini the same question twice.
        return 0 if typed else 1
    notes.insert(0, store.warning)

    if gemini.rate_limited(turn.reply):
        send(
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
    send(sender, _compose(reply, notes))
    return 0
