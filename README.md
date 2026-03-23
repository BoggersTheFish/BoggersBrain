# BoggersBrain

**BoggersBrain** is a single-file research substrate: a **closed-loop dynamical system** that couples a small recurrent **graph** (four typed nodes) to a **scalar file environment**, minimizes a composite **tension** signal, and can **sandbox**, **audit**, and optionally **commit** self-modifications—including restricted **`exec`** of graph mutations, **multi-environment** / **real-sensor** extensions, **persistent checkpoints**, **screen-based vision symbols**, **gated desktop embodiment**, and **sandboxed self-feature proposals**.

Repository: [github.com/BoggersTheFish/BoggersBrain](https://github.com/BoggersTheFish/BoggersBrain)

---

## Why this exists (and who it is for)

Most “agentic” or self-modifying systems lean on large learned models and opaque stacks. BoggersBrain is deliberately **small, inspectable, and deterministic enough to reason about**:

- **Core loop has no neural networks, no gradients, no external ML libraries** — only Python’s standard library (`math`, `random`, `time`, `copy`, etc.) for the cognitive substrate.
- **Optional extras** (see [Requirements](#requirements)): **Pillow** + **PyAutoGUI** + **Tkinter** enable screenshot hashing and **human-gated** mouse/keyboard actions; nothing moves without an explicit **Yes** in a dialog.
- **Everything lives in one module** (`closed_loop_control.py`) so behavior is auditable in one place.
- **Objective-first design**: prediction error, goal error, internal mismatch, and overactivation feed a single **tension** scalar; the loop optimizes that signal (with novelty shaping), not a hidden reward hack.
- **Safety-by-construction for self-mod**: structural changes are evaluated in **sandboxes** over fixed **internal horizons**. A change **commits only if** long-horizon statistics improve under explicit rules, and **code-like** mutations can require a **human prompt** or **`CODE_EMISSION_AUTO=y`**.

That makes it useful for:

- **Research**: experimenting with tension, symbols, drift, checkpoints, vision, and self-modification without training infrastructure.
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
11. **Emergent goals** (`maybe_invent_goal`): when real-wave **tension** has been **too calm** for long enough, the system proposes **small, sandbox-safe** target changes. **Strict** gate: trial mean/var must beat baseline by configurable ratios. Set **`EMERGENT_RELAX_GATE=y`** for a slightly looser exploration gate (still logged). Successful commits **`write_target()`** so `control_target.txt` stays in sync.
12. **Hierarchical planning + reflection** (`maybe_hierarchical_plan`): periodic reflection strings and multi-line **`exec`** proposals on the graph, evaluated on a longer sandbox horizon (`HIERARCHICAL_SANDBOX_STEPS`); same demo vs production gate pattern as code emission; optional **`CODE_EMISSION_AUTO`** for commit.
13. **Persistent checkpoint** (`save_checkpoint` / `load_checkpoint`): serialises graph + loop state to **`brain_checkpoint.json`** (gitignored) so runs can resume across restarts. Disable with **`BRAIN_CHECKPOINT=0`**.
14. **Safe embodiment** (`safe_embodiment_action`): optional **Tk** confirmation for each proposed **PyAutoGUI** action (move / click / type test string). **Off** unless **`BRAIN_EMBODIMENT=y`**. Every action is logged to **`vibe_code_audit.log`**; separate **`emb_c` / `emb_r`** counters.
15. **Vision-driven symbols** (`maybe_create_vision_symbol`): periodic **screenshot hashes** (Pillow `ImageGrab`) detect stable frames; if a sandbox-style compression check passes, a **vision symbol** is stored as an `List[int]` pattern (distinct from actions `0–2`) and audited. **`BRAIN_VISION_SYMBOLS=0`** disables. **`vis_sym`** counts formations.
16. **Self-feature proposals** (`maybe_propose_feature`): vision-tagged **`exec`** lines that mutate the **`ControlSystem`** (extra clock sensor, macro symbol, novelty tighten, distributed child). Evaluated with **`internal_wave`** on a **deep-copied** controller (`FEATURE_SANDBOX_STEPS`). Same gate style as hierarchical / emission. **`BRAIN_SELF_FEATURE=y`** to enable. **`feat_c` / `feat_r`** counters; checkpointed.

---

## Architecture (minimal map)

| Node ID | Role (conceptual) |
|--------:|-------------------|
| 0 | **Sensor** — encoded scalar + (Phase 5) real-world blend |
| 1 | **Prediction** |
| 2 | **Motor** — action selection pressure |
| 3 | **Meta** — graph statistics & tension context |

Edges are directed; weights adapt from the **objective** (`reinforce_edges`). The **Graph** also stores **symbols**, **action history**, **tension history**, **prediction-error EMA/trend**, **action deltas** and **scale factor** for the hybrid predictor, **`novelty_scale`**, **`distributed_graphs`** (Phase 5), and **`sensor_blend_weight`**.

The **`ControlSystem`** owns the **`Graph`**, **`SensorEncoder`**, **`real_sensors`** callables, environment paths (`control_path()`), wave counter, drift flags, commit/rollback counters (`commits`, `rollbacks`, `vibe_*`, `code_emit_*`, `emergent_goal_*`, `hierarchical_plan_*`, `embodiment_*`, `self_feature_*`), optional **vision history**, and **embodiment / vision / feature** counters.

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
| **Emergent goals** | “Boredom” detection → refined target proposals + sandbox; optional **`EMERGENT_RELAX_GATE`**. |
| **Hierarchical planning** | Reflection + longer-horizon `exec` proposals; same audit/gate family as emissions. |
| **Checkpoint** | `brain_checkpoint.json` resume (optional disable via env). |
| **Embodiment** | Gated PyAutoGUI; opt-in **`BRAIN_EMBODIMENT`**. |
| **Vision symbols** | Stable screen-hash repetition → symbol; opt-out **`BRAIN_VISION_SYMBOLS`**. |
| **Self-feature** | ControlSystem-level `exec` proposals; opt-in **`BRAIN_SELF_FEATURE`**. |

---

## Files in this repo

| File | Purpose |
|------|---------|
| `closed_loop_control.py` | **Entire implementation** — run this. |
| `control_value.txt` | Primary scalar **plant** state (read/written each wave). |
| `control_value_2.txt` | Second scalar channel for multi-environment tests. |
| `control_target.txt` | Goal scalar for the controller. |
| `external_event.txt` | Optional **Phase 5** external scalar (created if missing). |
| `brain_checkpoint.json` | **Runtime** persistent state (if checkpoint enabled). **Gitignored** — not committed. |
| `vibe_code_audit.log` | **Append-only** audit (proposals, commits, rollbacks, `ENV=`, checkpoint, embodiment, vision, self-feature). **Gitignored** — regenerates. |

---

## Requirements

- **Python 3.10+** recommended (uses `from __future__ import annotations` and modern typing).

**Core substrate:** no `pip install` required.

**Optional (embodiment + vision hashes):**

```bash
pip install pillow pyautogui
```

**Tkinter** is used for confirmation dialogs (usually bundled with Python on Windows; on Linux, install your distro’s `python3-tk` if needed).

---

## How to run

### Default entry point

```bash
python closed_loop_control.py
```

Runs **`run_scaling_test`** (target 500, 1000 waves per environment, two envs, quiet mode for waves). Loads **`brain_checkpoint.json`** if present and checkpoint is enabled.

### Single episode helper

From Python or a small script, call `run_episode(waves, seed, initial_value, target, quiet=...)`.

### Full demo stack (PowerShell)

Checkpoint + code emission + optional embodiment + vision symbols + self-feature:

```powershell
$env:CODE_EMISSION_DEMO = "y"
$env:CODE_EMISSION_AUTO = "y"
$env:CODE_EMISSION_INTERVAL = "50"
# Optional: $env:EMERGENT_RELAX_GATE = "y"

# Persistent state (default on; set to 0 to disable load/save)
# $env:BRAIN_CHECKPOINT = "0"

# Gated mouse/keyboard (requires pillow + pyautogui + tk)
$env:BRAIN_EMBODIMENT = "y"

# Vision symbols (default on; set BRAIN_VISION_SYMBOLS=0 to disable screen grabs)
# $env:BRAIN_VISION_SYMBOLS = "y"

# Self-feature proposals (off by default)
$env:BRAIN_SELF_FEATURE = "y"

python closed_loop_control.py
```

Optional: write numbers to `external_event.txt` while the process runs to exercise the **file sensor**.

**Note:** Screen capture (`ImageGrab`) and embodiment can be **slow** on long runs; disable vision/embodiment env vars for faster tests.

---

## Environment variables (reference)

| Variable | Effect |
|----------|--------|
| `CODE_EMISSION_DEMO` | Enables demo-style gates / proposal scaling for emissions (see source). |
| `CODE_EMISSION_AUTO` | `y` / `1` / `yes` — auto-accept emission when sandbox gate passes (non-interactive). |
| `CODE_EMISSION_INTERVAL` | Waves between emission attempts (default 200). |
| `CODE_EMISSION_GATE_MEAN`, `CODE_EMISSION_GATE_VAR` | Override production ratio gate factors. |
| `CODE_EMISSION_DELTA_MULT`, `CODE_EMISSION_NOVELTY_MULT`, `CODE_EMISSION_META_W` | Tune proposal strengths. |
| `EMERGENT_RELAX_GATE` | `y` / `1` / `yes` — looser emergent-goal gate (exploration); audited. |
| `BRAIN_CHECKPOINT` | Default on; set **`0`** / **`n`** / **`no`** to disable checkpoint load/save. |
| `BRAIN_EMBODIMENT` | **`y`** enables Tk-gated PyAutoGUI proposals (otherwise skipped). |
| `BRAIN_VISION_SYMBOLS` | Default **on**; set **`0`** to disable vision capture / vision-symbol creation. |
| `BRAIN_SELF_FEATURE` | **`y`** enables sandboxed self-feature `exec` proposals (otherwise skipped). |

**Key constants** (in `closed_loop_control.py`): `EMERGENT_GOAL_INTERVAL`, `HIERARCHICAL_INTERVAL`, `EMBODIMENT_INTERVAL`, `VISION_SYMBOL_INTERVAL`, `FEATURE_PROPOSAL_INTERVAL`, `EMERGENT_STABLE_*`, `EMERGENT_GATE_*`, `DISTRIBUTED_EMISSION_PROB`, `REAL_SENSOR_INTERVAL`, etc.

---

## Safety and audit model

- **Sandboxes** never perform irreversible writes to control files during evaluation of a candidate mutation (unless a specific evaluator does so by design—see source).
- **Commits** happen only after **recorded** baseline vs trial metrics pass the gate.
- **Embodiment** never runs without **`BRAIN_EMBODIMENT=y`** and an explicit **Yes** in the dialog for each action.
- **Audit log** lines include timestamps, **`ENV=`**, checkpoint load/save, **`EMBODIMENT_*`**, **`VISION_SYMBOL_FORMED`**, **`SELF_FEATURE_*`**, hierarchical and emergent tags, and rollback reasons.

This is **not** a substitute for OS-level isolation: restricted `exec` is still `exec`. For untrusted proposals, run in a container or subprocess sandbox (future work).

---

## Limitations (honest)

- **Single process**, single main graph; **distributed** children are stored and scored in emission / feature sandboxes; live `wave_step` does not run a full coupled multi-graph simulation.
- **Scalar plant** is intentionally tiny; scaling to rich sensors is API-sized, not production robotics.
- **Self-feature** sandbox uses **deep copy** of the controller and can be **CPU-heavy** on long runs.
- **Checkpoint** does not serialise every possible runtime tweak (for example, ad-hoc **`real_sensors`** tuple growth may not round-trip every edge case); treat checkpoint as best-effort continuity.
- **Tuning** (intervals, gates) affects how often commits occur; conservative defaults favor **no change** near a good attractor.

---

## Contributing / license

Issues and PRs can target: clearer modular splits (still optional), stronger sandbox isolation, or richer sensors—without breaking the “readable single file” story.

If you add a license file, pick one explicitly; this README does not impose one by default.

---

## Acknowledgement

Design and iteration history are documented in commit messages and in `vibe_code_audit.log` on your machine (not committed—regenerated each run).

**BoggersBrain** — *tension low, edge open.*
