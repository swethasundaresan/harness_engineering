"""The agentic loop.

The defining contract:
- Control flow is driven by `response.stop_reason`.
- Loop continues iff stop_reason == "tool_use".
- Loop returns iff stop_reason == "end_turn".
- Any other stop_reason raises UnexpectedStopReason.

No string-membership tests against assistant text drive control flow here.
No integer-literal iteration cap is the primary stopping mechanism.
A Budget (token + wall-clock, sourced from config) is the safety net and raises
BudgetExceeded if hit. It never silently truncates.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from claims_intake.budget import Budget
from claims_intake.tracer import Tracer


class UnexpectedStopReason(Exception):
    """Raised when the model returns an unsupported stop reason."""

    pass


ToolExecutor = Callable[[str, dict[str, Any]], str]
"""Takes (tool_name, tool_input) and returns the tool_result content as a string.

Errors are returned as a serialized JSON string with is_error=true;
they are never raised by the executor.
"""


class MessagesClient(Protocol):
    """Protocol for the messages client used by the agent loop."""

    def create(self, **kwargs: Any) -> Any: ...


@dataclass
class FinalState:
    """Final state returned after the model completes its turn."""

    messages: list[dict[str, Any]]
    total_input_tokens: int
    total_output_tokens: int
    turn_count: int
    final_content: list[Any] = field(default_factory=list)


def run(
    *,
    client: Any,
    model: str,
    system: str,
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    tool_executor: ToolExecutor,
    budget: Budget,
    tracer: Tracer,
    max_tokens: int = 4096,
) -> FinalState:
    """Run the agentic loop until the model returns stop_reason == "end_turn".

    Control flow is determined exclusively by response.stop_reason.

    - "tool_use": execute all requested tools and continue.
    - "end_turn": return the final state.
    - anything else: raise UnexpectedStopReason.

    There is deliberately no fixed iteration count. Budget provides the
    token and wall-clock safety mechanism.
    """

    working_messages = list(messages)

    turn = 0
    total_input = 0
    total_output = 0

    while True:
        turn += 1

        # Budget is the safety mechanism instead of a fixed iteration cap.
        budget.check()

        t0 = time.monotonic()

        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            tools=tools,
            messages=working_messages,
        )

        latency_ms = (time.monotonic() - t0) * 1000.0

        # Track token usage.
        input_tokens = int(response.usage.input_tokens)
        output_tokens = int(response.usage.output_tokens)

        total_input += input_tokens
        total_output += output_tokens

        budget.record_input_tokens(input_tokens)

        # Collect all tool calls for tracing.
        tool_calls = [
            {
                "id": block.id,
                "name": block.name,
                "input": dict(block.input),
            }
            for block in response.content
            if getattr(block, "type", None) == "tool_use"
        ]

        # Record the model turn.
        tracer.write(
            {
                "turn": turn,
                "stop_reason": response.stop_reason,
                "tool_calls": tool_calls,
                "latency_ms": round(latency_ms, 1),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
        )

        # -------------------------------------------------------------
        # Case 1: model completed normally
        # -------------------------------------------------------------
        if response.stop_reason == "end_turn":
            working_messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                }
            )

            return FinalState(
                messages=working_messages,
                total_input_tokens=total_input,
                total_output_tokens=total_output,
                turn_count=turn,
                final_content=list(response.content),
            )

        # -------------------------------------------------------------
        # Case 2: model requested one or more tools
        # -------------------------------------------------------------
        if response.stop_reason == "tool_use":
            working_messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                }
            )

            tool_results: list[dict[str, Any]] = []

            # Execute every tool requested in this assistant turn.
            for block in response.content:
                if getattr(block, "type", None) != "tool_use":
                    continue

                result_content = tool_executor(
                    block.name,
                    dict(block.input),
                )

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_content,
                    }
                )

            # All tool results from this assistant turn must be returned
            # together in a single user turn.
            working_messages.append(
                {
                    "role": "user",
                    "content": tool_results,
                }
            )

            continue

        # -------------------------------------------------------------
        # Case 3: unsupported stop reason
        # -------------------------------------------------------------
        raise UnexpectedStopReason(
            f"turn {turn}: "
            f"unexpected stop_reason={response.stop_reason!r}"
        )