# Changelog

## 0.0.1

First working driver: Gemini Web answers tells.

- A tell from an allowed sender is typed into Gemini in an a8s-browser seat that a person signed in by hand, and the reply comes back as a tell. Text only — no images and no uploads.
- One conversation per correspondent, remembered in `$XDG_STATE_HOME/a8s-gemini-web` across restarts. A new conversation opens with an identity preamble saying which agent this is, that a relay carries the messages, and who it is talking to.
- `definitions/gemini-web.json` registers the node; the browser seat, the allowlist and an optional model are per-node a8s vars. An unset allowlist refuses everyone, the same rule a8s-browser uses and for the same reason.
- A turn is finished when the page says so (the rate-it-and-redo-it cluster under the newest reply), with text settling and an overall timeout as backstops. A reply cut short is delivered and marked; a quota refusal from Gemini is reported as one rather than relayed as an answer; a profile that is not signed in is named as that, and nothing here ever signs in.
- One seam to the browser (`src/browser.py`) and one module holding every selector and label (`src/gemini.py`), catalogued with its source in `docs/gemini-ui.md`.
- CI on every pull request: Python lint (ruff, pinned), PII scan of the diff, the test suite, and a VERSION bump gate.
- CI on every merge to main: the same gates plus a PII scan of the whole tracked tree, then a `v<version>` tag and a GitHub release.
- `tools/lint` and `tests/run` run the same gates locally, each in a venv beside the tests, never in the system python.
- PII machinery carried over from a8s-browser: diff checker, whole-tree scanner, pre-push hook, and the pattern-sync script. Patterns come from the `PII_PATTERNS` secret in CI and a gitignored local file on a checkout.
