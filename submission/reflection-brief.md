# Reflection Brief — Harness Engineering Capstone

**Name:** Swetha Sundaresan 
**Date:** 2026-11-01

> **Submission status: Complete.** The final-stage starter TODOs were implemented, all four test suites pass, and the required scenarios and evidence artifacts are included. One System 1 fixture mismatch is reported honestly below: the kitchen-fire claim escalated although its expected outcome was routed.

**Environment**

- **Model(s):** System 1 used `claude-haiku-4-5-20251001`; System 2 completed a live model-backed run in WSL (the model identifier was not captured); System 4 used the recorded response fixture labelled `claude-sonnet-4-6`.
- **OS / Python:** Windows / Python 3.11.9 for tests; live model-backed runs were executed in WSL.
- **Approx. API spend:** Not reliably recorded. System 1's own run summary estimates $0.1474; System 2 records token counts but not a billing total.

---

## Part 1 — Per-system

### System 1 — Agentic loop

1. **Loop control.** The trace `system1/trace-claim_01_kitchen_fire.jsonl` records `tool_use → end_turn`. The continue/stop decision is in `claims_intake/loop.py::run`: `tool_use` appends tool results and continues, `end_turn` returns, and any other reason raises `UnexpectedStopReason`. All 30 tests passed (`system1/test.log`).

2. **Anti-pattern.** `test_antipatterns.py` statically rejects string-membership tests against assistant text as control flow; it also checks against a literal iteration cap and Python-side claim-type branching. Such string matching could misread ordinary claim text as a command instead of honoring the API's `stop_reason`. The 30-test pass is in `system1/test.log`; the completed run summary is `system1/summary.md`.

3. **Tool design.** `classify_claim` commits to a type and confidence; `escalate_to_human` is terminal and is described for unresolved ambiguity, low confidence, missing facts, or policy disputes. The distinct decision and terminal conditions help keep classification from being confused with escalation. Tool failures are serialized with `is_error`, `error_category`, `is_retryable`, and `message`, so the model can distinguish retryable failures from permanent ones; this behavior is defined in `claims_intake/tools.py` and covered by the passing suite (`system1/test.log`). The kitchen-fire trace shows `lookup_policy` and fact-recording tool calls, but not a structured error (`system1/trace-claim_01_kitchen_fire.jsonl`).

4. **Your numbers.** The kitchen-fire claim used 2 turns and cost an estimated $0.0085; the eight-claim run cost $0.1474 (`system1/summary.md`, run `20261101_081058`). Kitchen fire escalated although its fixture expected routing; the other seven claims matched their listed route/escalate expectations. Per-claim results vary with model responses and inputs, so I would investigate this escalation in the trace rather than assume the README sample must match.

### System 2 — Context strategy

5. **The reduction.** Run `20261101-103621` measured **38,708** raw transcript tokens and **16,856** assembled tokens, a **56.45% reduction** (`system2/budget.json`). The active issue remained the largest section at **15,789 tokens**; resolved refund and subscription sections were 427 and 454 tokens, and the compact Case Facts block was 204 tokens. This exceeds the rubric's 50% reduction target.

6. **Summarize vs preserve.** The run summarized resolved refund and subscription discussions into 427 and 454 tokens, retained a 204-token structured Case Facts block, and preserved the 15,789-token active payment-method conversation verbatim (`system2/budget.json`). The active issue stays exact because it contains current details that summaries could omit; resolved history is compressible because its conclusions can be represented compactly. The byte-exact active segment check and all 30 tests pass (`system2/test.log`).

7. **Facts block.** The full assembled context answered **6/6** questions (`system2/eval.jsonl`). In the Case-Facts-stripped control, Q1 (refund amount) still passed, but **Q6 regressed** because the exact `in_progress` status token was no longer present (`system2/eval_control.jsonl`). This demonstrates why compact structured facts supplement rather than replace the preserved active conversation.

### System 3 — Claude Code config

8. **Path-scoped rules.** The API rule declares `paths: ["src/api/**/*"]` (`system3/config_snapshot/.claude/rules/api.md`). This lets one cross-cutting convention apply to API handlers wherever they live, without placing narrower, duplicated `CLAUDE.md` files in directories. The final configuration suite passed all 35 tests (`system3/test.log`).

9. **Forked skill.** The skill frontmatter says `context: fork` and its `allowed-tools` list is read-only: `Read`, `Grep`, `Glob`, plus constrained `Bash` calls for Git/GitHub reads (`system3/config_snapshot/.claude/skills/deploy-check/SKILL.md`). The fork keeps verbose discovery output out of the parent session, while the allowlist prevents the check from modifying, pushing, or deploying. Without those boundaries, noisy intermediate output could pollute the main context and the skill could have an unnecessarily large write-capable blast radius. The validator returned `OK` (`system3/validator.log`).

10. **Scope.** Project-level configuration is tracked in `CLAUDE.md` and `.claude/`; `CLAUDE.md` imports modular standards with `@.claude/standards/...` references, and `.claude/commands/review.md` provides the project-scoped `/review` command (`system3/config_snapshot/CLAUDE.md`). User-level files under `~/.claude/` are personal and not version-controlled. The validator returned `OK` and the configuration suite passed all 35 tests (`system3/validator.log`, `system3/test.log`).

### System 4 — Orchestration

11. **Push work down.** The seeded warm tier contained **40** defects; the SQL-filtered query returned **17** newer than `2026-04-01T00:00:00Z` (`system4/shift-run.log`). `WarmStore.defects_since` runs `SELECT * FROM defects WHERE ts > ? ORDER BY ts DESC LIMIT ?`; the captured query plan uses `idx_defects_ts (ts>?)`, so the model receives the slice rather than the full history. The shift output confirms 17 new defects were analyzed.

12. **Crash recovery.** `shift_monitor/recovery.py::decide` resumes only an incomplete manifest whose latest step is no more than **30 minutes** old; empty, complete, or older manifests start fresh. The fresh path can inject saved findings as a summary instead of trusting a stale partial invocation. The 30-minute threshold test passed in the orchestration suite (`system4/test.log`); the successful shift output is in `system4/shift-run.log`.

13. **Small state and isolated forks.** The captured `hot_state.json` is **980 bytes**, below the 5,120-byte budget (`system4/shift-run.log`, `system4/hot_state.json`). A strict size bound keeps prompt growth predictable. For forked investigation, `shift_monitor/fork.py::fork_for_hypothesis` copies the same baseline into a separate directory for each hypothesis; each investigation writes to its own scratchpad, and only an explicit `merge_findings` appends selected findings to the main scratchpad. The independent-scratchpad and append-only merge tests passed (`system4/test.log`), so exploratory work does not mutate main state by default.

---

## Part 2 — Synthesis

14. **Three layers.** **Model:** the external Claude call and response contract are represented by `claims_intake/client.py`; the live run used Haiku as recorded in `system1/summary.md`. **Harness:** `claims_intake/loop.py::run` owns the stop-reason-driven loop; its suite passed 30 tests (`system1/test.log`) and the trace shows both stop reasons (`system1/trace-claim_01_kitchen_fire.jsonl`). **Orchestration:** `shift_monitor/pipeline.py::run_shift` filters warm-tier state, builds a prompt, updates bounded hot state, and appends the scratchpad; the recorded shift processed 17 defects (`system4/shift-run.log`).

15. **Deterministic vs prompt.** The deterministic boundary is `HotState.write_atomic`: it enforces the 5,120-byte limit and atomically replaces the state file; this run wrote 980 bytes (`system4/hot_state.json`, `system4/shift-run.log`). Prompt guidance is in `shift_monitor/invocation.py::rich`, which asks for a report and updated-state proposal; it guides model content but cannot guarantee correctness. The run demonstrates why hard invariants belong in code while judgments and recommendations belong in the prompt.

16. **Context, two faces.** System 2 manages context within a conversation: it reduced **38,708** transcript tokens to **16,856** assembled tokens (**56.45%**) by summarizing resolved segments while preserving the active issue (`system2/budget.json`). System 4 manages context across shifts: it queried **17 of 40** warm-tier defects and retained a **980-byte** hot state (`system4/shift-run.log`). Both keep decision-relevant information, but System 2 compresses prior turns for a single model context, while System 4 persists bounded state and queries a time-filtered slice between runs.

17. **Reliability you can't see in one run.** The loop anti-pattern tests statically inspect the source for string-based control flow and literal iteration caps—properties a single successful trace would not reveal. Those tests are included in the 30-pass result (`system1/test.log`). Catching regressions before shipping matters even though the captured run `20261101_081058` terminated as expected on `end_turn` (`system1/trace-claim_01_kitchen_fire.jsonl`).

18. **Blast radius.** In System 4, a bad recommendation could misdirect a production quality response; the recorded shift proposed quarantining a lot and taking a test station out of service (`system4/shift-run.log`). Hypothesis forks start from copied state in separate directories and cannot affect the main scratchpad unless the operator explicitly merges findings (`shift_monitor/fork.py`; isolation tests in `system4/test.log`). The runner also writes bounded hot state, while a human can review recommendations before operational action. Atomic replacement and the byte-budget check limit state corruption, not the impact of an accepted recommendation.

---

## Part 3 — Honest assessment

19. **What broke.** The machine initially had Python 3.10.11 while the projects require at least 3.11; installing Python 3.11.9 fixed that. On Windows, repo-local venv installs for Systems 2 and 4 hit the legacy 260-character path limit in Anthropic SDK filenames; successful retries use short-path venvs under `E:\harness_engineering\venvs\` (`system2/setup.log`, `system4/setup.log`). System 2's WSL-generated UTF-8 `context.md` initially failed a Windows test because default text decoding used `cp1252`; the writer and byte-exact reader now explicitly use UTF-8, and the suite passes 30 tests (`system2/test.log`).

20. **What you'd change.** I would add a documented recorded-response backend to Systems 1 and 2, analogous to System 4's offline response path, so the artifact pipeline and output schemas can also be validated deterministically without credentials. The model-backed scenarios here did run: System 1 processed all eight claims and System 2 completed its 6/6 evaluation (`system1/summary.md`, `system2/eval.jsonl`). System 4's recorded-response shift produced 17 filtered defects and a 980-byte state (`system4/shift-run.log`).
