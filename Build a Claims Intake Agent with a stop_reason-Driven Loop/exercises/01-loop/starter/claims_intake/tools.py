"""Tool schemas and dispatcher.

Seven tools, registered with Anthropic tool-use shape.
Tool results are serialized JSON strings.

Graceful errors use this shape:

    {
        "is_error": true,
        "error_category": "transient" | "permanent",
        "is_retryable": bool,
        "message": "..."
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claims_intake.session import ClaimSession


CLAIM_TYPES = ["property_damage", "theft", "liability", "auto"]
SEVERITIES = ["low", "medium", "high"]


# ----------------------------------------------------------------------------
# Tool schemas
# ----------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "lookup_policy",
        "description": (
            "Look up an insurance policy by policy ID. "
            "Use this early in claim intake to confirm policy information."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "policy_id": {
                    "type": "string",
                    "description": "Policy identifier to look up.",
                }
            },
            "required": ["policy_id"],
        },
    },
    {
        "name": "record_claim_fact",
        "description": (
            "Record one normalized fact about the claim, such as incident date, "
            "location, damaged item, or item lost."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "description": "Normalized fact field name.",
                },
                "value": {
                    "type": "string",
                    "description": "Value of the claim fact.",
                },
            },
            "required": ["field", "value"],
        },
    },
    {
        "name": "classify_claim",
        "description": (
            "Classify the claim into one supported claim type. "
            "Provide confidence and rationale for the classification."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "claim_type": {
                    "type": "string",
                    "enum": CLAIM_TYPES,
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "rationale": {
                    "type": "string",
                },
            },
            "required": [
                "claim_type",
                "confidence",
                "rationale",
            ],
        },
    },
    {
        "name": "assess_severity",
        "description": (
            "Assess the severity of the claim after sufficient facts "
            "have been collected."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": SEVERITIES,
                },
                "rationale": {
                    "type": "string",
                },
            },
            "required": [
                "severity",
                "rationale",
            ],
        },
    },
    {
        "name": "request_clarification",
        "description": (
            "Ask the claimant a clarification question when important facts "
            "are ambiguous between possible claim types."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                },
                "ambiguity_between": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                    "minItems": 2,
                },
            },
            "required": [
                "question",
                "ambiguity_between",
            ],
        },
    },
    {
        "name": "route_to_adjuster",
        "description": (
            "Route a classified and severity-assessed claim to the "
            "appropriate adjuster queue. This is a terminal action."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "queue": {
                    "type": "string",
                    "enum": CLAIM_TYPES,
                },
                "claim_summary": {
                    "type": "string",
                },
            },
            "required": [
                "queue",
                "claim_summary",
            ],
        },
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Escalate the claim to a human when ambiguity or another issue "
            "prevents reliable automated routing. This is a terminal action."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                },
                "structured_summary": {
                    "type": "object",
                    "properties": {
                        "policy_id": {
                            "type": "string",
                        },
                        "root_cause": {
                            "type": "string",
                        },
                        "candidate_claim_types": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": CLAIM_TYPES,
                            },
                        },
                        "case_facts": {
                            "type": "object",
                        },
                        "recommended_action": {
                            "type": "string",
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0,
                            "maximum": 1,
                        },
                    },
                    "required": [
                        "policy_id",
                        "root_cause",
                        "candidate_claim_types",
                        "case_facts",
                        "recommended_action",
                        "confidence",
                    ],
                },
            },
            "required": [
                "reason",
                "structured_summary",
            ],
        },
    },
]


# ----------------------------------------------------------------------------
# Result helpers
# ----------------------------------------------------------------------------


def _err(category: str, retryable: bool, message: str) -> str:
    return json.dumps(
        {
            "is_error": True,
            "error_category": category,
            "is_retryable": retryable,
            "message": message,
        }
    )


def _ok(payload: dict[str, Any]) -> str:
    return json.dumps(payload)


# ----------------------------------------------------------------------------
# Tool implementations
# ----------------------------------------------------------------------------


def _t_lookup_policy(
    session: ClaimSession,
    inp: dict[str, Any],
) -> str:
    policy_id = inp.get("policy_id")

    if not isinstance(policy_id, str):
        return _err(
            "permanent",
            False,
            "policy_id must be a string",
        )

    policy = session.policies.get(policy_id)

    if policy is None:
        return _err(
            "permanent",
            False,
            f"policy {policy_id} not found",
        )

    return _ok(policy)


def _t_record_claim_fact(
    session: ClaimSession,
    inp: dict[str, Any],
) -> str:
    field_name = inp.get("field")
    value = inp.get("value")

    if not isinstance(field_name, str):
        return _err(
            "permanent",
            False,
            "field must be a string",
        )

    if not isinstance(value, str):
        return _err(
            "permanent",
            False,
            "value must be a string",
        )

    session.case_facts[field_name] = value

    return _ok(
        {
            "recorded": True,
            "field": field_name,
            "case_facts_count": len(session.case_facts),
        }
    )


def _t_classify_claim(
    session: ClaimSession,
    inp: dict[str, Any],
) -> str:
    claim_type = inp.get("claim_type")
    confidence = inp.get("confidence")
    rationale = inp.get("rationale")

    if claim_type not in CLAIM_TYPES:
        return _err(
            "permanent",
            False,
            f"invalid claim_type: {claim_type}",
        )

    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
    ):
        return _err(
            "permanent",
            False,
            "confidence must be a number",
        )

    if not 0 <= confidence <= 1:
        return _err(
            "permanent",
            False,
            "confidence must be between 0 and 1",
        )

    if not isinstance(rationale, str):
        return _err(
            "permanent",
            False,
            "rationale must be a string",
        )

    session.classification = {
        "claim_type": claim_type,
        "confidence": confidence,
        "rationale": rationale,
    }

    return _ok(
        {
            "recorded": True,
            "claim_type": claim_type,
            "confidence": confidence,
            "rationale": rationale,
        }
    )


def _t_assess_severity(
    session: ClaimSession,
    inp: dict[str, Any],
) -> str:
    severity = inp.get("severity")
    rationale = inp.get("rationale")

    if severity not in SEVERITIES:
        return _err(
            "permanent",
            False,
            f"invalid severity: {severity}",
        )

    if not isinstance(rationale, str):
        return _err(
            "permanent",
            False,
            "rationale must be a string",
        )

    session.severity = {
        "severity": severity,
        "rationale": rationale,
    }

    return _ok(
        {
            "recorded": True,
            "severity": severity,
            "rationale": rationale,
        }
    )


def _t_request_clarification(
    session: ClaimSession,
    inp: dict[str, Any],
) -> str:
    question = inp.get("question")
    ambiguity_between = inp.get("ambiguity_between")

    if not isinstance(question, str):
        return _err(
            "permanent",
            False,
            "question must be a string",
        )

    if (
        not isinstance(ambiguity_between, list)
        or len(ambiguity_between) < 2
    ):
        return _err(
            "permanent",
            False,
            "ambiguity_between must contain at least two entries",
        )

    session.clarifications_asked.append(
        {
            "question": question,
            "ambiguity_between": ambiguity_between,
        }
    )

    question_lower = question.lower()

    for key, reply in session.clarification_responses.items():
        if key.lower() in question_lower:
            return _ok(
                {
                    "claimant_reply": reply,
                }
            )

    return _ok(
        {
            "claimant_reply": "NO_RESPONSE",
        }
    )


def _t_route_to_adjuster(
    session: ClaimSession,
    inp: dict[str, Any],
) -> str:
    if session.terminal_called:
        return _err(
            "permanent",
            False,
            "terminal tool already called",
        )

    queue = inp.get("queue")
    claim_summary = inp.get("claim_summary")

    if queue not in CLAIM_TYPES:
        return _err(
            "permanent",
            False,
            f"invalid queue: {queue}",
        )

    if not isinstance(claim_summary, str):
        return _err(
            "permanent",
            False,
            "claim_summary must be a string",
        )

    if session.classification is None:
        return _err(
            "permanent",
            False,
            "classify_claim must be called before route_to_adjuster",
        )

    if session.severity is None:
        return _err(
            "permanent",
            False,
            "assess_severity must be called before route_to_adjuster",
        )

    record = {
        "claim_id": session.claim_id,
        "policy_id": session.policy_id,
        "claim_type": session.classification["claim_type"],
        "severity": session.severity["severity"],
        "confidence": session.classification["confidence"],
        "rationale": session.classification["rationale"],
        "claim_summary": claim_summary,
        "case_facts": dict(session.case_facts),
    }

    session.routing = record

    queue_file = (
        session.run_dir
        / "queues"
        / f"{queue}.jsonl"
    )

    _append_jsonl(queue_file, record)

    return _ok(
        {
            "routed": True,
            "queue": queue,
        }
    )


def _t_escalate_to_human(
    session: ClaimSession,
    inp: dict[str, Any],
) -> str:
    if session.terminal_called:
        return _err(
            "permanent",
            False,
            "terminal tool already called",
        )

    reason = inp.get("reason")
    structured_summary = inp.get("structured_summary")

    if not isinstance(reason, str):
        return _err(
            "permanent",
            False,
            "reason must be a string",
        )

    if not isinstance(structured_summary, dict):
        return _err(
            "permanent",
            False,
            "structured_summary must be an object",
        )

    required_fields = [
        "policy_id",
        "root_cause",
        "candidate_claim_types",
        "case_facts",
        "recommended_action",
        "confidence",
    ]

    missing = [
        field_name
        for field_name in required_fields
        if field_name not in structured_summary
    ]

    if missing:
        return _err(
            "permanent",
            False,
            "structured_summary missing required fields: "
            + ", ".join(missing),
        )

    record = {
        "claim_id": session.claim_id,
        "policy_id": session.policy_id,
        "reason": reason,
        **structured_summary,
        "case_facts_at_escalation": dict(session.case_facts),
    }

    session.escalation = record

    escalation_file = session.run_dir / "escalations.jsonl"

    _append_jsonl(
        escalation_file,
        record,
    )

    return _ok(
        {
            "escalated": True,
        }
    )


# ----------------------------------------------------------------------------
# Dispatcher
# ----------------------------------------------------------------------------

_DISPATCH = {
    "lookup_policy": _t_lookup_policy,
    "record_claim_fact": _t_record_claim_fact,
    "classify_claim": _t_classify_claim,
    "assess_severity": _t_assess_severity,
    "request_clarification": _t_request_clarification,
    "route_to_adjuster": _t_route_to_adjuster,
    "escalate_to_human": _t_escalate_to_human,
}


def make_executor(session: ClaimSession) -> Executor:
    """Return a ToolExecutor callable bound to this session."""

    def execute(
        name: str,
        tool_input: dict[str, Any],
    ) -> str:
        handler = _DISPATCH.get(name)

        if handler is None:
            return _err(
                "permanent",
                False,
                f"unknown tool: {name}",
            )

        try:
            return handler(
                session,
                tool_input,
            )
        except Exception as exc:
            return _err(
                "transient",
                True,
                f"{type(exc).__name__}: {exc}",
            )

    return execute


Executor = Any


def _append_jsonl(
    path: Path,
    record: dict[str, Any],
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "a",
        encoding="utf-8",
    ) as fh:
        fh.write(
            json.dumps(
                record,
                ensure_ascii=False,
            )
            + "\n"
        )