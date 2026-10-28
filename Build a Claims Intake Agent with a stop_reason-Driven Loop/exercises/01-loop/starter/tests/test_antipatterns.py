"""Anti-pattern audit.

Verifies, by static AST analysis, that the agentic loop does NOT:
- use string-membership tests against text content to drive control flow
- use an integer-literal iteration cap as its primary stopping mechanism
- omit reference to `stop_reason` as the loop-breaking signal

And that the package broadly does not branch on `claim_type` equality
outside of the tool-schema definitions and the cost-estimate module.

Each test parses the relevant file with `ast` and walks the tree. There are
no runtime imports of claims_intake here.
"""

from __future__ import annotations

import ast
from pathlib import Path


PKG = Path(__file__).resolve().parents[1] / "claims_intake"
LOOP_PY = PKG / "loop.py"


def _parse(path: Path) -> ast.Module:
    return ast.parse(
        path.read_text(encoding="utf-8"),
        filename=str(path),
    )


# ---------------------------------------------------------------------------
# Anti-pattern 1
# ---------------------------------------------------------------------------


def test_no_string_membership_against_text_in_loop() -> None:
    """No string-literal membership checks are used in loop.py."""

    tree = _parse(LOOP_PY)
    offenders: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue

        has_in_operator = any(
            isinstance(op, ast.In)
            for op in node.ops
        )

        left_is_string = (
            isinstance(node.left, ast.Constant)
            and isinstance(node.left.value, str)
        )

        if has_in_operator and left_is_string:
            offenders.append(ast.unparse(node))

    assert not offenders, (
        "String-membership tests against model output are not allowed. "
        f"Offending expressions: {offenders}"
    )


# ---------------------------------------------------------------------------
# Anti-pattern 2
# ---------------------------------------------------------------------------


def test_no_integer_literal_iteration_cap_in_loop() -> None:
    """No integer-literal loop cap is used as the stopping mechanism."""

    tree = _parse(LOOP_PY)
    offenders: list[str] = []

    for node in ast.walk(tree):

        # Detect:
        # for ... in range(<integer literal>)
        if isinstance(node, ast.For):
            iterator = node.iter

            if (
                isinstance(iterator, ast.Call)
                and isinstance(iterator.func, ast.Name)
                and iterator.func.id == "range"
            ):
                has_integer_literal = any(
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, int)
                    and not isinstance(arg.value, bool)
                    for arg in iterator.args
                )

                if has_integer_literal:
                    offenders.append(ast.unparse(node))

        # Detect:
        # while something < <integer literal>
        if isinstance(node, ast.While):
            test = node.test

            if isinstance(test, ast.Compare):
                has_integer_on_right = any(
                    isinstance(comparator, ast.Constant)
                    and isinstance(comparator.value, int)
                    and not isinstance(comparator.value, bool)
                    for comparator in test.comparators
                )

                if has_integer_on_right:
                    offenders.append(ast.unparse(node))

    assert not offenders, (
        "Integer-literal iteration caps are not allowed; "
        "use a Budget instead. "
        f"Offending loops: {offenders}"
    )


# ---------------------------------------------------------------------------
# Positive evidence
# ---------------------------------------------------------------------------


def test_stop_reason_is_loop_control() -> None:
    """stop_reason exists and controls exit from a while loop."""

    tree = _parse(LOOP_PY)

    has_stop_reason = any(
        (
            isinstance(node, ast.Attribute)
            and node.attr == "stop_reason"
        )
        or (
            isinstance(node, ast.Name)
            and node.id == "stop_reason"
        )
        for node in ast.walk(tree)
    )

    assert has_stop_reason, (
        "loop.py must reference stop_reason."
    )

    loop_exits_on_stop_reason = False

    for node in ast.walk(tree):
        if not isinstance(node, ast.While):
            continue

        body_text = "\n".join(
            ast.unparse(statement)
            for statement in node.body
        )

        if (
            "stop_reason" in body_text
            and (
                "return" in body_text
                or "raise" in body_text
            )
        ):
            loop_exits_on_stop_reason = True
            break

    assert loop_exits_on_stop_reason, (
        "A while loop must use stop_reason and exit "
        "through return or raise."
    )


# ---------------------------------------------------------------------------
# Decision-tree-in-Python audit
# ---------------------------------------------------------------------------


def test_no_claim_type_equality_branching_in_package() -> None:
    """Claim-type decisions should live in model/tool interactions."""

    offenders: list[str] = []

    excluded_files = {
        "tools.py",
        "pricing.py",
        "__init__.py",
    }

    for path in PKG.rglob("*.py"):

        if path.name in excluded_files:
            continue

        tree = _parse(path)

        for node in ast.walk(tree):

            if not isinstance(node, ast.Compare):
                continue

            left_is_claim_type = (
                isinstance(node.left, ast.Name)
                and node.left.id == "claim_type"
            ) or (
                isinstance(node.left, ast.Attribute)
                and node.left.attr == "claim_type"
            )

            if not left_is_claim_type:
                continue

            has_equality_operator = any(
                isinstance(op, ast.Eq)
                for op in node.ops
            )

            compared_against_string = any(
                isinstance(comparator, ast.Constant)
                and isinstance(comparator.value, str)
                for comparator in node.comparators
            )

            if (
                has_equality_operator
                and compared_against_string
            ):
                offenders.append(
                    f"{path.name}:{node.lineno}: "
                    f"{ast.unparse(node)}"
                )

    assert not offenders, (
        "Claim-type branching should be moved into the model "
        "via tool calls. "
        f"Offending expressions: {offenders}"
    )