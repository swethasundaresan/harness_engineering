# Reflection Brief — Harness Engineering Capstone

**Name:** Not provided  
**Date:** 2026-11-01

> **Submission status: PARTIAL.** The final-stage starter TODOs were implemented and tests were rerun from the modified `starter/` directories. System 1 has now completed a live run. System 2 still cannot make model calls because no valid API key or authenticated `claude` CLI is available; its failed attempt is retained and no model-generated budget or eval result is claimed.

**Environment**

- **Model(s):** System 1 used `claude-haiku-4-5-20251001`; System 4 used the recorded response fixture labelled `claude-sonnet-4-6`. System 2's live model call remains blocked.
- **OS / Python:** Windows / Python 3.11.9
- **Approx. API spend:** $0

---

## Part 1 — Per-system

### System 1 — Agentic loop

1. **Loop control.** The trace `system1/trace-claim_01_kitchen_fire.jsonl` records `tool_use → end_turn`. The continue/stop decision is in `claims_intake/loop.py::run`: `tool_use` appends tool results and continues, `end_turn` returns, and any other reason raises `UnexpectedStopReason`. All 30 tests passed (`system1/test.log`).

2. **Anti-pattern.** `test_antipatterns.py` statically rejects string-membership tests against assistant text as control flow; it also checks against a literal iteration cap and Python-side claim-type branching. Such string matching could misread ordinary claim text as a command instead of honoring the API's `stop_reason`. The 30-test pass is in `system1/test.log`; the completed run summary is `system1/summary.md`.

3. **Tool design.** `classify_claim` commits to a type and confidence; `escalate_to_human` is terminal and is described for unresolved ambiguity, low confidence, missing facts, or policy disputes. The distinct decision and terminal conditions help keep classification from being confused with escalation. Tool failures are serialized with `is_error`, `error_category`, `is_retryable`, and `message`, so the model can distinguish retryable failures from permanent ones; this behavior is defined in `claims_intake/tools.py` and covered by the passing suite (`system1/test.log`). The kitchen-fire trace shows `lookup_policy` and fact-recording tool calls, but not a structured error (`system1/trace-claim_01_kitchen_fire.jsonl`).

4. **Your numbers.** The kitchen-fire claim used 2 turns and cost an estimated $0.0085; the eight-claim run cost $0.1474 (`system1/summary.md`, run `20261101_081058`). Kitchen fire escalated although its fixture expected routing; the other seven claims matched their listed route/escalate expectations. Per-claim results vary with model responses and inputs, so I would investigate this escalation in the trace rather than assume the README sample must match.

### System 2 — Context strategy

5. **The reduction.** This run measured a raw transcript baseline of **47,144 tokens** before the case-facts request failed (`system2/scenario-attempt.log`, run ID `20261101-125042`). No assembled context or `budget.json` was produced, so I cannot report assembled tokens, reduction percentage, or the largest measured section. The design keeps the active issue verbatim, but that is not a measurement from this run.

6. **Summarize vs preserve.** The intended rule is to summarize resolved issue segments and preserve the active issue byte-exact, with case facts retained as a compact structured block. This run produced no per-section token counts because model access failed during case-facts extraction (`system2/scenario-attempt.log`). The final test log records 28 passed and 2 artifact-dependent skips (`system2/test.log`), so the token trade-off still needs a successful run.

7. **Facts block.** I cannot identify a regressing question: neither `eval.jsonl` nor `eval_control.jsonl` was generated. The run failed before evaluation because no inference backend was available (`system2/scenario-attempt.log`); the two skipped tests are visible in `system2/test.log`. Re-run with model access to compare the full and control variants.

### System 3 — Claude Code config

8. **Path-scoped rules.** The API rule declares `paths: ["src/api/**/*"]` (`system3/config_snapshot/.claude/rules/api.md`). This lets one cross-cutting convention apply to API handlers wherever they live, without placing narrower, duplicated `CLAUDE.md` files in directories. The final configuration suite passed all 35 tests (`system3/test.log`).

9. **Forked skill.** The skill frontmatter says `context: fork` and its `allowed-tools` list is read-only: `Read`, `Grep`, `Glob`, plus constrained `Bash` calls for Git/GitHub reads (`system3/config_snapshot/.claude/skills/deploy-check/SKILL.md`). The fork keeps verbose discovery output out of the parent session, while the allowlist prevents the check from modifying, pushing, or deploying. Without those boundaries, noisy intermediate output could pollute the main context and the skill could have an unnecessarily large write-capable blast radius. The validator returned `OK` (`system3/validator.log`).

10. **Scope.** Project-level configuration is tracked in `CLAUDE.md` and `.claude/` (for example, `.claude/commands/review.md`); the config documents user-level files under `~/.claude/`, which are personal and not version-controlled (`system3/config_snapshot/CLAUDE.md`). This separation is reflected in the final suite and validator output (`system3/test.log`, `system3/validator.log`).

### System 4 — Orchestration

11. **Push work down.** The seeded warm tier contained **40** defects; the SQL-filtered query returned **17** newer than `2026-04-01T00:00:00Z` (`system4/shift-run.log`). `WarmStore.defects_since` runs `SELECT * FROM defects WHERE ts > ? ORDER BY ts DESC LIMIT ?`; the captured query plan uses `idx_defects_ts (ts>?)`, so the model receives the slice rather than the full history. The shift output confirms 17 new defects were analyzed.

12. **Crash recovery.** `shift_monitor/recovery.py::decide` resumes only an incomplete manifest whose latest step is no more than **30 minutes** old; empty, complete, or older manifests start fresh. The fresh path can inject saved findings as a summary instead of trusting a stale partial invocation. The 30-minute threshold test passed in the orchestration suite (`system4/test.log`); the successful shift output is in `system4/shift-run.log`.

13. **Small state.** The captured `hot_state.json` is **980 bytes**, below the 5,120-byte budget (`system4/shift-run.log`, `system4/hot_state.json`). A strict size bound matters when each shift reuses this state indefinitely: it keeps prompt growth predictable and avoids carrying an ever-expanding history. `HotState.write_atomic` also rejects oversized payloads before replacing the file.

---

## Part 2 — Synthesis

14. **Three layers.** **Model:** the external Claude call and response contract are represented by `claims_intake/client.py`; the live run used Haiku as recorded in `system1/summary.md`. **Harness:** `claims_intake/loop.py::run` owns the stop-reason-driven loop; its suite passed 30 tests (`system1/test.log`) and the trace shows both stop reasons (`system1/trace-claim_01_kitchen_fire.jsonl`). **Orchestration:** `shift_monitor/pipeline.py::run_shift` filters warm-tier state, builds a prompt, updates bounded hot state, and appends the scratchpad; the recorded shift processed 17 defects (`system4/shift-run.log`).

15. **Deterministic vs prompt.** The deterministic boundary is `HotState.write_atomic`: it enforces the 5,120-byte limit and atomically replaces the state file; this run wrote 980 bytes (`system4/hot_state.json`, `system4/shift-run.log`). Prompt guidance is in `shift_monitor/invocation.py::rich`, which asks for a report and updated-state proposal; it guides model content but cannot guarantee correctness. The run demonstrates why hard invariants belong in code while judgments and recommendations belong in the prompt.

16. **Context, two faces.** System 2 manages context inside a conversation: this attempt measured a 47,144-token raw baseline but could not assemble the compressed context (`system2/scenario-attempt.log`). System 4 manages context across shifts by retaining bounded hot state: **980 bytes** after processing **17 of 40** defects (`system4/shift-run.log`). The shared principle is to keep only decision-relevant information; the mechanism differs—summarize/prune conversation history within a run versus persist a compact state and query a time-filtered slice between runs. System 2’s reduction percentage remains unmeasured.

17. **Reliability you can't see in one run.** The loop anti-pattern tests statically inspect the source for string-based control flow and literal iteration caps—properties a single successful trace would not reveal. Those tests are included in the 30-pass result (`system1/test.log`). Catching regressions before shipping matters even though the captured run `20261101_081058` terminated as expected on `end_turn` (`system1/trace-claim_01_kitchen_fire.jsonl`).

18. **Blast radius.** In System 4, a bad recommendation could misdirect a production quality response; the recorded shift proposed quarantining a lot and taking a test station out of service (`system4/shift-run.log`). The runner writes only bounded hot state and a scratchpad, while the human can stop invoking the shift runner or hold recommendations for review before operational action. Atomic state replacement and the byte-budget check limit state corruption, not the impact of an accepted recommendation.

---

## Part 3 — Honest assessment

19. **What broke.** The machine initially had Python 3.10.11 while the projects require at least 3.11; installing Python 3.11.9 fixed that. On Windows, repo-local venv installs for Systems 2 and 4 hit the legacy 260-character path limit in Anthropic SDK filenames; their successful retries use project-specific short-path venvs under `E:\harness_engineering\venvs\` (`system2/setup.log`, `system4/setup.log`). System 1 is now run successfully as documented in `system1/summary.md`; System 2 still needs working credentials (`system2/scenario-attempt.log`).

20. **What you'd change.** I would add a documented recorded-response backend to Systems 1 and 2, analogous to System 4's offline response path, so the complete artifact pipeline and output schemas can be validated without credentials. System 4's recorded-response shift produced a real run artifact with 17 filtered defects and a 980-byte state (`system4/shift-run.log`). The model-backed results would still need a separately authenticated run before claiming production behavior.
