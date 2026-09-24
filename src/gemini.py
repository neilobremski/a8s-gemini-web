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
import os
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

# How long the prompt box is given to appear. Gemini is a single-page app: a
# navigation resolves long before the composer exists, and a snapshot taken in
# that window has no textbox in it at all. Failing there would throw away a
# message because a page was slow, which cost a live turn on 2026-09-23.
PROMPT_WAIT_SECONDS = 20.0

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
#
# Neither does a heading, on its own. Gemini writes structured answers, and
# their section headings are the reply — stopping at the first one returns the
# introductory sentence and throws away everything the sender asked for. Only a
# *turn* heading ends a turn, which is the pair below.
STOP_ROLES = ("textbox", "contentinfo", "form", "navigation", "banner")

# The composer, as a selector rather than an accessible name, because `drop`
# addresses an element and the box is a Quill editor. `div[contenteditable=true]`
# on its own matches two elements — Quill keeps a hidden clipboard node — and
# Playwright refuses an ambiguous target, so the editor class is part of it.
COMPOSER_SELECTOR = 'div.ql-editor[contenteditable="true"]'

# Gemini raises a disclaimer the first time a profile attaches anything, and the
# file does not land until a person accepts it. Accepting terms on somebody's
# account is not this driver's to do — it is the same kind of one-time, by-hand
# step as signing the profile in.
CONSENT_HEADING = "Creating content from images and files"

# How long an upload is given to show up in the composer before the send is
# abandoned. Nothing is submitted in that window, so running out is a message
# kept rather than a message sent without its files.
UPLOAD_WAIT_SECONDS = 30.0

# a8s-browser's heredoc marker for the message text. It is this driver's choice
# rather than the page's: any word works, and `_block_marker` lengthens it if a
# line of the message happens to read exactly like it.
BLOCK_MARKER = "A8SGW"

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

# Gemini has no rename control this driver can reach safely. The obvious
# candidate, `button[aria-label^="Show more options"]`, opens the *response
# actions* menu - "Branch in new chat", "Listen", "Export to Docs" - whose first
# item is preselected, so an open menu swallows the next keystrokes and can
# branch the conversation instead of typing into it. Naming is cosmetic anyway:
# the stored URL identifies a conversation, and Gemini titles a chat from its
# first message, which here is the preamble.


# `- role "name" [ref=e1] [level=6]: value` — one node of a snapshot.
NODE = re.compile(
    r'^-\s+(?P<role>[A-Za-z][\w-]*)'
    r'(?:\s+"(?P<name>[^"]*)")?'
    r'(?P<attrs>(?:\s*\[[^\]]*\])*)'
    r'(?:\s*:\s*(?P<value>.*))?$'
)


class GeminiError(Exception):
    """The page did not look the way this module expects."""


class SendUncertain(GeminiError):
    """The send failed at or after the keystroke that submits the message.

    The difference matters more than it looks. A failure *before* Enter means
    the message is definitely not in the conversation and the caller should
    keep it and try again. A failure at Enter, or a seat that stopped answering
    altogether, means nobody here knows — and retrying on that guess asks
    Gemini the same question twice, in the same chat, as though the sender had
    said it twice. The caller reconciles against the page instead of guessing.
    """


class Reading:
    """One look at the conversation.

    `counts` is (user turns, model turns) as the page's own headings report
    them, or None when no heading matched — that is what tells a new reply from
    the one that was already there, without comparing text.
    """

    def __init__(self, text, complete, counts=None):
        self.text = text
        self.complete = complete
        self.counts = counts


class Turn:
    """The outcome of one message: the reply, and whether it finished."""

    def __init__(self, reply, complete, seconds, note="", counts=None):
        self.reply = reply
        self.complete = complete
        self.seconds = seconds
        self.note = note
        self.counts = counts


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


def _block_marker(lines):
    """A heredoc marker no line of the message can be mistaken for."""
    marker = BLOCK_MARKER
    taken = {line.strip() for line in lines}
    while marker in taken:
        marker += "X"
    return marker


def send_script(label, message):
    """The script that types one message and sends it.

    **The message never appears as a command-line argument.** a8s-browser
    strips every script line before it parses it, so text passed inline loses
    its indentation — an indented code example arrives at column zero, which is
    a different program from the one the sender asked about. Worse, any line
    ending in `<<WORD` reads as a block opener and the whole script is refused,
    so a message that merely mentions a heredoc could not be sent at all.

    Each line therefore travels as a `<<MARKER` block, whose content a8s-browser
    takes verbatim: no stripping, no quoting, no comment rules. One block per
    line, because a `type` carrying a newline would press Enter and submit the
    message half-written; the line break is `Shift+Enter`, which Gemini treats
    as a new line inside the prompt.

    The box is emptied first, which also focuses it — a leftover draft in the
    prompt box would otherwise be sent along with the message. Sending is Enter
    straight after, which is b3t's proven move.

    One known difference from byte-for-byte: `splitlines` drops a trailing
    newline, so a message that ends in one arrives without it. Interior blank
    lines, tabs, quotes and indentation all survive.
    """
    if "<<" in label:
        raise GeminiError(
            f"the prompt box's name ({label!r}) contains '<<', which a8s-browser reads "
            "as a block opener. Give this seat a CSS selector for the prompt box instead."
        )
    lines = message.splitlines() or [""]
    marker = _block_marker(lines)
    script = [f"fill {shlex.quote(label)} ''"]
    for index, line in enumerate(lines):
        if index:
            script.append("press Shift+Enter")
        if line:
            script.append(f"type <<{marker}\n{line}\n{marker}")
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


def turn_heading(role, name):
    """Which turn a heading opens: "model", "user", or "" for a content heading.

    The distinction is the whole of R1: a level-2 `Critical findings` inside an
    answer is text, and only `Gemini said` / `You said` divide one turn from
    the next.
    """
    if role != "heading":
        return ""
    if name == MODEL_TURN_HEADING:
        return "model"
    if name.startswith(USER_TURN_HEADING):
        return "user"
    return ""


def turn_counts(snapshot):
    """How many turns each side has taken, or None when no heading matches.

    This is what identifies a turn. Text cannot: an agent relay answers `OK`
    all day, and a second `OK` is a new reply rather than the old one still on
    screen. None means the headings have changed shape and the caller has to
    fall back to comparing text, which is the weaker rule and known to be.
    """
    asked = answered = 0
    for line in snapshot.splitlines():
        role, name, _ = node(line)
        which = turn_heading(role, name)
        if which == "model":
            answered += 1
        elif which == "user":
            asked += 1
    if not asked and not answered:
        return None
    return asked, answered


def _last_model_turn(lines):
    found = -1
    for index, line in enumerate(lines):
        role, name, _ = node(line)
        if turn_heading(role, name) == "model":
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
        if turn_heading(role, name):
            break
        if role in STOP_ROLES:
            break
        if role == "button" and name in COMPLETION_BUTTONS:
            break
        if role == "heading":
            # A section heading inside the answer. It is part of what Gemini
            # wrote, and dropping it would run two sections together.
            text = name or value
        elif role in TEXT_ROLES:
            text = value or name
        else:
            continue
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
    """The snapshot a `snap` step attached, read off disk.

    A `snap` step reports the file it wrote, so the snapshot is named rather
    than guessed at. Taking the first `.txt` out of the run's artifacts is what
    this used to do, and it stops being right the moment a script also
    downloads something: artifacts are attached in script order, so a
    downloaded `.txt` attached before the snap would be read as the page. The
    artifact list is still the fallback, because a step that *fails* has a
    snapshot attached to it without a `snap` command to report one.

    The newest is the one that counts — a script may look twice.
    """
    named = [path for path in transcript.outputs("snap") if path.strip()]
    paths = named or transcript.files
    if not paths:
        raise GeminiError(
            f"a8s-browser attached no snapshot for seat {browser.seat!r}, so the page "
            "cannot be read"
        )
    path = paths[-1]
    try:
        # `errors="replace"` because the fallback can land on a binary artifact,
        # and a UnicodeDecodeError here would escape as a crash rather than as
        # a reply telling the sender what went wrong.
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError as exc:
        raise GeminiError(f"the page snapshot at {path} could not be read: {exc}") from exc


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


BLANK_PAGE = "about:blank"


def _no_prompt(browser, snapshot):
    """Why the composer is missing, with the likely cause named.

    A blank page after a navigation that reported the app's own URL means the
    page did not survive between two commands, and the way that happens is
    a8s-browser cycling Chrome: it restarts a browser whose `visibilityState`
    is "hidden", which a window behind other windows reports on macOS. Every
    command then gets a fresh `about:blank`, and no driver can work across
    calls. Saying so beats another sentence about selectors.
    """
    seat = browser.seat or "<seat>"
    if not snapshot.strip() or BLANK_PAGE in snapshot:
        return (
            f"the seat landed on {BLANK_PAGE} straight after opening Gemini, so the page "
            "is not surviving between commands. a8s-browser restarts a Chrome whose "
            "window reports itself hidden, which is what an occluded or minimised "
            f"window does. Bring seat {seat!r}'s Chrome window to the front and try again."
        )
    return (
        f"no textbox in the page snapshot after {PROMPT_WAIT_SECONDS:.0f}s — Gemini's "
        f"prompt box never appeared (it is normally named {PROMPT_FALLBACK_LABEL!r}). "
        f"`a8s-browser -s {seat} snap` shows the page now."
    )


# How long the page is watched for the turn an uncertain send may have made.
# It confirms a send; its expiry never disproves one.
SUBMIT_CONFIRM_SECONDS = 20.0


def await_turn_taken(browser, before, now=None, sleep=None):
    """Whether a turn from this side appears on the page within the window.

    True is proof the message went in. **False is not proof that it did not.**
    A page renders when it renders, and a snapshot taken a moment too early
    shows the previous state — which is exactly the reading that, treated as
    proof, made the driver ask Gemini the same question twice.
    """
    now, sleep = now or _now, sleep or _sleep
    deadline = now() + SUBMIT_CONFIRM_SECONDS
    while True:
        try:
            after = read(browser)
        except (GeminiError, BrowserError):
            return False
        if before and after.counts and after.counts[0] > before[0]:
            return True
        if now() >= deadline:
            return False
        sleep(POLL_SECONDS)


def await_prompt(browser, now=None, sleep=None):
    """The prompt box's label and the snapshot it was read from, waited for.

    Returns as soon as the composer exists. If it never does, this raises the
    same sentence `prompt_label` would, naming the seat to snapshot by hand.
    """
    now, sleep = now or _now, sleep or _sleep
    deadline = now() + PROMPT_WAIT_SECONDS
    while True:
        snapshot = page_snapshot(browser)
        label = textbox_label(snapshot)
        if label:
            return label, snapshot
        if now() >= deadline:
            raise GeminiError(_no_prompt(browser, snapshot))
        sleep(POLL_SECONDS)


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
    return Reading(
        extract_reply(snapshot, history, sent),
        turn_complete(snapshot),
        turn_counts(snapshot),
    )


def is_new(reading, baseline="", baseline_counts=None):
    """Whether this reading shows a reply that was not there before the send.

    Counting the page's turn headings is the strong answer, and it is right
    even when the new reply reads exactly like the old one — `OK` after `OK` is
    two turns, not one. Comparing text is the fallback for a page whose
    headings changed shape, and it is wrong in precisely that case, which is
    why it is second.
    """
    if reading.counts and baseline_counts:
        return reading.counts[1] > baseline_counts[1]
    return bool(reading.text) and reading.text != baseline


def await_reply(browser, sent, baseline="", baseline_counts=None, now=None, sleep=None):
    """Wait for the turn Gemini is writing to finish, and return it.

    Finished means the page says so, or — if those labels have changed — that
    the text has not moved for SETTLE_SECONDS. What counts as *this* turn's
    reply is `is_new`: the page's turn count moved, or, failing that, the text
    is no longer the `baseline` that was on screen before the message went in.
    """
    now, sleep = now or _now, sleep or _sleep
    started = now()
    last = ""
    counts = baseline_counts
    stable_since = None
    while True:
        reading = read(browser, sent)
        counts = reading.counts or counts
        text = reading.text if is_new(reading, baseline, baseline_counts) else ""
        if text and text == last:
            if stable_since is None:
                stable_since = now()
        else:
            stable_since = None
            last = text
        if text and reading.complete:
            return Turn(text, True, now() - started, counts=counts)
        if text and stable_since is not None and now() - stable_since >= SETTLE_SECONDS:
            return Turn(
                text,
                True,
                now() - started,
                "the page never marked this turn finished; it is being reported because "
                "the text stopped changing.",
                counts=counts,
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
            return Turn(last, False, elapsed, note, counts=counts)
        sleep(POLL_SECONDS)


SUBMIT_STEP = "press Enter"


def _failed_step(transcript):
    for step in transcript.steps:
        if not step.get("ok"):
            return step
    return None


def consent_pending(snapshot):
    """Whether Gemini is holding a file behind its first-upload disclaimer."""
    return CONSENT_HEADING.lower() in (snapshot or "").lower()


def _consent_error(browser, names):
    return GeminiError(
        f"Gemini is asking this profile to accept its disclaimer about uploaded files "
        f"before it will take one, so {', '.join(names)} was not sent and neither was "
        f"your message. Someone has to accept it by hand, once: open the seat "
        f"(`a8s-browser -s {browser.seat} open`), attach any file to a chat, and press "
        f"Agree in the dialog that appears. This driver does not accept terms on an "
        f"account it drives."
    )


def attach(browser, paths, wait=UPLOAD_WAIT_SECONDS, now=None, sleep=None):
    """Put files into the composer and wait until the page shows them.

    Nothing here submits anything, so every failure is a message that was not
    sent — which is the one case this driver can safely let a8s retry.

    The wait is on the file's own name appearing in the page. An upload is not
    instant and the send button is disabled while it runs, so pressing Enter on
    the way past would submit the prompt without the file it is about. Giving up
    rather than sending anyway is the same choice: a question about a document
    nobody attached reads as a model failure, and it costs a turn to discover.
    """
    now, sleep = now or _now, sleep or _sleep
    names = [os.path.basename(path) for path in paths]
    script = "drop " + " ".join(shlex.quote(part) for part in [COMPOSER_SELECTOR, *paths])
    _run(browser, script, f"putting {', '.join(names)} into the conversation")

    deadline = now() + wait
    snapshot = ""
    while True:
        snapshot = _snapshot_of(_run(browser, "snap", "reading the composer"), browser)
        if consent_pending(snapshot):
            raise _consent_error(browser, names)
        if all(name in snapshot for name in names):
            return names
        if now() >= deadline:
            break
        sleep(POLL_SECONDS)
    raise GeminiError(
        f"{', '.join(names)} did not appear in Gemini's composer within "
        f"{wait:.0f}s, so your message was not sent — a question about a file "
        "Gemini never received is worse than one you can send again."
    )


def send(browser, label, message):
    """Type the message and submit it, or say which of those is not known.

    a8s-browser stops a script at its first failed step and reports which one,
    and the submitting keystroke is the last step. So a named failure on any
    earlier step is proof the message was never submitted, while a failure on
    the keystroke itself — or a seat that returned no transcript at all — is
    genuinely unknown and is raised as `SendUncertain`.
    """
    script = send_script(label, message)
    try:
        transcript = browser.run(script)
    except BrowserError as exc:
        raise SendUncertain(
            f"typing the message into Gemini: {exc}. The seat never answered, so "
            "whether the message was submitted cannot be told from here."
        ) from exc
    if transcript.ok:
        return
    failed = _failed_step(transcript) or {}
    if str(failed.get("command") or "").strip() == SUBMIT_STEP:
        raise SendUncertain(
            f"typing the message into Gemini: {transcript.error}. That failure is on "
            "the keystroke that sends, so whether Gemini received the message cannot "
            "be told from here."
        )
    raise GeminiError(f"typing the message into Gemini: {transcript.error}")


def send_turn(browser, label, message, baseline="", baseline_counts=None, now=None, sleep=None):
    send(browser, label, message)
    return await_reply(browser, message, baseline, baseline_counts, now=now, sleep=sleep)


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
