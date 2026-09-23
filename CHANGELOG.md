# Changelog

## 0.0.1

First working driver: Gemini Web answers tells.

- A tell from an allowed sender is typed into Gemini in an a8s-browser seat that a person signed in by hand, and the reply comes back as a tell. Text only — no images and no uploads.
- One conversation per correspondent, remembered in `$XDG_STATE_HOME/a8s-gemini-web` across restarts. A new conversation opens with an identity preamble saying which agent this is, that a relay carries the messages, and who it is talking to.
- `definitions/gemini-web.json` registers the node; the browser seat, the allowlist and an optional model are per-node a8s vars. An unset allowlist refuses everyone, the same rule a8s-browser uses and for the same reason.
- A turn is finished when the page says so (the rate-it-and-redo-it cluster under the newest reply), with text settling and an overall timeout as backstops. A reply cut short is delivered and marked; a quota refusal from Gemini is reported as one rather than relayed as an answer; a profile that is not signed in is named as that, and nothing here ever signs in.
- A structured answer comes back whole. Only `You said` / `Gemini said` end a turn; a section heading inside a reply is part of the reply, not the end of it.
- A new reply is identified by the page's turn count rather than by its text, so an agent that answers `OK` twice gets two answers instead of one and a timeout.
- The message reaches Gemini exactly as written — indentation intact, and a message that mentions a shell heredoc is sendable. Each line travels as an a8s-browser block instead of a command argument, because a script line is stripped before it is parsed.
- A send that fails on the keystroke that submits is reconciled against the page instead of guessed at, so an ambiguous failure never asks Gemini the same question twice. Seeing the turn appear proves it was sent; not seeing it proves nothing, and is reported as uncertain rather than retried.
- A reply that `tell` will not take — including a `tell` that cannot be launched at all — is held on disk and delivered by the next run, without spending another turn with Gemini. Each held reply is claimed before it is sent, so two runs flushing at once cannot deliver one answer twice, and a hand-run `ask` hands held replies to their correspondents rather than printing them to the operator.
- One turn at a time per seat, and every session-store change is a locked read-modify-write. Two overlapping runs no longer erase each other's conversations or interleave in the same browser window.
- A store that cannot be written answers the sender with what went wrong, and a stored entry whose URL is not text is ignored rather than carried into the browser.
- A slow first paint no longer costs a turn: the prompt box is waited for rather than read once, three seconds after a navigation.
- A seat whose page does not survive between commands is named as that — a8s-browser restarts a Chrome whose window reports itself hidden — instead of reporting a missing prompt box.
- No rename of the conversation. `Show more options` is Gemini's *response actions* menu, not a conversation menu, and the menu it opens swallows the keystrokes that follow — see `docs/gemini-ui.md`.
- One seam to the browser (`src/browser.py`) and one module holding every selector and label (`src/gemini.py`), catalogued with its source in `docs/gemini-ui.md`.
- CI on every pull request: Python lint (ruff, pinned), PII scan of the diff, the test suite, and a VERSION bump gate.
- CI on every merge to main: the same gates plus a PII scan of the whole tracked tree, then a `v<version>` tag and a GitHub release.
- `tools/lint` and `tests/run` run the same gates locally, each in a venv beside the tests, never in the system python.
- PII machinery carried over from a8s-browser: diff checker, whole-tree scanner, pre-push hook, and the pattern-sync script. Patterns come from the `PII_PATTERNS` secret in CI and a gitignored local file on a checkout.
