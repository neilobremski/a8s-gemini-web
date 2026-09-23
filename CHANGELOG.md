# Changelog

## 0.0.1

Repository scaffold. No application code yet.

- CI on every pull request: Python lint (ruff, pinned), PII scan of the diff, the test suite, and a VERSION bump gate.
- CI on every merge to main: the same gates plus a PII scan of the whole tracked tree, then a `v<version>` tag and a GitHub release.
- `tools/lint` and `tests/run` run the same gates locally, each in a venv beside the tests, never in the system python.
- PII machinery carried over from a8s-browser: diff checker, whole-tree scanner, pre-push hook, and the pattern-sync script. Patterns come from the `PII_PATTERNS` secret in CI and a gitignored local file on a checkout.
