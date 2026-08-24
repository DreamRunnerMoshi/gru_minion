"""Covers the fix from experiments/exp3/LOG.md's "RepeatedFormatError fix (2026-08-23)"
section: GruModel now escalates its correction text as consecutive FormatErrors pile up
(orchestrator/gru_toolcall.py's _escalation_prefix, orchestrator/gru_model.py's counter),
instead of repeating the same static message every retry. This never got a live-infra
confirmation before the cloud diagnostic run it was waiting on got stopped mid-session —
these tests are the offline substitute: deterministic, no GPU, no Ollama.
"""

from tests.harness import run_session
from tests.mock_llm import Text, Tool

MAX_CONSECUTIVE_FORMAT_ERRORS = 6  # orchestrator/config/gru.yaml agent.max_consecutive_format_errors


def _all_message_text(llm) -> str:
    return "\n".join(
        str(m.get("content", "")) for call in llm.calls for m in call["messages"] if isinstance(m, dict)
    )


def test_repeated_prose_trips_the_limit(tmp_path):
    """The exact failure mode from exp3: the model writes a prose conclusion instead of
    calling a tool, MAX_CONSECUTIVE_FORMAT_ERRORS times in a row. Session must end via
    RepeatedFormatError (mini-swe-agent's own safety valve), not hang or crash some
    other way."""
    steps = [Text("The fix looks correct and all tests should now pass.")] * MAX_CONSECUTIVE_FORMAT_ERRORS
    session = run_session(tmp_path=tmp_path, steps=steps)

    assert session.result["exit_status"] == "RepeatedFormatError"
    assert len(session.llm.calls) == MAX_CONSECUTIVE_FORMAT_ERRORS


def test_correction_escalates_instead_of_repeating(tmp_path):
    """The mechanism, not just the outcome: later retries must carry a sharper warning
    than the first one, not the same text every time (that static-message behavior is
    exactly what exp3 found doesn't work — think was added as an escape hatch and was
    used 0/147 times)."""
    steps = [Text("Done.")] * MAX_CONSECUTIVE_FORMAT_ERRORS
    session = run_session(tmp_path=tmp_path, steps=steps)

    all_text = _all_message_text(session.llm)
    assert "2nd response in a row" in all_text, "mild escalation (2nd failure) never reached the model"
    assert "EMPTY submission" in all_text, "hard escalation (3rd+ failure) never reached the model"

    # The hard warning must appear strictly after the mild one, on a later call —
    # otherwise this could pass by coincidence (e.g. the whole template dumped once).
    mild_idx = next(i for i, c in enumerate(session.llm.calls) if "2nd response in a row" in str(c["messages"]))
    hard_idx = next(i for i, c in enumerate(session.llm.calls) if "EMPTY submission" in str(c["messages"]))
    assert hard_idx > mild_idx


def test_a_clean_turn_resets_the_counter(tmp_path):
    """2 failures, then one valid `think` call, then MAX_CONSECUTIVE_FORMAT_ERRORS more
    failures — must take the full budget again after the reset, not trip early on
    2 + MAX_CONSECUTIVE_FORMAT_ERRORS - 2. Validates GruModel._consecutive_format_errors
    actually resets on a clean parse rather than just accumulating for the whole session."""
    steps = (
        [Text("almost done")] * 2
        + [Tool("think", {"note": "let me reconsider"})]
        + [Text("done now")] * MAX_CONSECUTIVE_FORMAT_ERRORS
    )
    session = run_session(tmp_path=tmp_path, steps=steps)

    assert session.result["exit_status"] == "RepeatedFormatError"
    # If the counter hadn't reset, this would trip after 2 + (6 - 2) = 6 calls instead
    # of consuming the full script (2 + 1 + 6 = 9).
    assert len(session.llm.calls) == len(steps)
