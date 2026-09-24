"""A tell that carries files, from the message body into the conversation."""
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
    def test_the_file_is_dropped_and_only_the_prose_is_typed(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        path = _attached(tmp_path, "report.pdf")
        code = answer(
            "gemini", "example-sender", _with_files("summarise this", path), outbox, seat
        )
        assert code == 0
        assert seat.attached == ["report.pdf"]
        # The path is the thing that must not reach the page as text. It
        # belongs on the drop line and nowhere else.
        assert _asked(seat)[-1] == "summarise this"
        carrying = [
            line
            for script in seat.scripts
            for line in script.splitlines()
            if path in line
        ]
        assert carrying and all(line.startswith("drop ") for line in carrying)
        assert "report.pdf" in outbox.last

    def test_the_drop_happens_before_the_keystroke_that_sends(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        path = _attached(tmp_path, "chart.png")
        answer("gemini", "example-sender", _with_files("what is this", path), outbox, seat)
        joined = "\n".join(seat.scripts)
        # A file that lands after the send is a question about nothing.
        assert joined.index("drop ") < joined.rindex(gemini.SUBMIT_STEP)

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

    def test_a_chip_that_is_still_uploading_does_not_confirm(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        # The filename renders while the upload runs and Send is disabled.
        seat.upload_settle_polls = 10_000
        path = _attached(tmp_path, "slow.pdf")

        code = answer("gemini", "example-sender", _with_files("read it", path), outbox, seat)

        assert code == 1
        assert "read it" not in _asked(seat)
        assert "did not settle" in outbox.last

    def test_an_upload_that_settles_is_confirmed(
        self, tmp_path, seat, outbox, clock, state_home
    ):
        seat.upload_settle_polls = 2  # renders, moves, then stops
        path = _attached(tmp_path, "fine.pdf")

        code = answer("gemini", "example-sender", _with_files("read it", path), outbox, seat)

        assert code == 0
        assert _asked(seat)[-1] == "read it"
        assert seat.attached == ["fine.pdf"]

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
