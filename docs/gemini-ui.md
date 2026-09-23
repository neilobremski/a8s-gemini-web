# What this driver believes about Gemini's web interface

Everything listed here lives in `src/gemini.py`, and that module is the only
place in the program that knows any of it. When Google changes the interface
this page tells you what to look for and the module tells you where to change
it. That is maintenance, not a defect.

Re-derive any of it with a snapshot of the live page:

```bash
a8s-browser -s <seat> open          # the signed-in profile, in a real window
a8s-browser -s <seat> go https://gemini.google.com/app
a8s-browser -s <seat> snap          # the accessibility tree, as text
```

A snapshot line reads `- role "name" [ref=e12]` or `- paragraph: some text`,
which is the shape `src/gemini.py` parses. Search it for the name in the table
below, and put whatever it says now into the constant beside it.

## The table

| Constant in `gemini.py` | What it is | Source |
|---|---|---|
| `APP_URL` | `https://gemini.google.com/app` | b3t |
| `SIGN_IN_HOST` | `accounts.google.com` in the URL after navigating means the profile is signed out | b3t |
| `PROMPT_HINTS` / `PROMPT_FALLBACK_LABEL` | the prompt box is the snapshot's `textbox`, preferring a name mentioning prompt, gemini or ask; live it is named `Enter a prompt for Gemini` | b3t, name observed 2026-09-23 |
| — (sending) | `fill "<that name>" <text>` then `press Enter` | observed 2026-09-23 |
| `MODEL_TURN_HEADING` | `Gemini said`, a level-6 heading opening each model turn | observed 2026-09-23 |
| `USER_TURN_HEADING` | `You said <prompt>`, a level-5 heading opening each human turn | observed 2026-09-23 |
| `COMPLETION_BUTTONS` | `Good response`, `Bad response`, `Redo`, `Show more options` — the cluster a finished turn grows, and this driver's completion signal | observed 2026-09-23 |
| `TEXT_ROLES` / `STOP_ROLES` | which snapshot roles carry reply text, and what ends a turn | reading of the snapshot format |
| `HISTORY_SELECTOR` | `main`, read with `text` as the fallback when the headings stop matching | reading |
| `TRAILING_NOISE` | the page's own `Gemini is AI and can make mistakes.` line | observed 2026-09-23 |
| `conversation_id` | a new chat is `/app` with no id; after the first message the URL becomes `/app/<hex id>`, and returning is a plain `go` to it | observed 2026-09-23 |
| `MODEL_TURN_HEADING` / `USER_TURN_HEADING` as *turn* headings | only these two end a turn; a `Critical findings` heading inside an answer is the answer | observed 2026-09-23 |
| `MODE_PICKER_PREFIX` | the model switcher is named `Open mode picker, currently <Model>`, so the current model is readable without opening anything | observed 2026-09-23 |
| `MODEL_BUTTON_SELECTORS` | CSS for that switcher, `button[aria-label^="Open mode picker"]` first | derived from the observed name, **click untested** |
| `RATE_LIMIT_PHRASES` | Gemini's own quota refusal, matched near the front of a short reply | reading, **untested** |
| `TROUBLE_PHRASES` | `couldn't generate`, `something went wrong` | b3t |

The date is when someone looked. The interface changes without notice, so
treat every row as a reading rather than a constant.

## What is not verified, and what to do about it

**Model selection.** Reading the current model needs no click and is safe.
Changing it means opening the mode picker, which is one of Gemini's Angular
menus, and b3t records that accessibility-*ref* clicks do not work on those.
a8s-browser's `click` resolves a CSS selector to a real Playwright click, which
is the mechanism that did work in b3t — but nobody has tried it on this menu.
In order:

1. the CSS-selector click this driver already does (`MODEL_BUTTON_SELECTORS`);
2. a8s-browser's `run-code` verb, which runs a Playwright statement body with
   `page` in scope — the seat must opt in with
   `a8s vars <browser seat> set A8S_BROWSER_ALLOW_EVAL 1`;
3. if neither works, the fix belongs in a8s-browser rather than here.

Selecting a model is non-fatal by design: a seat that cannot switch keeps the
turn and runs on Gemini's default, and the reply carries a note saying so. The
text round trip needs no `eval` and no `run-code`, so **a seat that never
configures a model needs no extra permission at all**.

**Naming the conversation — removed, and do not put it back.** The driver used
to try a rename through `button[aria-label^="Show more options"]`. That button
is not a conversation menu: it opens the *response actions* menu for the newest
reply — `Branch in new chat`, `Listen`, `Export to Docs`, `Draft in Gmail`,
`Report legal issue`, `See response details` — and `Branch in new chat` is
preselected. An open menu swallows the keystrokes that follow, so the next
message went into the menu instead of the prompt box and the turn timed out
with nothing sent (observed 2026-09-23). A cosmetic feature that can eat a
whole turn is not worth having: the stored URL identifies a conversation, and
Gemini titles a chat from its first message anyway — which here is the identity
preamble, so the title is already about the correspondent.

Note the same name appears twice on the page. `Show more options` in
`COMPLETION_BUTTONS` is read from a snapshot as evidence a turn finished; it is
never clicked.

**How the message reaches the prompt box.** Not as a command argument.
a8s-browser strips every script line before it parses it, so an indented code
example arrives at column zero — a different program from the one the sender
asked about — and any line ending in `<<WORD` is read as a block opener, which
refuses the whole script. Each line of the message therefore travels as a
`<<MARKER` block, whose content a8s-browser takes verbatim, one block per line
because a `type` carrying a newline would press Enter and send the message
half-written. `tests/test_browser_parser.py` checks that rule against
a8s-browser's own parser when a checkout of it is reachable.

**The seat's Chrome window has to be on screen.** a8s-browser restarts a Chrome
whose `visibilityState` reads `hidden`, which on macOS is what a window behind
other windows reports. Every command then gets a fresh `about:blank` and no
page survives from one command to the next, so a turn fails with a composer
that never appears. The driver names this case rather than blaming the
selectors. Keep the seat's window visible — its own desktop or space is ideal.

**Rate-limit wording.** Gemini's quota refusal has not been captured, so the
phrases are a reading. They match only near the front of a short reply, because
a long answer that explains rate limiting is an answer and withholding it would
be the worse mistake. If a refusal gets relayed as an answer, add its wording
to `RATE_LIMIT_PHRASES`.

**Out of scope for v1.** Images, file uploads and anything behind the
`Upload & tools` menu. b3t drives that menu through Playwright locators in
`run-code`, which is a different mechanism from the one this driver uses.

## When a turn goes wrong

Every failure names the thing that did not match. `no textbox in the page
snapshot` means the prompt box moved; `no reply appeared within …` means either
the message never reached the box or the turn headings changed. Take a snapshot
and compare it against the table.

`b3t` (`apps/b3t/gemini.py` in `neilobremski/bin`) drives the same pages for a
different purpose. When a row here goes stale, that tool needs the same fix.
