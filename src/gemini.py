"""Everything that knows what Gemini's web interface looks like.

**This is the file that breaks when Google changes the interface.** That is not
a defect in this driver, it is the standing cost of driving a web app that
publishes no API, and patching this module is expected maintenance rather than
a bug report. Every selector, label, heading and URL shape the program relies
on is here, so a break is one file to read and one file to fix.
`docs/gemini-ui.md` lists each one and how to re-derive it from a snapshot.

Two sources, both named in that doc:

*Observed on the live interface, 2026-09-23, through `a8s-browser snap`* — the
prompt box's name, that a new chat has no id until the first message is sent,
the `You said` / `Gemini said` headings that separate the turns, the button
cluster that marks a finished reply, and the mode picker's name. The interface
changes without notice, so these are current readings and not constants.

*From b3t* (`apps/b3t/gemini.py` in `neilobremski/bin`, which drives Gemini Web
through playwright-cli today) — the app URL, the sign-in check, finding the
prompt box as the snapshot's `textbox`, sending with fill-then-Enter, and
polling snapshots for a completion signal rather than guessing a wait. b3t
needs the same fixes whenever this module does.

Unverified and best effort: naming a conversation after its correspondent, and
selecting a model. Both are non-fatal by design — a turn that cannot rename or
cannot switch models still delivers its reply.
"""
import re
import shlex
import time

from browser import BrowserError

APP_URL = "https://gemini.google.com/app"
SIGN_IN_HOST = "accounts.google.com"

# How long a page is given to settle after a navigation before it is read.
PAGE_LOAD_SECONDS = 3

# A finished reply is announced by the page (see `turn_complete`). The settle
# window is the backstop for when that announcement changes shape: text that
# has not moved for this long counts as done. The timeout bounds the whole wait
# and returns whatever arrived.
POLL_SECONDS = 2.5
SETTLE_SECONDS = 6.0
TURN_TIMEOUT_SECONDS = 180.0

# How long the URL is given to acquire a conversation id after the first
# message. Gemini rewrites /app to /app/<id> once the turn is under way.
URL_WAIT_SECONDS = 15.0

# The prompt box is a textbox in the snapshot, preferring one whose name says
# what it is for. It is a Quill editor rather than a real textarea, so it is
# reached by its accessible name and never by textarea semantics.
PROMPT_HINTS = ("prompt", "gemini", "ask")
PROMPT_FALLBACK_LABEL = "Enter a prompt for Gemini"

# Each turn is announced by a heading: the person's at level 5, Gemini's at
# level 6. The model heading is what anchors reply extraction.
MODEL_TURN_HEADING = "Gemini said"
USER_TURN_HEADING = "You said"

# A finished model turn grows a button cluster. Its presence after the last
# `Gemini said` heading is the completion signal, in place of guessing from
# text alone. Every label here is distinctive enough that one is enough.
COMPLETION_BUTTONS = ("Good response", "Bad response", "Redo", "Show more options")

# Snapshot roles that carry reply text. Buttons, headings and the rest of the
# page's furniture are not part of what Gemini said.
TEXT_ROLES = ("paragraph", "text", "listitem", "code", "blockquote", "cell", "link")
# Roles that end a turn. A button does not: a reply with a code block in it
# carries a copy button of its own, and stopping there would cut the reply in
# half. The prompt box is what actually sits below the last turn, which is also
# what keeps the page's own disclaimer out of a reply that is still streaming.
STOP_ROLES = ("heading", "textbox", "contentinfo", "form", "navigation", "banner")

# The whole conversation as rendered text, used when the headings stop matching
# — the reply is then whatever follows the message just sent.
HISTORY_SELECTOR = "main"
# Page furniture that rendered text picks up after the last reply.
TRAILING_NOISE = ("Gemini is AI and can make mistakes", *COMPLETION_BUTTONS)

# Gemini answers a burst with a quota refusal of its own, which arrives as a
# reply like any other and has to be recognised rather than relayed as an
# answer. The window keeps a long answer *about* rate limiting from reading as
# one.
RATE_LIMIT_PHRASES = (
    "you've reached your limit",
    "you have reached your limit",
    "you've hit your limit",
    "reached your daily limit",
    "too many requests",
    "rate limit",
    "try again later",
)
RATE_LIMIT_SCAN_CHARS = 240
RATE_LIMIT_MAX_CHARS = 600

# b3t's wording for a turn Gemini could not finish.
TROUBLE_PHRASES = ("couldn't generate", "something went wrong")

# The model switcher names the model it is on, so the current model is readable
# with no clicking at all. Changing it means opening an Angular menu, which is
# the part that may not answer a selector click.
MODE_PICKER_PREFIX = "Open mode picker, currently"
MODEL_BUTTON_SELECTORS = (
    'button[aria-label^="Open mode picker"]',
    'button[data-test-id="bard-mode-menu-button"]',
    ".gds-mode-switch-button",
)

# Naming a conversation is cosmetic — the stored URL identifies it, and Gemini
# titles a chat from its first message anyway, which here is the preamble. None
# of this was seen in a snapshot; it is a best attempt.
CONVERSATION_MENU_SELECTORS = (
    'button[aria-label^="Show more options"]',
    'button[data-test-id="actions-menu-button"]',
)
RENAME_ITEM = "Rename"
RENAME_INPUT_SELECTORS = (
    '[role="dialog"] input',
    "mat-dialog-container input",
    'input[data-test-id="conversation-title-input"]',
)

# `- role "name" [ref=e1] [level=6]: value` — one node of a snapshot.
NODE = re.compile(
    r'^-\s+(?P<role>[A-Za-z][\w-]*)'
    r'(?:\s+"(?P<name>[^"]*)")?'
    r'(?P<attrs>(?:\s*\[[^\]]*\])*)'
    r'(?:\s*:\s*(?P<value>.*))?$'
)


class GeminiError(Exception):
    """The page did not look the way this module expects."""


class Reading:
    """One look at the conversation: the newest reply, and whether the page
    says that reply is finished."""

    def __init__(self, text, complete):
        self.text = text
        self.complete = complete


class Turn:
    """The outcome of one message: the reply, and whether it finished."""

    def __init__(self, reply, complete, seconds, note=""):
        self.reply = reply
        self.complete = complete
        self.seconds = seconds
        self.note = note


def _now():
    return time.monotonic()


def _sleep(seconds):
    time.sleep(seconds)


def node(line):
    """One snapshot line as (role, name, value); ("", "", "") for anything else."""
    match = NODE.match(line.strip())
    if not match:
        return "", "", ""
    return (
        match.group("role"),
        (match.group("name") or "").strip(),
        (match.group("value") or "").strip(),
    )


def poll_script():
    """One look at the page: its structure, and its text.

    The snapshot answers "is the turn done" and carries the reply; the rendered
    text is the fallback that needs no headings at all.
    """
    return f"snap\ntext {shlex.quote(HISTORY_SELECTOR)}"


def send_script(label, message):
    """The script that types one message and sends it.

    A command script is one command per line, so a multi-line message cannot be
    a single `fill`. The first line fills the box — which focuses it — and each
    further line is a newline keystroke plus a `type`, whose argument
    a8s-browser takes verbatim; that is what carries an apostrophe or a quote
    through unharmed. The first line goes through `shlex.quote` for the same
    reason. Sending is Enter straight after, which is b3t's proven move.
    """
    lines = message.splitlines() or [""]
    script = [f"fill {shlex.quote(label)} {shlex.quote(lines[0])}"]
    for line in lines[1:]:
        script.append("press Shift+Enter")
        if line.strip():
            script.append(f"type {line.strip()}")
    script.append("press Enter")
    return "\n".join(script)


def textbox_label(snapshot):
    """The prompt box's accessible name, read from a snapshot (b3t's rule).

    a8s-browser fills by label or selector rather than by ref, so what this
    takes from the snapshot is the *name* — which is the aria-label the page's
    own markup carries, and what `fill` matches on.
    """
    fallback = None
    for line in snapshot.splitlines():
        lowered = line.lower()
        if "textbox" not in lowered:
            continue
        match = re.search(r'"([^"]+)"', line)
        if not match:
            continue
        name = match.group(1)
        if any(hint in lowered for hint in PROMPT_HINTS):
            return name
        if fallback is None:
            fallback = name
    return fallback


def current_model(snapshot):
    """The model Gemini is on, read off the mode picker without opening it."""
    for line in snapshot.splitlines():
        role, name, _ = node(line)
        if role == "button" and name.startswith(MODE_PICKER_PREFIX):
            return name[len(MODE_PICKER_PREFIX):].strip(" :,")
    return ""


def _last_model_turn(lines):
    found = -1
    for index, line in enumerate(lines):
        role, name, _ = node(line)
        if role == "heading" and name == MODEL_TURN_HEADING:
            found = index
    return found


def reply_block(snapshot):
    """The newest model turn's text, taken from the snapshot's own structure.

    Anchored on the last `Gemini said` heading and stopped at whatever ends the
    turn, so no assumption is made about the markup inside a turn beyond which
    roles carry text.
    """
    lines = snapshot.splitlines()
    start = _last_model_turn(lines)
    if start < 0:
        return ""
    collected = []
    for line in lines[start + 1:]:
        role, name, value = node(line)
        if role in STOP_ROLES:
            break
        if role == "button" and name in COMPLETION_BUTTONS:
            break
        if role in TEXT_ROLES:
            text = value or name
            if text:
                collected.append(text)
    return "\n".join(collected).strip()


def turn_complete(snapshot):
    """Whether the page says the newest model turn has finished.

    A finished turn carries the rate-it-and-redo-it buttons; one that is still
    streaming does not. This is the primary completion signal — settling on
    unchanged text is only the backstop for when these labels change.
    """
    lines = snapshot.splitlines()
    start = _last_model_turn(lines)
    if start < 0:
        return False
    for line in lines[start + 1:]:
        role, name, _ = node(line)
        if role == "button" and name in COMPLETION_BUTTONS:
            return True
    return False


def conversation_id(url):
    """The id in `https://gemini.google.com/app/<id>`, or "" for a fresh app."""
    marker = "/app/"
    if marker not in url:
        return ""
    return url.split(marker, 1)[1].split("?", 1)[0].split("#", 1)[0].strip("/")


def rate_limited(text):
    """Gemini's own quota refusal, which arrives as a reply.

    Matched only near the front of a short answer: a long reply that explains
    HTTP rate limiting is an answer, not a refusal, and withholding it would be
    the worse mistake.
    """
    if not text or len(text) > RATE_LIMIT_MAX_CHARS:
        return False
    window = text[:RATE_LIMIT_SCAN_CHARS].lower()
    return any(phrase in window for phrase in RATE_LIMIT_PHRASES)


def trouble(text):
    """Gemini's wording for a turn it could not finish, or ""."""
    lowered = (text or "").lower()
    for phrase in TROUBLE_PHRASES:
        if phrase in lowered:
            return phrase
    return ""


def _tail_after(history, sent):
    """What the rendered conversation says after the message just sent."""
    if not history or not sent:
        return ""
    needle = sent.strip()
    index = history.rfind(needle)
    if index < 0:
        first = needle.splitlines()[0].strip()
        index = history.rfind(first) if first else -1
        if index < 0:
            return ""
        needle = first
    tail = history[index + len(needle):]
    for noise in TRAILING_NOISE:
        tail = tail.split(noise, 1)[0]
    return tail.strip()


def extract_reply(snapshot, history, sent):
    """The newest reply: the snapshot's own turn structure, else the text.

    The structure comes first because it is unambiguous — the last `Gemini
    said` heading is the turn that just ran. The rendered text is the fallback
    for when those headings change, and it is anchored on the message that was
    just sent, which is text this driver already knows.
    """
    block = reply_block(snapshot)
    if block:
        return block
    return _tail_after(history, sent)


def _run(browser, script, doing):
    try:
        transcript = browser.run(script)
    except BrowserError as exc:
        raise GeminiError(f"{doing}: {exc}") from exc
    if not transcript.ok:
        raise GeminiError(f"{doing}: {transcript.error}")
    return transcript


def _first_output(transcript, verb):
    outputs = transcript.outputs(verb)
    return outputs[0] if outputs else ""


def _snapshot_of(transcript, browser):
    """The snapshot a `snap` step attached, read off disk."""
    paths = [path for path in transcript.files if path.endswith(".txt")] or transcript.files
    if not paths:
        raise GeminiError(
            f"a8s-browser attached no snapshot for seat {browser.seat!r}, so the page "
            "cannot be read"
        )
    try:
        with open(paths[0]) as handle:
            return handle.read()
    except OSError as exc:
        raise GeminiError(f"the page snapshot at {paths[0]} could not be read: {exc}") from exc


def current_url(browser):
    return _first_output(_run(browser, "url", "reading the browser's URL"), "url").strip()


def _require_signed_in(browser, url):
    if SIGN_IN_HOST in url:
        raise GeminiError(
            f"browser seat {browser.seat!r} is not signed in to Gemini — the page is on "
            f"{SIGN_IN_HOST}. Sign it in by hand once (`a8s-browser -s {browser.seat} open`, "
            "then log in in the window that opens); this driver never signs in to anything."
        )


def open_app(browser):
    """A fresh Gemini chat."""
    script = f"go {APP_URL}\nwait {PAGE_LOAD_SECONDS}\nurl"
    url = _first_output(_run(browser, script, "opening Gemini"), "url").strip()
    _require_signed_in(browser, url)
    return url


def open_conversation(browser, url):
    """An existing conversation, by the URL this correspondent was given."""
    wanted = conversation_id(url)
    script = f"go {url}\nwait {PAGE_LOAD_SECONDS}\nurl"
    landed = _first_output(
        _run(browser, script, "opening the stored conversation"), "url"
    ).strip()
    _require_signed_in(browser, landed)
    if wanted and conversation_id(landed) != wanted:
        raise GeminiError(
            f"the stored conversation {wanted} did not open — the browser landed on "
            f"{landed}, so it was probably deleted in Gemini"
        )
    return landed


def page_snapshot(browser):
    return _snapshot_of(_run(browser, "snap", "snapshotting the page"), browser)


def prompt_label(snapshot, seat=""):
    """The prompt box's label, or a failure that says where to look."""
    label = textbox_label(snapshot)
    if not label:
        raise GeminiError(
            "no textbox in the page snapshot — Gemini's prompt box was not found "
            f"(it is normally named {PROMPT_FALLBACK_LABEL!r}). "
            f"`a8s-browser -s {seat or '<seat>'} snap` shows what the page looks like now."
        )
    return label


def conversation_url(browser, now=None, sleep=None):
    """The conversation's own URL, waited for until Gemini assigns one."""
    now, sleep = now or _now, sleep or _sleep
    deadline = now() + URL_WAIT_SECONDS
    url = current_url(browser)
    while not conversation_id(url):
        if now() >= deadline:
            raise GeminiError(
                f"Gemini stayed on {url} instead of a conversation URL, so this "
                "correspondent has no conversation to come back to"
            )
        sleep(POLL_SECONDS)
        url = current_url(browser)
    return url


def read(browser, sent=""):
    """One look at the page: the newest reply, and whether it is finished."""
    transcript = _run(browser, poll_script(), "reading the conversation")
    snapshot = _snapshot_of(transcript, browser)
    history = _first_output(transcript, "text")
    return Reading(extract_reply(snapshot, history, sent), turn_complete(snapshot))


def await_reply(browser, sent, baseline="", now=None, sleep=None):
    """Wait for the turn Gemini is writing to finish, and return it.

    Finished means the page says so, or — if those labels have changed — that
    the text has not moved for SETTLE_SECONDS. `baseline` is the reply that was
    already on the page before this message went in: text that still equals it
    is the previous turn, not this one, which is also how a message that never
    reached the prompt box is caught instead of answered with the last reply.
    """
    now, sleep = now or _now, sleep or _sleep
    started = now()
    last = ""
    stable_since = None
    while True:
        reading = read(browser, sent)
        text = reading.text if reading.text and reading.text != baseline else ""
        if text and text == last:
            if stable_since is None:
                stable_since = now()
        else:
            stable_since = None
            last = text
        if text and reading.complete:
            return Turn(text, True, now() - started)
        if text and stable_since is not None and now() - stable_since >= SETTLE_SECONDS:
            return Turn(
                text,
                True,
                now() - started,
                "the page never marked this turn finished; it is being reported because "
                "the text stopped changing.",
            )
        elapsed = now() - started
        if elapsed >= TURN_TIMEOUT_SECONDS:
            if last:
                note = (
                    f"cut short: Gemini was still writing after {elapsed:.0f}s, "
                    "so this reply may be unfinished."
                )
            else:
                note = (
                    f"no reply appeared within {elapsed:.0f}s. The message may not have "
                    "reached Gemini's prompt box, or the turn headings in gemini.py no "
                    "longer match the page."
                )
            return Turn(last, False, elapsed, note)
        sleep(POLL_SECONDS)


def send(browser, label, message):
    _run(browser, send_script(label, message), "typing the message into Gemini")


def send_turn(browser, label, message, baseline="", now=None, sleep=None):
    send(browser, label, message)
    return await_reply(browser, message, baseline, now=now, sleep=sleep)


def _dismiss_menu(browser):
    """Leave no menu open behind a step that failed part-way through one."""
    try:
        browser.run("press Escape")
    except BrowserError:
        pass


def _click_first(browser, selectors, doing):
    """Click the first selector that matches. Returns "" or why none did."""
    failures = []
    for selector in selectors:
        script = f"click {shlex.quote(selector)}\nwait 1"
        try:
            transcript = browser.run(script)
        except BrowserError as exc:
            failures.append(f"{selector}: {exc}")
            continue
        if transcript.ok:
            return ""
        failures.append(f"{selector}: {transcript.error}")
    return f"{doing} matched nothing: " + "; ".join(failures)


def choose_model(browser, model, snapshot=""):
    """Pick a model from Gemini's switcher. Best effort, and never fatal.

    The mode picker names the model it is already on, so a seat that is on the
    right one changes nothing and never opens the menu. A seat that cannot open
    it, or cannot find the model in it, keeps the turn and runs on Gemini's
    default — the product is meant to need no configuration, so a preference
    that cannot be applied is a note, not a lost message.
    """
    if not model:
        return ""
    on = current_model(snapshot) if snapshot else ""
    if on and model.lower() in on.lower():
        return ""
    failure = _click_first(browser, MODEL_BUTTON_SELECTORS, "Gemini's mode picker")
    if not failure:
        failure = _click_first(browser, (model,), f"the model menu item {model!r}")
    if failure:
        _dismiss_menu(browser)
        return (
            f"model {model!r} not selected — {failure}. "
            f"Gemini's default{f' ({on})' if on else ''} is in use."
        )
    return ""


def name_conversation(browser, title):
    """Rename the conversation after its correspondent. Best effort.

    The stored URL is what identifies a conversation and Gemini titles a chat
    from its first message on its own, so a failure here costs a tidy sidebar
    and nothing else.
    """
    failure = _click_first(browser, CONVERSATION_MENU_SELECTORS, "the conversation's menu")
    if not failure:
        failure = _click_first(browser, (RENAME_ITEM,), f"the {RENAME_ITEM!r} menu item")
    if not failure:
        for selector in RENAME_INPUT_SELECTORS:
            script = f"fill {shlex.quote(selector)} {shlex.quote(title)}\npress Enter"
            try:
                transcript = browser.run(script)
            except BrowserError as exc:
                failure = f"the rename box ({selector}): {exc}"
                continue
            if transcript.ok:
                return ""
            failure = f"the rename box ({selector}): {transcript.error}"
    _dismiss_menu(browser)
    return f"the conversation could not be named {title!r} — {failure}"
