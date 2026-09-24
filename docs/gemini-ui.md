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
| `BLOCK_ROLES` / `INLINE_ROLES` / `CELL_SEPARATOR` | a paragraph, list item, blockquote, heading and code block is a line of the reply, and so is a table `row`, its `columnheader` or `cell` names joined by ` \| ` (the header row is its own line); a `text`, inline `code`, `link` or `superscript` child is a run inside its paragraph's line. Bold and italic are not nodes at all: the snapshot merges them into the surrounding `text`. A citation is an empty `superscript` between two `text` runs, then a single-quoted `button` for the source chip. Every run is trimmed, so the space between two runs comes from the rendered text, and only when that cannot tell is it guessed | observed 2026-09-24 |
| `CODE_BLOCK_BUTTON` / `_code_block` | a code block is a `code` node beside a header holding the language (`generic: Python`) and `Download code` / `Copy code`. The snapshot collapses its newlines and indentation — a three-line JSON block arrives as one `code` value — so its text is taken from the rendered text, where the block keeps its lines. Inside a list item, the `Copy code` button is what tells the block's wrapper from an inline span | observed 2026-09-24 |
| `HISTORY_SELECTOR` | `main`, read with `text` as the fallback when the headings stop matching. a8s-browser 0.3.1 returns it decoded, so it is used as it arrives; decoding it again would turn a literal backslash-n on the page into a line break | reading |
| `node` / `_unquote` | a snapshot is YAML: a value that starts with a quote or holds a colon arrives as a quoted scalar. A cited answer splits its paragraph into `text` children around `superscript` markers, one of them `- text: ", HERON-3"`; the quotes are syntax and are removed | observed 2026-09-24 |
| `TRAILING_NOISE` | the page's own `Gemini is AI and can make mistakes.` line | observed 2026-09-23 |
| `conversation_id` | a new chat is `/app` with no id; after the first message the URL becomes `/app/<hex id>`, and returning is a plain `go` to it | observed 2026-09-23 |
| `MODEL_TURN_HEADING` / `USER_TURN_HEADING` as *turn* headings | only these two end a turn; a `Critical findings` heading inside an answer is the answer | observed 2026-09-23 |
| `MODE_PICKER_PREFIX` | the model switcher is named `Open mode picker, currently <Model>`, so the current model is readable without opening anything | observed 2026-09-23 |
| `MODEL_BUTTON_SELECTORS` | CSS for that switcher, `button[aria-label^="Open mode picker"]` first | derived from the observed name, **click untested** |
| `RATE_LIMIT_PHRASES` | Gemini's own quota refusal, matched near the front of a short reply | reading, **untested** |
| `TROUBLE_PHRASES` | `couldn't generate`, `something went wrong` | b3t |
| `CONSENT_HEADING` | `Creating content from images and files` — the dialog Gemini raises the first time a profile attaches anything, with `Cancel` and `Agree`. Until a person presses Agree, no file lands | observed 2026-09-23 |
| `UPLOAD_MENU_SELECTOR` / `UPLOAD_MENU_ITEM` | uploading: `click 'button[aria-label="Upload & tools"]'` opens a `menu "Menu options"`; `click "Upload files"` picks its `menuitem "Upload files. Documents, data, code files"`, which opens a file chooser; `upload <abs path>` answers it. One file per chooser, before the submitting keystroke | observed 2026-09-24 |
| `IMAGE_CHIP_NAME` | an uploaded **image** (a `.jpeg`, and a `.png` in a second upload) shows in the composer as a thumbnail, `img "attachment"`, a sibling of the prompt box, with **no filename anywhere**. Only the composer is read for it — the conversation carries pictures too | observed 2026-09-24 |
| `_composer` | the composer is the `group` that holds the prompt box; chips, the prompt box and `Send message` sit inside it, the conversation outside it | observed 2026-09-24 |
| `chip_label` | the attachment chip for a document: a `generic [cursor=pointer]` above the prompt box holding `generic: TXT` (the extension, in capitals) and `generic: probe-note` (the name **without** its extension). No `Remove` button and no progress node showed for a small text file | observed 2026-09-24 |
| `SEND_BUTTON_NAME` | `Send message` — a button in the composer, with an `img: arrow_upward`. **It does not exist while the prompt box is empty**, and appears once there is text. A snapshot marks a disabled node with a trailing `[disabled]`, so this is the page's own answer to "will you send this now" | observed 2026-09-23 |
| `IMAGE_DOWNLOAD_NAME` | a generated image inside a model turn is an unnamed `button` wrapping an `img` with no value — unnamed on one page, named `", AI generated"` on another — followed by that image's own `button "Share image"`, `button "Copy image"` and `button "Download full size image"`. One download button per image | observed 2026-09-24 |
| `IMAGE_CONTROL_NAMES` | the image turn's rating cluster is `Good response`, `Bad response`, `Redo` (newest turn only), `Share image`, `Show more options` — **no `Copy`**, which a text turn's cluster has | observed 2026-09-24 |
| `image_readiness` | an image turn is finished only when every image drawn in it has its download button. In the one generation watched, the image and its download button were on the page ten seconds before the rating cluster; the opposite order was not seen, and is still taken to be possible | observed 2026-09-24, once |
| `NEWEST_EXCHANGE_SELECTOR` / `image_download_selector` | the download button as an element: `button[aria-label="Download full size image"]`, inside `div.conversation-container` (one per exchange) and `div.generated-images`. The newest exchange is the container with no container after it | observed 2026-09-24 |

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
a8s-browser's own parser when a checkout of it is reachable — point
`A8S_BROWSER_SRC` at its `src/`. This is not byte-for-byte: a trailing newline
is dropped by `splitlines`. Indentation, tabs, quotes and interior blank lines
survive.

**A page that does not survive between commands.** With a8s-browser 0.3.1 or
later a covered or minimised window keeps its page. A turn that lands on
`about:blank` straight after opening Gemini therefore means a8s-browser
restarted Chrome and could not return to the page — its own error names the URL
it lost — or somebody closed the seat's window by hand. The driver names both
rather than blaming the selectors. Landing on `about:blank` says nothing about
whether a stored conversation still exists in Gemini, so a conversation that
does not open is reported as one that could not be opened, never as deleted:
what Gemini shows for a conversation that really was deleted has not been
observed.

**Rate-limit wording.** Gemini's quota refusal has not been captured, so the
phrases are a reading. They match only near the front of a short reply, because
a long answer that explains rate limiting is an answer and withholding it would
be the worse mistake. If a refusal gets relayed as an answer, add its wording
to `RATE_LIMIT_PHRASES`.

## Files

**A file goes in through Gemini's own menu.** `click 'button[aria-label="Upload
& tools"]'` opens the menu, `click "Upload files"` opens a file chooser, and
`upload <abs path>` answers it. A chooser takes one file and closes, so the menu
is opened once per file. The button is clicked by CSS selector, which a8s-browser
turns into a real Playwright click, and this Angular menu answers that; b3t
records that a click by accessibility *ref* does not open it. The menu closes
when its item is clicked. If any step fails, the page is read for the consent
dialog first and then `Escape` is pressed, because an open menu swallows the
keystrokes that follow it.

**A synthetic drop attaches nothing.** `drop 'div.ql-editor[contenteditable="true"]'
--path <abs>` and `drop div.xap-uploader-dropzone --path <abs>` — the editor, and
the container Gemini itself marks as its dropzone — both ran without error on the
live page and attached nothing: no chip, no filename, no progress node, with
`Send message` enabled beside the typed text. Why Gemini does not act on the
events is not established. The menu is the mechanism because it is the one that
lands.

**There is no `input[type=file]` on the page at rest.** A DOM query for one
returns zero, so `setInputFiles` against a selector is not available; Gemini
creates the input when its own upload flow runs.

**The first upload on a profile needs a person.** Gemini raises a modal —
heading `Creating content from images and files`, buttons `Cancel` and `Agree` —
and the file does not attach until it is accepted. It is a disclaimer about
rights in uploaded content. This driver detects it and says so; it does not
press Agree. Accepting terms on an account is the same kind of one-time, by-hand
step as signing the profile in, and it belongs to whoever owns the account.

**What a chip looks like depends on the file.** Chips sit in the composer — the
`group` that holds the prompt box — and nothing outside that group is counted.
A document's chip is a clickable `generic` holding `generic: TXT` and `generic:
probe-note` for `probe-note.txt`: the name without its extension, and a long name
shortened to its first and last ten characters around `...`. An image's chip is
a thumbnail, `img "attachment"`, with no name at all.

Only chip nodes are evidence: a document chip is the value of a `generic` node
that reads exactly the file's `chip_label`, and a thumbnail is an `img
"attachment"` node. The thumbnail's own name, the prompt the sender typed and the
snapshot's syntax are never matched against a filename — so `attachment.pdf` is
not confirmed by a picture, and a short name is not confirmed by text that
happens to contain it. Each new chip is then given to **one** file at most: a
document takes a new chip with its label, each `.png`/`.jpg`/`.jpeg`/`.webp`/`.gif`
takes a new thumbnail, and a type nobody has watched land (`.svg`, `.heic` and
the like) takes whichever is left — a chip with its own label first, then a
thumbnail. Two files whose labels read the same need two chips, and one
thumbnail never stands for two files.

**The upload confirmation asks the composer, not only the chip.** The snapshot is
the whole page, so three readings are wrong and one is right.

*Wrong:* "is the name there?" — answered yes by a conversation that mentioned
the file an hour ago, before this upload started.

*Wrong:* "has the name just appeared?" — a chip can render while the upload is
still running.

*Wrong:* "has the page stopped changing?" — a pending upload is **static**. A
paused progress bar and a disabled button read identically from one poll to the
next, so a settle proves only that nothing moved.

*Right:* ask the control whose whole job is to answer it. `Send message` is
disabled while the upload runs and enabled when it is done. That is positive
evidence about the current composer rather than the absence of a marker.

So `attach` requires **the composer's chips to rise over a baseline taken before
the upload** — which stops anything already there confirming it, while still
letting the same file be sent twice — **and** `send_ready(snapshot) is True`. A
page with no composer group has no chips to count, and that is the same answer
as a missing send control: unknown, never ready.

`send_ready` has three answers, and the third is the point. `True` ready, `False`
not yet, and **`None` for no evidence either way**, which is never treated as
ready. If the control is gone from the page, this driver can no longer tell a
finished upload from a running one, so the message is kept and the reply names
the prerequisite instead of guessing.

**This is why the text is typed before the files go in.** The send control does
not render on an empty composer, so an upload that happened first would leave
nothing to read.

**A generated image comes back through its own download control.** An image in
a model turn is an unnamed `button` wrapping an `img`; an icon is an
`img` too, but it carries its glyph name as a value (`img: download`), so an
`img` with no value is a picture, whatever its name — unnamed on one page and
`", AI generated"` on another. Each picture is followed by its own
`Share image`, `Copy image` and `Download full size image` buttons.

In the one generation watched live, the picture and its download button were on
the page before the rating cluster, and the cluster followed ten seconds later.

`image_readiness` answers three ways, like `send_ready`. `True`: every picture
drawn in the newest turn has its download button. `False`: the turn shows a
picture or an image control, and a download button is still missing. `None`: no
image evidence at all, and the turn is judged as text. An image turn is finished
only on `True` and the rating cluster; a turn whose image is pending never
settles. Whether the cluster can appear before an image finishes rendering could
not be seen on a page that had already finished, so this driver assumes it can.

The turn's text comes from its own model turn, even when that is empty. The
rendered-text fallback is for a page whose turn headings no longer match, and
reading it for an image-only turn returns the page's furniture — `Gemini said`,
the mode picker's `Flash` — as though Gemini had written it.

**Downloading.** `download <selector> 60` per image, where the selector is the
download button inside the newest `div.conversation-container` (the one with
no container after it) and `div.generated-images`, taking the Nth child that
holds a download button. a8s-browser acts on the first visible match of a CSS
selector, and older exchanges keep their download buttons, which is why the
selector is scoped to the newest exchange. a8s-browser copies the file into its
own artifacts, whose path the next download may reuse, so this driver copies
each image into the turn's own directory **before asking for the next one**, and
checks that the copy has the bytes the download produced. A picture that comes
back byte-identical to one already kept is reported as a failure, because it
means the selector no longer tells the images apart.

**The download needs a8s-browser 0.3.1.** The seat's Chrome is a real Chrome
attached over CDP, and it saves a download into its own download folder unless
told otherwise, where a8s-browser 0.3.0's `download` does not see it and times out.
0.3.1 points the seat's downloads at the seat's own directory, waits for the
finished file and reports its path. Live on 2026-09-24 with 0.3.1: a generated
2048x2048 JPEG came back through the verb, was copied into the turn's directory
byte for byte, and was attached; nothing landed in the user's own download
folder. This driver never watches a shared download folder itself.

Not covered: documents and code Gemini builds in Canvas, and anything reached
through `Export to Docs`. Those use other controls, and the response-actions
menu that holds them is one this driver does not open.

Do not port b3t's download recipe as written. Its `mousewheel 2000 0` scrolls
**horizontally**, because the signature is `mousewheel <dx> <dy>` — that step has
never scrolled a page down. a8s-browser's own `scroll <dy>` is correct.

## When a turn goes wrong

Every failure names the thing that did not match. `no textbox in the page
snapshot` means the prompt box moved; `no reply appeared within …` means either
the message never reached the box or the turn headings changed. Take a snapshot
and compare it against the table.

`b3t` (`apps/b3t/gemini.py` in `neilobremski/bin`) drives the same pages for a
different purpose. When a row here goes stale, that tool needs the same fix.
