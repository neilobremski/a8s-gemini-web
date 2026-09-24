"""The two file seams: what a8s hands this seat, and what this seat hands back.

a8s does not pass attachments as structured data. It appends them to the message
body as lines, so the driver's first job on every wake is to take them back out
again — and that is not cosmetic. The prose and the paths go to different places:
the prose is typed into Gemini, and the paths are dropped into the composer. A
local filesystem path typed into a page is useless to the model and discloses
where this machine keeps its mail.

Going the other way, a file this seat produces has to be named before it can be
sent, and the name may have come from a web page. So every name is reduced to a
single safe path segment here rather than wherever it happens to be used.
"""
import os
import re
import shutil

# The two lines a8s appends to `$MESSAGE`, one per attachment.
ATTACHED_PREFIX = "ATTACHED FILE: "
UNAVAILABLE_PREFIX = "ATTACHMENT UNAVAILABLE: "

# `<name>.partNNNofMMM` — what `tell --split` makes of a file over the size cap.
# a8s does not put them back together; the receiver owns that.
PART = re.compile(r"^(?P<name>.+)\.part(?P<index>\d+)of(?P<total>\d+)$")

FALLBACK_NAME = "attachment"


class Incoming:
    """One wake's message, with its attachments taken out of the body.

    `prose` is what Gemini should be asked. `paths` are files to put into the
    conversation. `notes` are sentences for the reply, each naming a file the
    sender believes they sent and this seat will not be uploading.
    """

    def __init__(self, prose, paths, notes):
        self.prose = prose
        self.paths = paths
        self.notes = notes


def _classify(message):
    """The body's lines split into prose, attachment paths and lost filenames."""
    prose = []
    paths = []
    lost = []
    for line in (message or "").splitlines():
        stripped = line.strip()
        if stripped.startswith(ATTACHED_PREFIX):
            path = stripped[len(ATTACHED_PREFIX):].strip()
            if path:
                paths.append(path)
        elif stripped.startswith(UNAVAILABLE_PREFIX):
            detail = stripped[len(UNAVAILABLE_PREFIX):].strip()
            if detail:
                lost.append(detail)
        else:
            prose.append(line)
    return "\n".join(prose).strip(), paths, lost


def _group_parts(paths):
    """Split paths into whole files and `.partNNNofMMM` sets, keyed by name.

    A set is keyed by the original name and the total, because two different
    files could in principle split into the same number of parts.
    """
    whole = []
    sets = {}
    for path in paths:
        match = PART.match(os.path.basename(path))
        if not match:
            whole.append(path)
            continue
        key = (match.group("name"), int(match.group("total")))
        sets.setdefault(key, {})[int(match.group("index"))] = path
    return whole, sets


def _join(name, total, found, work_dir):
    """Concatenate a complete part set into one file. None when it is short.

    A part can fail its own download while its siblings arrive, so an
    incomplete set is a real state and not a bug here. Joining what did arrive
    would hand Gemini a truncated file and call it the sender's document, which
    is worse than saying nothing arrived.
    """
    missing = [index for index in range(1, total + 1) if index not in found]
    if missing:
        return None, (
            f"{name} arrived in {total} parts and {len(missing)} of them did not "
            f"(missing {', '.join(str(index) for index in missing)}), so it was not "
            "uploaded. Send it again, or send it smaller."
        )
    os.makedirs(work_dir, exist_ok=True)
    joined = os.path.join(work_dir, safe_name(name))
    with open(joined, "wb") as out:
        for index in range(1, total + 1):
            with open(found[index], "rb") as part:
                shutil.copyfileobj(part, out)
    return joined, ""


def read(message, work_dir):
    """One wake's message as an `Incoming`.

    `work_dir` holds files this function has to build — today only a rejoined
    split set. Nothing else is copied: an attachment a8s delivered is already on
    local disk and the browser reads it from where it is.
    """
    prose, paths, lost = _classify(message)
    notes = [
        f"{detail} — this seat never received that file, so it is not in the conversation."
        for detail in lost
    ]
    whole, sets = _group_parts(paths)
    for (name, total), found in sets.items():
        joined, note = _join(name, total, found, work_dir)
        if joined:
            whole.append(joined)
        if note:
            notes.append(note)
    return Incoming(prose, whole, notes)


# a8s-browser names an artifact `<YYYYMMDDTHHMMSS>-<name>`. The stamp is its
# bookkeeping, not part of the file the page handed over.
ARTIFACT_STAMP = re.compile(r"^\d{8}T\d{6}-")


def adopt(sources, directory, taken=()):
    """Copy files this seat is about to send into a directory it owns.

    Returns `(paths, notes)`. Each name is reduced by `safe_name`, because it
    came from a web page and will land on the sender's disk, and made unique
    within the directory and against `taken` — two images Gemini names alike
    must arrive as two files. A file that cannot be copied is named in a note
    rather than dropped.
    """
    used = {name.lower() for name in taken}
    paths = []
    notes = []
    for index, source in enumerate(sources, 1):
        name = safe_name(ARTIFACT_STAMP.sub("", os.path.basename(source)), f"image-{index}")
        stem, ext = os.path.splitext(name)
        candidate, bump = name, 1
        while candidate.lower() in used:
            bump += 1
            candidate = f"{stem}-{bump}{ext}"
        try:
            os.makedirs(directory, exist_ok=True)
            target = os.path.join(directory, candidate)
            shutil.copyfile(source, target)
        except OSError as exc:
            notes.append(f"{candidate} was downloaded but could not be kept for sending ({exc}).")
            continue
        used.add(candidate.lower())
        paths.append(target)
    return paths, notes


def safe_name(name, fallback=FALLBACK_NAME):
    """A name reduced to one path segment that cannot escape its directory.

    Names reach this seat from a web page and from other people's machines, and
    they end up as filenames on the *sender's* disk after a `tell --attach`. So
    the reduction happens once, here, rather than at each use.
    """
    base = os.path.basename((name or "").strip().replace("\\", "/").rstrip("/"))
    base = base.replace("\0", "")
    if base in ("", ".", ".."):
        return fallback
    return base
