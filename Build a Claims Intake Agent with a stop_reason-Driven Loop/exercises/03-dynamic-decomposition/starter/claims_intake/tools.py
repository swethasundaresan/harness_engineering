"""Tool schemas and dispatcher.

Seven tools are registered using the Anthropic tool-use shape. The dispatcher
returns serialized JSON strings to be wrapped as tool_result content.

Errors follow the Graceful Tool Failure shape:

    {
        "is_error": true,
        "error_category": "transient" | "permanent",
        "is_retryable": bool,
        "message": "..."
    }

Errors are returned to the model and are never raised to the agentic loop.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claims_intake.session import ClaimSession


CLAIM_TYPES = [
    "property_damage",
    "theft",
    "liability",
    "auto",
]

SEVERITIES = [
    "low",
    "medium",
    "high",
]


# ----------------------------------------------------------------------------
# Schemas passed to the Anthropic Messages API
# ----------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "lookup_policy",
        "description": (
            "Look up a policyholder's coverage record. Use this early in the "
            "conversation to confirm that the policy exists, what it covers, "
            "its deductible, and its status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "policy_id": {
                    "type": "string",
                    "description": "Policy identifier, such as POL-1001.",
                },
            },
            "required": ["policy_id"],
        },
    },
    {
        "name": "record_claim_fact",
        "description": (
            "Record one normalized fact extracted from the claimant's "
            "statements. Call this once for each fact, such as incident_date, "
            "location, description, items_lost, or injury_party."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "description": (
                        "Snake-case field name, such as incident_date "
                        "or location."
                    ),
                },
                "value": {
                    "type": "string",
                    "description": "The claim fact as a short string.",
                },
            },
            "required": ["field", "value"],
        },
    },
    {
        "name": "classify_claim",
        "description": (
            "Commit to a claim type with a confidence score and rationale. "
            "Call this after enough facts and clarifications have been gathered."
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
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "description": (
                        "Classification confidence, where 0 means no "
                        "confidence and 1 means certain."
                    ),
                },
                "rationale": {
                    "type": "string",
                    "description": (
                        "A concise explanation of why the selected claim "
                        "type fits the available facts."
                    ),
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
            "Assess the claim's severity after classification. Severity should "
            "reflect damage magnitude, injury severity, and available facts."
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
                    "description": (
                        "A concise explanation of the selected severity."
                    ),
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
            "Ask the claimant one clarifying question when the available "
            "facts are ambiguous between two or more claim types."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "One clear clarification question for the claimant."
                    ),
                },
                "ambiguity_between": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": CLAIM_TYPES,
                    },
                    "minItems": 2,
                    "description": (
                        "The candidate claim types the question should "
                        "distinguish between."
                    ),
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
            "Terminal tool that routes a classified and severity-assessed "
            "claim to the appropriate adjuster queue."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "queue": {
                    "type": "string",
                    "enum": CLAIM_TYPES,
                    "description": (
                        "The adjuster queue that should receive the claim."
                    ),
                },
                "claim_summary": {
                    "type": "string",
                    "description": (
                        "A concise summary of the claim for the adjuster."
                    ),
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
            "Terminal tool that escalates a claim when it cannot be routed "
            "safely because of unresolved ambiguity, insufficient confidence, "
            "or another blocking condition."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": (
                        "Why automated processing cannot safely continue."
                    ),
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
                            "minimum": 0.0,
                            "maximum": 1.0,
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


def _err(
    category: str,
    retryable: bool,
    message: str,
) -> str:
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
            f"policy_id {policy_id!r} not found",
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
            f"claim_type must be one of {CLAIM_TYPES}",
        )

    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
    ):
        return _err(
            "permanent",
            False,
            "confidence must be a number in [0,1]",
        )

    normalized_confidence = float(confidence)

    if not 0.0 <= normalized_confidence <= 1.0:
        return _err(
            "permanent",
            False,
            "confidence must be a number in [0,1]",
        )

    if not isinstance(rationale, str):
        return _err(
            "permanent",
            False,
            "rationale must be a string",
        )

    session.classification = {
        "claim_type": claim_type,
        "confidence": normalized_confidence,
        "rationale": rationale,
    }

    return _ok(
        {
            "recorded": True,
            **session.classification,
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
            f"severity must be one of {SEVERITIES}",
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
            **session.severity,
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

    if not all(
        isinstance(item, str) and item in CLAIM_TYPES
        for item in ambiguity_between
    ):
        return _err(
            "permanent",
            False,
            f"ambiguity_between entries must be in {CLAIM_TYPES}",
        )

    session.clarifications_asked.append(
        {
            "question": question,
            "ambiguity_between": list(ambiguity_between),
        }
    )

    normalized_question = question.lower()

    for keyword, response in session.clarification_responses.items():
        if keyword.lower() in normalized_question:
            return _ok(
                {
                    "claimant_reply": response,
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
            "a terminal tool has already called",
        )

    queue = inp.get("queue")
    claim_summary = inp.get("claim_summary")

    if queue not in CLAIM_TYPES:
        return _err(
            "permanent",
            False,
            f"queue must be one of {CLAIM_TYPES}",
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

    queue_path = (
        session.run_dir
        / "queues"
        / f"{queue}.jsonl"
    )

    _append_jsonl(
        queue_path,
        record,
    )

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
            "a terminal tool has already called",
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

    required_fields = {
        "policy_id",
        "root_cause",
        "candidate_claim_types",
        "case_facts",
        "recommended_action",
        "confidence",
    }

    missing_fields = sorted(
        required_fields - structured_summary.keys()
    )

    if missing_fields:
        return _err(
            "permanent",
            False,
            "structured_summary is missing required fields: "
            + ", ".join(missing_fields),
        )

    policy_id = structured_summary["policy_id"]
    root_cause = structured_summary["root_cause"]
    candidate_claim_types = structured_summary[
        "candidate_claim_types"
    ]
    case_facts = structured_summary["case_facts"]
    recommended_action = structured_summary[
        "recommended_action"
    ]
    confidence = structured_summary["confidence"]

    if not isinstance(policy_id, str):
        return _err(
            "permanent",
            False,
            "structured_summary.policy_id must be a string",
        )

    if not isinstance(root_cause, str):
        return _err(
            "permanent",
            False,
            "structured_summary.root_cause must be a string",
        )

    if not isinstance(candidate_claim_types, list):
        return _err(
            "permanent",
            False,
            "candidate_claim_types must be a list",
        )

    if not all(
        isinstance(item, str) and item in CLAIM_TYPES
        for item in candidate_claim_types
    ):
        return _err(
            "permanent",
            False,
            f"candidate_claim_types entries must be in {CLAIM_TYPES}",
        )

    if not isinstance(case_facts, dict):
        return _err(
            "permanent",
            False,
            "case_facts must be an object",
        )

    if not isinstance(recommended_action, str):
        return _err(
            "permanent",
            False,
            "recommended_action must be a string",
        )

    if (
        not isinstance(confidence, (int, float))
        or isinstance(confidence, bool)
    ):
        return _err(
            "permanent",
            False,
            "confidence must be a number in [0,1]",
        )

    normalized_confidence = float(confidence)

    if not 0.0 <= normalized_confidence <= 1.0:
        return _err(
            "permanent",
            False,
            "confidence must be a number in [0,1]",
        )

    record = {
        "claim_id": session.claim_id,
        "policy_id": policy_id,
        "reason": reason,
        "root_cause": root_cause,
        "candidate_claim_types": list(
            candidate_claim_types
        ),
        "case_facts": dict(case_facts),
        "recommended_action": recommended_action,
        "confidence": normalized_confidence,
        "case_facts_at_escalation": dict(
            session.case_facts
        ),
    }

    session.escalation = record

    escalation_path = (
        session.run_dir
        / "escalations.jsonl"
    )

    _append_jsonl(
        escalation_path,
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


# Type alias for clarity. The loop only sees a callable.
Executor = Any


def make_executor(
    session: ClaimSession,
) -> Executor:
    """Return a tool executor callable bound to the claim session."""

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
    ) as file_handle:
        file_handle.write(
            json.dumps(
                record,
                ensure_ascii=False,
            )
            + "\n"
        )