from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claims_intake.session import ClaimSession


CLAIM_TYPES = ["property_damage", "theft", "liability", "auto"]
SEVERITIES = ["low", "medium", "high"]


# ----------------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "lookup_policy",
        "description": (
            "Look up an insurance policy by policy ID. Call this early in the "
            "conversation, before classifying or routing the claim, to verify "
            "the policy and retrieve its coverage information."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "policy_id": {
                    "type": "string",
                    "description": "The claimant's policy identifier.",
                }
            },
            "required": ["policy_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_claim_fact",
        "description": (
            "Record one normalized fact about the incident. Call this whenever "
            "the claimant provides a useful claim detail such as incident_date, "
            "location, items_lost, estimated_loss, injuries, or vehicle_details. "
            "Record separate facts using separate tool calls."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "field": {
                    "type": "string",
                    "description": (
                        "Normalized fact name, such as incident_date, location, "
                        "items_lost, estimated_loss, or injuries."
                    ),
                },
                "value": {
                    "type": "string",
                    "description": "The normalized value of the claim fact.",
                },
            },
            "required": ["field", "value"],
            "additionalProperties": False,
        },
    },
    {
        "name": "classify_claim",
        "description": (
            "Commit the claim to its most likely claim type after enough facts "
            "have been collected. Include a confidence score from 0 to 1 and a "
            "brief rationale grounded in the available facts."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "claim_type": {
                    "type": "string",
                    "enum": CLAIM_TYPES,
                    "description": "The selected claim type.",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Classification confidence between 0 and 1.",
                },
                "rationale": {
                    "type": "string",
                    "description": "Why the available facts support this claim type.",
                },
            },
            "required": ["claim_type", "confidence", "rationale"],
            "additionalProperties": False,
        },
    },
    {
        "name": "assess_severity",
        "description": (
            "Commit the claim to a low, medium, or high severity bucket. Base "
            "the assessment on factors such as injuries, safety risk, financial "
            "loss, urgency, and extent of damage."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": SEVERITIES,
                    "description": "The assessed severity bucket.",
                },
                "rationale": {
                    "type": "string",
                    "description": "Why the available facts support this severity.",
                },
            },
            "required": ["severity", "rationale"],
            "additionalProperties": False,
        },
    },
    {
        "name": "request_clarification",
        "description": (
            "Ask the claimant one focused clarification question when two or "
            "more plausible interpretations remain and the ambiguity prevents "
            "reliable classification, severity assessment, or routing. Do not "
            "use this when the available facts are already sufficient."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "A concise clarification question for the claimant.",
                },
                "ambiguity_between": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                    "description": (
                        "At least two competing interpretations or claim types "
                        "that the answer will distinguish."
                    ),
                },
            },
            "required": ["question", "ambiguity_between"],
            "additionalProperties": False,
        },
    },
    {
        "name": "route_to_adjuster",
        "description": (
            "Route a fully classified and severity-assessed claim to the "
            "appropriate adjuster queue. This is a terminal tool. Call it only "
            "after classify_claim and assess_severity have succeeded and enough "
            "facts exist to provide a useful claim summary."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "queue": {
                    "type": "string",
                    "enum": CLAIM_TYPES,
                    "description": "The adjuster queue matching the claim type.",
                },
                "claim_summary": {
                    "type": "string",
                    "description": (
                        "A concise summary of the incident, important facts, "
                        "classification, and routing context."
                    ),
                },
            },
            "required": ["queue", "claim_summary"],
            "additionalProperties": False,
        },
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Escalate the claim to a human when it cannot be safely or reliably "
            "routed, such as when critical information is unavailable, policy "
            "details conflict, ambiguity remains, or confidence is too low. "
            "This is a terminal tool and requires a structured handoff summary."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why automated routing cannot safely continue.",
                },
                "structured_summary": {
                    "type": "object",
                    "properties": {
                        "policy_id": {"type": "string"},
                        "root_cause": {"type": "string"},
                        "candidate_claim_types": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": CLAIM_TYPES,
                            },
                        },
                        "case_facts": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                        "recommended_action": {"type": "string"},
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
                    "additionalProperties": False,
                },
            },
            "required": ["reason", "structured_summary"],
            "additionalProperties": False,
        },
    },
]


# ----------------------------------------------------------------------------
# Errors
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

def _t_lookup_policy(session: ClaimSession, inp: dict[str, Any]) -> str:
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
            f"policy not found: {policy_id}",
        )

    return _ok(policy)


def _t_record_claim_fact(
    session: ClaimSession,
    inp: dict[str, Any],
) -> str:
    field = inp.get("field")
    value = inp.get("value")

    if not isinstance(field, str):
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

    session.case_facts[field] = value

    return _ok(
        {
            "recorded": True,
            "field": field,
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
            f"claim_type must be one of: {', '.join(CLAIM_TYPES)}",
        )

    # bool is a subclass of int, so reject it explicitly.
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        return _err(
            "permanent",
            False,
            "confidence must be a number between 0 and 1",
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
            f"severity must be one of: {', '.join(SEVERITIES)}",
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
            "ambiguity_between must be a list with at least 2 entries",
        )

    session.clarifications_asked.append(
        {
            "question": question,
            "ambiguity_between": ambiguity_between,
        }
    )

    normalized_question = question.casefold()

    for key, reply in session.clarification_responses.items():
        if isinstance(key, str) and key.casefold() in normalized_question:
            return _ok({"claimant_reply": reply})

    return _ok({"claimant_reply": "NO_RESPONSE"})


def _t_route_to_adjuster(
    session: ClaimSession,
    inp: dict[str, Any],
) -> str:
    if session.terminal_called:
        return _err(
            "permanent",
            False,
            "a terminal tool has already been called",
        )

    queue = inp.get("queue")
    claim_summary = inp.get("claim_summary")

    if queue not in CLAIM_TYPES:
        return _err(
            "permanent",
            False,
            f"queue must be one of: {', '.join(CLAIM_TYPES)}",
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
            "claim must be classified before routing",
        )

    if session.severity is None:
        return _err(
            "permanent",
            False,
            "claim severity must be assessed before routing",
        )

    classification = session.classification
    severity = session.severity

    record = {
        "claim_id": session.claim_id,
        "policy_id": session.policy_id,
        "claim_type": classification["claim_type"],
        "severity": severity["severity"],
        "confidence": classification["confidence"],
        "rationale": classification["rationale"],
        "claim_summary": claim_summary,
        "case_facts": dict(session.case_facts),
    }

    session.routing = record

    _append_jsonl(
        Path("runs") / str(session.run) / "queues" / f"{queue}.jsonl",
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
            "a terminal tool has already been called",
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

    record = {
        "claim_id": session.claim_id,
        "policy_id": session.policy_id,
        "reason": reason,
        **structured_summary,
        "case_facts_at_escalation": dict(session.case_facts),
    }

    session.escalation = record

    _append_jsonl(
        Path("runs") / str(session.run) / "escalations.jsonl",
        record,
    )

    return _ok({"escalated": True})


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

    def execute(name: str, tool_input: dict[str, Any]) -> str:
        handler = _DISPATCH.get(name)

        if handler is None:
            return _err(
                "permanent",
                False,
                f"unknown tool: {name}",
            )

        try:
            return handler(session, tool_input)
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
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(record, ensure_ascii=False) + "\n"
        )