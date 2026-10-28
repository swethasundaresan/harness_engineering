"""The runner guarantees every claim ends routed or escalated, even if the model doesn't."""

import json
from pathlib import Path

from claims_intake.run import _run_one
from tests.fakes import FakeBlock, FakeClient, FakeMessages, FakeResponse, FakeUsage


def test_claim_without_terminal_tool_is_escalated(tmp_path: Path) -> None:
    """end_turn with no route/escalate call still produces an escalation record."""
    scripted = [
        FakeResponse(
            content=[FakeBlock(type="text", text="Thanks, I have everything I need.")],
            stop_reason="end_turn",
            usage=FakeUsage(input_tokens=10, output_tokens=5),
        ),
    ]
    result = _run_one(
        client=FakeClient(messages=FakeMessages(scripted=scripted)),
        model="fake-model",
        fixture={"claim_id": "CLM-T", "policy_id": "POL-T", "initial_message": "hi"},
        policies={},
        run_dir=tmp_path,
        max_input_tokens=1_000_000,
        max_wall_clock_s=60.0,
    )

    assert result.session.outcome == "escalated"
    lines = (tmp_path / "escalations.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["claim_id"] == "CLM-T"
