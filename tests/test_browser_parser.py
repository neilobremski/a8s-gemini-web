"""The fake seat must refuse what the real seat refuses.

`tests/conftest.py` mirrors a8s-browser's script parser so a generated script
is read here by the rules the real seat reads it by. A mirror drifts: the
review that produced `tests/test_findings.py` found this one a version behind,
and a driver tested against a parser nobody runs is tested against nothing.

Two defences. The table below is the contract, written out case by case, and it
is checked against the real parser whenever a checkout of a8s-browser can be
found — `A8S_BROWSER_SRC`, or a sibling directory. When it cannot, the table
still runs against the mirror, so the cases are never skipped in full.
"""
import os
import sys

import pytest
from conftest import ScriptError, script_commands

# (script, expected) where expected is the list of (command, block) pairs the
# parser produces, or the substring of the refusal it must raise instead.
CASES = [
    ("go https://example.test", [("go https://example.test", None)]),
    ("# a comment\n\npress Enter", [("press Enter", None)]),
    ("   fill 'box' 'text'   ", [("fill 'box' 'text'", None)]),
    ("type <<T\n  indented\nT", [("type", "  indented")]),
    ("type <<T\n\nT", [("type", "")]),
    ("type <<T\n# not a comment in here\nT", [("type", "# not a comment in here")]),
    ("type <<T\npress Enter\nT", [("type", "press Enter")]),
    ("type <<T\ncat <<EOF\nT", [("type", "cat <<EOF")]),
    ("type <<T\nline one\nline two\nT", [("type", "line one\nline two")]),
    ("type <<T\nbody\nT\npress Enter", [("type", "body"), ("press Enter", None)]),
    # The rule that cost a turn: an opener carries the verb and nothing else.
    ("type Dear team <<T\nbody\nT", "inline argument"),
    ("fill 'box' 'text' <<T\nbody\nT", "inline argument"),
    ("type <<T\nbody", "unterminated"),
    # CRLF: splitlines eats the pair, so no carriage return reaches a command
    # and a marker line still terminates its block.
    ("type <<T\r\nbody\r\nT\r\n", [("type", "body")]),
]


def real_parser():
    """a8s-browser's own `script_commands`, if a checkout is reachable."""
    named = os.environ.get("A8S_BROWSER_SRC")
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for candidate in [named] if named else [
        os.path.join(os.path.dirname(here), "a8s-browser", "src"),
    ]:
        if candidate and os.path.isfile(os.path.join(candidate, "commands.py")):
            sys.path.insert(0, candidate)
            try:
                import commands
            finally:
                sys.path.remove(candidate)
            return commands
    return None


def run(parser, script):
    """One script through a parser, as pairs or as the refusal's text."""
    if parser is None:
        try:
            return script_commands(script)
        except ScriptError as exc:
            return str(exc)
    try:
        return parser.script_commands(script)
    except parser.ScriptError as exc:
        return str(exc)


@pytest.mark.parametrize("script,expected", CASES)
def test_the_mirror_parses_what_the_contract_says(script, expected):
    outcome = run(None, script)
    if isinstance(expected, str):
        assert isinstance(outcome, str) and expected in outcome
    else:
        assert outcome == expected


@pytest.mark.parametrize("script,expected", CASES)
def test_the_real_parser_agrees_with_the_mirror(script, expected):
    parser = real_parser()
    if parser is None:
        pytest.skip("no a8s-browser checkout reachable; the contract table still ran")
    real = run(parser, script)
    mirror = run(None, script)
    if isinstance(real, str) or isinstance(mirror, str):
        assert isinstance(real, str) and isinstance(mirror, str), (
            f"one parser refused {script!r} and the other did not: {real!r} vs {mirror!r}"
        )
        return
    assert real == mirror


def test_a_message_this_driver_sends_parses_the_same_in_both(tmp_path):
    import gemini

    parser = real_parser()
    if parser is None:
        pytest.skip("no a8s-browser checkout reachable")
    message = 'def f():\n    print("it\'s here")\n\nAnd: cat <<EOF'
    script = gemini.send_script(gemini.PROMPT_FALLBACK_LABEL, message)
    assert parser.script_commands(script) == script_commands(script)
