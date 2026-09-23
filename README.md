# a8s-gemini-web
A8S Gemini Web Integration

Requires [a8s-browser](https://github.com/neilobremski/a8s-browser) installed
and on `PATH`.

## Development

Every merge to `main` bumps `VERSION` and publishes a `v<version>` tag, so work
happens on a branch named for the target version and lands through a pull
request.

Run the same gates CI runs, before you push:

```bash
tools/lint                 # ruff, pinned to the version CI uses
tests/run                  # pytest, in a venv beside the tests
python3 tools/pii-scan.py  # PII across the whole tracked tree
```

PII patterns live in the `PII_PATTERNS` repository secret for CI, and in a
gitignored `.github/pii-patterns.local.txt` on a checkout. Copy
`.github/pii-patterns.example.txt` to that name, then `./install-hooks.sh` to
get the pre-push check, and `.github/sync-pii-patterns.sh` to push the same
list to the repository secret.
