# a8s-gemini-web

Gemini Web as an agent on the a8s network. A tell arrives, this driver types it
into Gemini in a real signed-in Chrome window, waits for the answer, and sends
that answer back as a tell. Each correspondent gets one conversation of their
own, so the chat has the memory a chat is supposed to have.

There is no API key and no login here. A person signs a browser profile in to
Gemini by hand, once; this driver only types.

## Before it will work

[a8s-browser](https://github.com/neilobremski/a8s-browser) 0.3.0 or later
(for its `upload` and `download` verbs) installed and on `PATH`, with one of its
seats already signed in to Gemini:

```bash
a8s-browser -s gemini-profile open      # a real Chrome window on a fresh profile
# sign in to Google in that window, by hand, once
a8s-browser -s gemini-profile go https://gemini.google.com/app
a8s-browser -s gemini-profile snap      # should show the Gemini page, not a sign-in
```

That seat name is this driver's `A8S_GEMINI_BROWSER_SEAT`. It also needs
[ar3](https://github.com/witw-llc/ar3) — `a8s` and `tell` — running on the same
machine, which is what carries the messages. The same machine is the whole story
for files, too: a path this driver hands the browser is a local path, so the two
are never on different hosts.

**One more by-hand step, if you want to send files.** The first time a profile
attaches anything, Gemini raises a disclaimer about rights in uploaded content,
and nothing attaches until somebody presses `Agree`. Do it once, in the same
window you signed in with:

```bash
a8s-browser -s gemini-profile open      # attach any file with the + button
# press Agree in the dialog that appears
```

Until that is done, a tell carrying a file comes back saying so and the message
stays queued — this driver does not accept terms on an account it drives, for
the same reason it never signs in.

Linux (or WSL). Python standard library only; nothing to build, nothing to pip
install.

## Install

```bash
git clone https://github.com/neilobremski/a8s-gemini-web ~/.a8s-gemini-web
echo 'source ~/.a8s-gemini-web/install.sh' >> ~/.bashrc    # puts it on PATH
```

## Register the node

```bash
mkdir -p ~/agents/gemini
a8s add gemini ~/agents/gemini ~/.a8s-gemini-web/definitions/gemini-web.json \
  --A8S_GEMINI_WEB=$HOME/.a8s-gemini-web/a8s-gemini-web \
  --A8S_GEMINI_BROWSER_SEAT=gemini-profile \
  --A8S_GEMINI_ALLOW=example-sender
a8s start gemini
```

Per-node vars, all set the same way (`a8s vars gemini set <KEY> <value>`):

| Var | |
|---|---|
| `A8S_GEMINI_WEB` | path to this repo's launcher |
| `A8S_GEMINI_BROWSER_SEAT` | the a8s-browser seat holding the signed-in profile |
| `A8S_GEMINI_ALLOW` | comma-separated senders this seat answers. **Unset means nobody** — the seat drives a signed-in account, so nobody is allowed by default. An allowed sender can type into that account *and upload files into it*, so the list is the whole trust boundary |
| `A8S_GEMINI_MODEL` | optional; a model as Gemini's own menu labels it (`Pro`, `Flash`). Unset takes whatever Gemini defaults to, which is the point — the product needs no configuration |
| `A8S_GEMINI_BROWSER_CMD` | optional; the a8s-browser launcher's path, for when a wake's `PATH` does not carry it |

## A turn

```
$ tell gemini "what is the difference between a mutex and a semaphore?"
```

and back comes a tell from `gemini`:

```
A mutex is owned: whoever locks it is the one who unlocks it, and it exists to
protect one resource. A semaphore is a count of permits with no owner, and any
thread may release one.
```

The first message to a new correspondent gets one extra step nobody sees: the
conversation opens with a short preamble telling Gemini which agent it is, that
it is reachable through a relay, and who it is talking to. Every message after
that goes into the same conversation.

When something goes wrong the reply says so in plain words rather than going
quiet — the seat is not signed in, Gemini is rate-limiting it, the reply was cut
short by the timeout. A reply that was cut short is still delivered, marked.

## By hand

```bash
a8s-gemini-web --seat gemini ask --from example-sender "are you there?" \
  --browser-seat gemini-profile --allow example-sender   # prints the reply, sends no tell
a8s-gemini-web --seat gemini sessions                    # who has a conversation, and where
a8s-gemini-web --seat gemini forget example-sender       # the next tell starts a new one
```

Conversations are remembered in `$XDG_STATE_HOME/a8s-gemini-web` (or
`~/.local/share/a8s-gemini-web`), one small JSON file per node.

## What it does

Text in, text out, files in, and generated images out.

```bash
tell gemini --attach report.pdf "what does this say about margins?"
```

a8s delivers the file to this machine and names it in the message; the driver
takes the path back out of the prose, puts the file in through Gemini's own
`Upload files` menu, waits for Gemini to show it, and only then sends. Nothing is submitted until the file
is in the page, because a question about a document Gemini never received reads
as a model failure and costs a turn to discover. A file over `tell`'s size cap
arrives as `--split` parts and is joined back together here; a set with a part
missing is refused and named rather than joined short.

A reply too long for the message cap comes back as `gemini-reply.md` attached,
instead of being cut.

```bash
tell gemini "draw a small red square on a white background"
```

An image Gemini generates comes back as an attachment, with whatever Gemini
wrote beside it — or, for a turn with no words, a line saying how many images
it made. The driver waits until each image in the turn has its own download
control before it counts the turn as finished, downloads each one through
a8s-browser, and names any image that did not come back in the reply.
Documents and code that Gemini builds in Canvas do not come back as files.

This needs an a8s-browser whose `download` reports what its Chrome saved. With
a8s-browser 0.3.0 against a real Chrome, the click works but Chrome saves the
image to its own download folder, the verb does not see it, and the reply says
the image could not be downloaded.

Selecting a model is best effort — it is one of Gemini's Angular menus, and a
seat that cannot switch keeps the turn and runs on the default.

Every selector and label this driver relies on is in `src/gemini.py`, listed
with its source in [`docs/gemini-ui.md`](docs/gemini-ui.md). Google changes the
interface without notice; that file is where the fix goes.

## Tests

```bash
tests/run
```

Builds a venv at `tests/.venv` and runs pytest in it; arguments pass through.
The suite drives a fake browser seat, so it needs neither a browser nor a
network.

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
