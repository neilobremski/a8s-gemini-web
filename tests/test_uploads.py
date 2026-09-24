"""A tell that carries files, from the message body into the conversation."""
import shlex

from test_handler import answer

import attachments
import gemini
import handler


def _attached(tmp_path, name, data=b"payload"):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def _with_files(prose, *paths):
    lines = [prose, ""] + [f"{attachments.ATTACHED_PREFIX}{path}" for path in paths]
    return "\n".join(lines)


def _typed(seat):
    return [text for role, text in seat.history if role == "user"]


def _asked(seat):
    """What a correspondent's own messages were, without the seat's preamble.

    A new correspondent gets the preamble typed first, so "nothing was typed"
    has to mean "the sender's message was not typed".
    """
    return [text for text in _typed(seat) if not text.startswith("You are ")]


class TestInbound:
    def test_the_file_is_uploaded_and_only_the_prose_is_typed(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        path = _attached(tmp_path, "report.pdf")
        code = answer(
            "gemini", "example-sender", _with_files("summarise this", path), outbox, seat
        )
        assert code == 0
        assert seat.attached == ["report.pdf"]
        # The path is the thing that must not reach the page as text. It
        # belongs on the line that answers the file chooser and nowhere else.
        assert _asked(seat)[-1] == "summarise this"
        carrying = [
            line
            for script in seat.scripts
            for line in script.splitlines()
            if path in line
        ]
        assert carrying and all(line.startswith("upload ") for line in carrying)
        assert "report.pdf" in outbox.last

    def test_the_upload_happens_before_the_keystroke_that_sends(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        path = _attached(tmp_path, "chart.png")
        answer("gemini", "example-sender", _with_files("what is this", path), outbox, seat)
        joined = "\n".join(seat.scripts)
        # A file that lands after the send is a question about nothing.
        assert joined.index("upload ") < joined.rindex(gemini.SUBMIT_STEP)

    def test_several_files_go_in_together(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        one = _attached(tmp_path, "a.png")
        two = _attached(tmp_path, "b.png")
        answer("gemini", "example-sender", _with_files("compare", one, two), outbox, seat)
        assert seat.attached == ["a.png", "b.png"]

    def test_an_upload_that_takes_a_moment_is_waited_for(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        seat.upload_polls = 3
        path = _attached(tmp_path, "slow.pdf")
        code = answer("gemini", "example-sender", _with_files("read it", path), outbox, seat)
        assert code == 0
        assert seat.attached == ["slow.pdf"]

    def test_an_upload_that_never_appears_keeps_the_message(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        seat.upload_polls = 10_000
        path = _attached(tmp_path, "stuck.pdf")
        code = answer("gemini", "example-sender", _with_files("read it", path), outbox, seat)
        # Nothing was submitted, so a8s may hand this back — and must, rather
        # than let the sender believe Gemini saw the file.
        assert code == 1
        assert _asked(seat) == []
        assert "stuck.pdf" in outbox.last
        assert "was not sent" in outbox.last

    def test_a_missing_file_is_a_non_send_not_a_wrong_answer(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        code = answer(
            "gemini",
            "example-sender",
            _with_files("read it", str(tmp_path / "gone.pdf")),
            outbox,
            seat,
        )
        assert code == 1
        assert _asked(seat) == []

    def test_a_lost_attachment_is_named_in_the_reply(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        message = (
            "look at this\n\n"
            f"{attachments.UNAVAILABLE_PREFIX}chart.png: could not download after 900s"
        )
        code = answer("gemini", "example-sender", message, outbox, seat)
        assert code == 0
        # The question still goes to Gemini; the sender is told what it went without.
        assert _asked(seat)[-1] == "look at this"
        assert "chart.png" in outbox.last


class TestTheUploadMenu:
    """Files go in through Gemini's own menu and chooser (live, 2026-09-24)."""

    def test_each_file_gets_its_own_menu_and_chooser(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        one = _attached(tmp_path, "a.png")
        two = _attached(tmp_path, "b.png")
        answer("gemini", "example-sender", _with_files("compare", one, two), outbox, seat)
        joined = "\n".join(seat.scripts)
        # A chooser takes one file and closes, so the menu opens once per file.
        assert joined.count(f"click {shlex.quote(gemini.UPLOAD_MENU_SELECTOR)}") == 2
        assert joined.count(f"upload {one}") == 1
        assert joined.count(f"upload {two}") == 1

    def test_a_synthetic_drop_is_never_used(self, tmp_path, seat, outbox, clock, state_home):
        path = _attached(tmp_path, "report.pdf")
        answer("gemini", "example-sender", _with_files("read it", path), outbox, seat)
        assert not any(
            line.startswith("drop ") for script in seat.scripts for line in script.splitlines()
        )

    def test_a_chooser_that_never_opens_is_a_non_send_and_the_menu_is_closed(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        seat.clickable.discard(gemini.UPLOAD_MENU_SELECTOR)  # the page changed shape
        path = _attached(tmp_path, "report.pdf")
        code = answer("gemini", "example-sender", _with_files("read it", path), outbox, seat)
        assert code == 1
        assert _asked(seat) == []
        assert "report.pdf" in outbox.last
        # An open menu swallows the keystrokes that follow it.
        assert "press Escape" in seat.scripts
        assert not seat.menu_open

    def test_the_chip_shows_the_name_without_its_extension(self):
        assert gemini.chip_label("probe-note.txt") == "probe-note"
        assert gemini.chip_label("archive.tar.gz") == "archive.tar"
        assert gemini.chip_label("README") == "README"
        # Read off the live chip for a 47-character name.
        long_name = "a-rather-long-file-name-for-the-chip-check-2026.txt"
        assert gemini.chip_label(long_name) == "a-rather-l...check-2026"
        chip = "- generic [ref=e1] [cursor=pointer]:\n  - generic [ref=e2]: TXT\n" \
            "  - generic [ref=e3]: probe-note\n"
        assert gemini._name_counts(chip, ["probe-note.txt"]) == (1,)


class TestConsent:
    def test_the_first_upload_disclaimer_keeps_the_message_and_names_the_fix(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        seat.consent_needed = True
        path = _attached(tmp_path, "report.pdf")
        code = answer(
            "gemini", "example-sender", _with_files("summarise", path), outbox, seat
        )
        # Nothing was typed, so the message is worth keeping until a person
        # accepts the disclaimer once.
        assert code == 1
        assert _asked(seat) == []
        assert "Agree" in outbox.last
        assert "by hand" in outbox.last

    def test_the_driver_never_presses_agree_itself(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        seat.consent_needed = True
        path = _attached(tmp_path, "report.pdf")
        answer("gemini", "example-sender", _with_files("summarise", path), outbox, seat)
        # Accepting terms on somebody's account is not this driver's to do.
        assert "Agree" not in "\n".join(seat.scripts)

    def test_consent_is_recognised_from_the_page_text(self):
        assert gemini.consent_pending(f'- heading "{gemini.CONSENT_HEADING}" [level=1]')
        assert not gemini.consent_pending("- textbox \"Enter a prompt for Gemini\"")
        assert not gemini.consent_pending("")


class TestTellArgv:
    def test_each_file_travels_as_its_own_attach_flag(self, monkeypatch):
        seen = {}

        class Done:
            returncode = 0

        def fake_run(argv, **kwargs):
            seen["argv"] = argv
            return Done()

        monkeypatch.setattr(handler.subprocess, "run", fake_run)
        handler._tell("someone", "body", ["/tmp/a.png", "/tmp/b.png"])
        # The `=` form on purpose: `--attach a.png someone` would swallow the
        # recipient whenever it happened to name an existing file.
        assert seen["argv"] == [
            "tell", "--attach=/tmp/a.png", "--attach=/tmp/b.png", "someone", "-",
        ]

    def test_no_files_means_the_command_it_always_was(self, monkeypatch):
        seen = {}

        class Done:
            returncode = 0

        monkeypatch.setattr(
            handler.subprocess, "run",
            lambda argv, **kwargs: (seen.update(argv=argv), Done())[1],
        )
        handler._tell("someone", "body")
        assert seen["argv"] == ["tell", "someone", "-"]


class TestConfirmationIsNotJustTheName:
    """Carlos R1 on PR3: the page carries the whole conversation."""

    def test_a_name_already_in_the_history_does_not_confirm_a_new_upload(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        # A real earlier turn, so the conversation is resumed rather than
        # created — a fresh conversation would clear the history and the
        # scenario with it.
        answer("gemini", "example-sender", "I will send you report.pdf shortly", outbox, seat)
        assert any("report.pdf" in text for _, text in seat.history)

        seat.upload_polls = 10_000  # this upload never lands
        path = _attached(tmp_path, "report.pdf")

        code = answer(
            "gemini", "example-sender", _with_files("and this one?", path), outbox, seat
        )

        # Before the repair this returned 0, submitted the prompt without the
        # file, and told the sender it was attached.
        assert code == 1
        assert "and this one?" not in _asked(seat)
        assert "was not sent" in outbox.last
        assert "attached to this turn" not in outbox.last

    def test_a_chip_beside_a_disabled_send_never_confirms(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        """Carlos R1 on the repair: the pending page is STATIC.

        The chip is there and the indicator never moves, so two identical
        snapshots are the normal case for an upload that has not finished.
        """
        seat.upload_pending_polls = 10_000
        path = _attached(tmp_path, "slow.pdf")

        code = answer("gemini", "example-sender", _with_files("read it", path), outbox, seat)

        assert code == 1
        assert "read it" not in _asked(seat)
        assert "did not finish uploading" in outbox.last

    def test_an_upload_that_becomes_ready_is_confirmed(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        # Disabled for a while, then the control enables: the transition is the
        # only thing that counts as done.
        seat.upload_pending_polls = 3
        path = _attached(tmp_path, "fine.pdf")

        code = answer("gemini", "example-sender", _with_files("read it", path), outbox, seat)

        assert code == 0
        assert _asked(seat)[-1] == "read it"
        assert seat.attached == ["fine.pdf"]

    def test_no_send_control_is_unknown_and_unknown_is_not_ready(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        # The page changed shape. Absence of evidence must not read as ready.
        seat.send_button = False
        path = _attached(tmp_path, "report.pdf")

        code = answer("gemini", "example-sender", _with_files("read it", path), outbox, seat)

        assert code == 1
        assert "read it" not in _asked(seat)
        assert "cannot tell" in outbox.last
        assert gemini.SEND_BUTTON_NAME in outbox.last
        assert "docs/gemini-ui.md" in outbox.last

    def test_the_text_is_typed_before_the_files_go_in(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        # The send control does not exist on an empty composer, so an upload
        # that happened first would leave nothing to read.
        path = _attached(tmp_path, "order.pdf")
        answer("gemini", "example-sender", _with_files("read it", path), outbox, seat)
        joined = "\n".join(seat.scripts)
        assert joined.index("type <<") < joined.rindex("upload ")
        assert joined.rindex("upload ") < joined.rindex(gemini.SUBMIT_STEP)

    def test_send_ready_reads_the_control_three_ways(self):
        enabled = f'- button "{gemini.SEND_BUTTON_NAME}" [ref=e1] [cursor=pointer]'
        disabled = f'- button "{gemini.SEND_BUTTON_NAME}" [ref=e1] [disabled]'
        assert gemini.send_ready(enabled) is True
        assert gemini.send_ready(disabled) is False
        assert gemini.send_ready('- textbox "Enter a prompt for Gemini" [ref=e1]') is None

    def test_a_repeat_of_the_same_filename_is_still_confirmed(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        # Sending the same name twice must work: the test is one MORE
        # occurrence, not a first one.
        path = _attached(tmp_path, "again.pdf")
        answer("gemini", "example-sender", _with_files("first", path), outbox, seat)
        seat.attached = []  # Gemini clears the composer after a send
        code = answer("gemini", "example-sender", _with_files("second", path), outbox, seat)
        assert code == 0
        assert _asked(seat)[-1] == "second"
