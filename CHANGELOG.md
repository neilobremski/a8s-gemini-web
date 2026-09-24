# Changelog

## 0.1.0

- **Files in.** `tell gemini --attach report.pdf "what does this say?"` now puts the file into the Gemini conversation. a8s appends attachments to the message body as `ATTACHED FILE: <path>` lines, so the driver takes them back out: the prose is typed and the paths are dropped into the composer. Previously the whole body was typed, which meant a local filesystem path was typed into Google's web interface — useless to the model, and a disclosure of where this machine keeps its mail.
- Confirmation is not "the filename is on the page". The snapshot carries the whole conversation, so a name mentioned in an earlier turn would confirm an upload that had not begun — and a filename can render while the upload is still running and Send is disabled. `attach` requires one *more* occurrence of each name than before the drop, and then the page to read the same twice running. Both hold without knowing what an attachment chip looks like, which matters because the consent dialog blocks observing one.
- Nothing is submitted until the page shows the file. An upload is not instant and the send button is disabled while it runs, so pressing Enter on the way past would ask Gemini about a document it never received. A file that does not appear is a message *not sent*, which a8s may safely hand back — unlike a failure after the keystroke.
- A `--split` file arrives as `.partNNNofMMM` pieces, which a8s does not rejoin. They are joined here. A set with a part missing is refused and named in the reply rather than joined short, because a truncated file presented as the sender's document is worse than no file.
- An attachment a8s could not deliver (`ATTACHMENT UNAVAILABLE:`) is named in the reply. The question still reaches Gemini; the sender is told what it went without, because silence reads as an answer about the file.
- **The first upload on a profile needs a person.** Gemini raises a disclaimer about rights in uploaded content, with `Cancel` and `Agree`, and nothing attaches until it is accepted. The driver detects it, keeps the message, and says exactly what to do. It does not press `Agree`: accepting terms on an account is the same kind of one-time by-hand step as signing the profile in.
- **A long reply travels whole.** An answer past the 4000-character body cap is attached as `gemini-reply.md` instead of being cut. The cap exists so one answer cannot flood a mailbox; a file does not sit in the message text, so it costs the cap nothing.
- A held reply now keeps its attachments, copied into the queue beside it. The files a turn produces are browser-seat artifacts and that directory is swept, so a queue holding a path into it would deliver an answer naming a file nobody has. A file that cannot be copied is dropped and named in the body rather than failing the hold — the answer is worth more than the attachment, and the turn that produced it has already been spent.
- Fixed: the page snapshot was found by taking the first `.txt` among a run's artifacts. Artifacts are attached in script order, so a script that also downloaded a text file would have read the download as the page, and a binary one would have raised `UnicodeDecodeError` past the `OSError` handler as a crash rather than a reply. The `snap` step reports the file it wrote, so the snapshot is now named rather than guessed at.
- `docs/gemini-ui.md` records what was observed on the live page for all of this, including what could *not* be verified and why.

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
- A reply that `tell` will not take — including a `tell` that cannot be launched at all — is held on disk and delivered by the next run, without spending another turn with Gemini. Only one run flushes that queue at a time, and a claim records when it was taken rather than when the reply was written, so two runs cannot deliver one answer twice, and a hand-run `ask` hands held replies to their correspondents rather than printing them to the operator.
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
