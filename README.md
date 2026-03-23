# BoggersBrain

**BoggersBrain** is a single-file, dependency-free research substrate: a **closed-loop dynamical system** that couples a small recurrent **graph** (four typed nodes) to a **scalar file environment**, minimizes a composite **tension** signal, and can **sandbox**, **audit**, and optionally **commit** self-modifications—including restricted **`exec`** of graph mutations and **multi-environment** / **real-sensor** extensions.

Repository: [github.com/BoggersTheFish/BoggersBrain](https://github.com/BoggersTheFish/BoggersBrain)

---

## Why this exists (and who it is for)

Most “agentic” or self-modifying systems lean on large learned models and opaque stacks. BoggersBrain is deliberately **small, inspectable, and deterministic enough to reason about**:

- **No neural networks, no gradients, no external ML libraries** — only Python’s standard library (`math`, `random`, `time`, `copy`, etc.).
- **Everything is one module** (`closed_loop_control.py`) so the full behavior is auditable in one place.
- **Objective-first design**: prediction error, goal error, internal mismatch, and overactivation feed a single **tension** scalar; the loop always optimizes that signal (with novelty shaping), not a hidden reward hack.
- **Safety-by-construction for self-mod**: structural changes (edges, novelty scale, action deltas, spawned shadow graphs) are evaluated in **sandboxes** over a fixed **internal horizon** (20 steps by default). A change **commits only if** the long-horizon statistics improve under explicit rules, and **code-like** mutations can require a **human prompt** or **`CODE_EMISSION_AUTO=y`**.

That makes it useful for:

- **Research**: experimenting with “tension,” symbols, drift, and self-modification without training infrastructure.
- **Pedagogy**: teaching closed-loop control, graph dynamics, and conservative self-modification contracts.
- **Prototyping**: a testbed for audit logs, multi-environment generalisation, and restricted `exec` before moving to heavier tooling.

---

## What it does (high level)

1. **Sense** a scalar **control value** from disk (`control_value.txt` or `control_value_2.txt` depending on `env_id`).
2. **Encode** it (plus target context) into a 16-D vector and **inject** into the **Sensor** node.
3. **Propagate** activity along weighted **edges** with relaxation; **Meta** injects summary features (density, recent tension, etc.).
4. **Plan** the next **action** in `{+1, −1, ×0.99}` on the scalar by comparing **predicted tension** for each option (hybrid real vs model rollout with drift handling).
5. **Act** on the file, **measure** real prediction error and **tension**, update **edges** from the objective, and maintain **online predictors** for additive and multiplicative dynamics.
6. **Discover symbols** (repeated action subsequences) when both **real** and **model** rollouts beat naive execution—capped by `MAX_SYMBOLS`.
7. **Self-mod** only inside **sandbox** simulations (`maybe_mutate_sandbox_only`), committing a single edge tweak if mean **and** variance of tension over the sandbox horizon improve.
8. **Vibe-code** (`maybe_vibe_code`): periodic proposals as **Python callables** on a **shadow graph**; commit only if internal-wave mean **and** variance improve; full **audit** with `ENV=` tags.
9. **Code emission** (`maybe_emit_code`): restricted **`exec`** strings with a **strict gate** (production: ratio thresholds; demo mode: vibe-style or distributed-specific rules); optional **human** or **`CODE_EMISSION_AUTO`** commit; audit trail.
10. **Phase 5**: **real sensors** (wall clock + optional `external_event.txt`) blended into the sensor vector with configurable **`sensor_blend_weight`** (default **0.3**); **distributed** proposals append **child graphs** and score an **ensemble** internal-wave metric.
11. **Emergent goals** (`maybe_invent_goal`): when real-wave **tension** has been **too calm** for long enough (low mean and variance over a sliding window), the system proposes **small, sandbox-safe** target changes—**nudge toward plant**, **micro** / **incremental** bumps or trims, optional **compound** symbol append. Proposals are scored with the same **`internal_wave`** horizon as other emissions. **Strict** gate: trial mean/var must beat baseline by **`EMERGENT_GATE_MEAN_RATIO` / `EMERGENT_GATE_VAR_RATIO`** (defaults **0.95** / **0.9**). Set **`EMERGENT_RELAX_GATE=y`** for a slightly looser exploration gate (still logged). Successful commits **`write_target()`** so `control_target.txt` stays in sync.

---

## Architecture (minimal map)

| Node ID | Role (conceptual) |
|--------:|-------------------|
| 0 | **Sensor** — encoded scalar + (Phase 5) real-world blend |
| 1 | **Prediction** |
| 2 | **Motor** — action selection pressure |
| 3 | **Meta** — graph statistics & tension context |

Edges are directed; weights adapt from the **objective** (`reinforce_edges`). The **Graph** also stores **symbols**, **action history**, **tension history**, **prediction-error EMA/trend**, **action deltas** and **scale factor** for the hybrid predictor, **`novelty_scale`**, **`distributed_graphs`** (Phase 5), and **`sensor_blend_weight`**.

The **`ControlSystem`** owns the **`Graph`**, **`SensorEncoder`**, **`real_sensors`** callables, environment paths (`control_path()`), wave counter, drift flags, and commit/rollback counters (`commits`, `rollbacks`, `vibe_*`, `code_emit_*`, `emergent_goal_*`).

---

## Phases (as implemented in code)

| Phase | Idea |
|------:|------|
| **Core loop** | File-backed scalar environment; tension; hybrid planning; online delta/scale learning. |
| **Symbols** | Reusable action patterns with dual validation (real + model). |
| **Sandbox self-mod** | Edge mutations only after sandbox mean **and** variance improve. |
| **Vibe-code** | Callable proposals on shadow graph; `VIBE_INTERVAL` waves; `vibe_code_audit.log`. |
| **Multi-env (scaling C)** | Two files, `env_id`, `run_scaling_test()`, ENV-tagged audits. |
| **Code emission (B)** | Restricted `exec`; human or `CODE_EMISSION_AUTO`; `CODE_EMISSION_*` env tuning. |
| **Phase 5** | Real sensors + `distributed_graphs` + distributed sandbox scoring + occasional spawn proposals. |
| **Emergent goals** | When tension is “too stable,” refined target proposals + sandbox; optional **`EMERGENT_RELAX_GATE`**. |

---

## Files in this repo

| File | Purpose |
|------|---------|
| `closed_loop_control.py` | **Entire implementation** — run this. |
| `control_value.txt` | Primary scalar **plant** state (read/written each wave). |
| `control_value_2.txt` | Second scalar channel for multi-environment tests. |
| `control_target.txt` | Goal scalar for the controller. |
| `external_event.txt` | Optional **Phase 5** external scalar (created if missing). |
| `vibe_code_audit.log` | **Append-only** audit (proposals, commits, rollbacks, `ENV=`, code emission, **`EMERGENT_GOAL_*`** lines). Ignored by git (regenerates). |

---

## Requirements

- **Python 3.10+** recommended (uses `from __future__ import annotations` and modern typing).

No `pip install` is required for core operation.

---

## How to run

### Default entry point

```bash
python closed_loop_control.py
```

Runs **`run_scaling_test`** (target 500, 1000 waves per environment, two envs, quiet mode for waves).

### Single episode helper

From Python or a small script, call `run_episode(waves, seed, initial_value, target, quiet=...)`.

### Phase 5 + code emission + emergent goals (example)

PowerShell:

```powershell
$env:CODE_EMISSION_DEMO = "y"
$env:CODE_EMISSION_AUTO = "y"
$env:CODE_EMISSION_INTERVAL = "50"
# Optional: loosen emergent sandbox gate slightly for exploration demos (still audited)
$env:EMERGENT_RELAX_GATE = "y"
python closed_loop_control.py
```

Optional: write numbers to `external_event.txt` while the process runs to exercise the **file sensor**.

---

## Environment variables (reference)

| Variable | Effect |
|----------|--------|
| `CODE_EMISSION_DEMO` | Enables demo-style gates / proposal scaling for emissions (see source). |
| `CODE_EMISSION_AUTO` | `y` / `1` / `yes` — auto-accept emission when sandbox gate passes (non-interactive). |
| `CODE_EMISSION_INTERVAL` | Waves between emission attempts (default 200). |
| `CODE_EMISSION_GATE_MEAN`, `CODE_EMISSION_GATE_VAR` | Override production ratio gate factors. |
| `CODE_EMISSION_DELTA_MULT`, `CODE_EMISSION_NOVELTY_MULT`, `CODE_EMISSION_META_W` | Tune proposal strengths. |
| `EMERGENT_RELAX_GATE` | `y` / `1` / `yes` — use a looser emergent-goal gate (exploration); audit logs `emergent_relax=True`. |

**Key constants** (edit in `closed_loop_control.py`): `EMERGENT_GOAL_INTERVAL` (default **400**), `EMERGENT_STABLE_*` (tension “boredom” detection), `EMERGENT_GATE_MEAN_RATIO` / `EMERGENT_GATE_VAR_RATIO`, `DISTRIBUTED_EMISSION_PROB` (**0.35**), `REAL_SENSOR_INTERVAL` (**50**).

Vibe and mutation intervals are **constants** at the top of `closed_loop_control.py` (`VIBE_INTERVAL`, `MUTATION_EVERY`, etc.).

---

## Safety and audit model

- **Sandboxes** never perform irreversible writes to control files during evaluation of a candidate mutation.
- **Commits** (edge mutation, vibe callable, `exec` diff) happen only after **recorded** baseline vs trial metrics pass the gate.
- **Audit log** lines include timestamps, **`ENV=`** for environment-aware proposals, **`phase5_distributed=`** for emission type, **`EMERGENT_GOAL_*`** for emergent goal proposals/commits/rollbacks, and rollback reasons.

This is **not** a substitute for OS-level isolation: restricted `exec` is still `exec`; Phase 5 documentation in code assumes trusted use. For untrusted proposals, run in a container or subprocess sandbox (future work).

---

## Limitations (honest)

- **Single process**, single main graph; **distributed** children are stored and scored in emission sandbox; live `wave_step` does not yet run a full coupled multi-graph simulation.
- **Scalar plant** is intentionally tiny; scaling to rich sensors is API-sized, not production robotics.
- **Tuning** (intervals, gates) affects how often commits occur; conservative defaults favor **no change** near a good attractor.
- **Emergent goals**: large random target jumps fail the sandbox by design (tension spikes). **Small** nudges and **relaxed** gate mode are needed to observe occasional commits in practice.

---

## Contributing / license

Issues and PRs can target: clearer modular splits (still optional), stronger sandbox isolation, or richer sensors—without breaking the “readable single file” story.

If you add a license file, pick one explicitly; this README does not impose one by default.

---

## Acknowledgement

Design and iteration history are documented in commit messages and in `vibe_code_audit.log` on your machine (not committed—regenerated each run).

**BoggersBrain** — *tension low, edge open.*
