#!/usr/bin/env python3
"""
Closed-loop, self-modifying cognitive substrate: graph dynamics, tension minimisation,
sandboxed self-modification, emergent action-sequence symbols.
No neural networks, no gradients, no external ML libraries.
"""

from __future__ import annotations

import copy
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

try:
    import tkinter as tk
    from tkinter import messagebox
except ImportError:  # pragma: no cover
    tk = None  # type: ignore[assignment]
    messagebox = None  # type: ignore[assignment]

try:
    from PIL import ImageGrab
except ImportError:  # pragma: no cover
    ImageGrab = None  # type: ignore[assignment]

try:
    import pyautogui
except ImportError:  # pragma: no cover
    pyautogui = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VEC_DIM = 16
NUM_NODES = 4
SENSOR_ID = 0
PRED_ID = 1
MOTOR_ID = 2
META_ID = 3

NOVELTY_SCALE = 0.15
BASELINE_ALPHA = 0.05
EDGE_LR = 0.02
RELAX_STEPS = 3
PROP_BIAS = 0.05
SANDBOX_WAVES = 10
PRED_EMA_ALPHA = 0.05
PREDICTION_ERROR_TREND_CAP = 40
SYMBOL_DRIFT_PENALTY = 1.25
MUTATION_EVERY = 5
MUTATION_EVERY_DRIFT = 3
DRIFT_THRESHOLD = 2.0
VERY_HIGH_TENSION = 1e6
DELTA_LR = 0.1
SCALE_LR = 0.01

ENV_PATH = Path(__file__).resolve().parent / "control_value.txt"
ENV_PATH_2 = Path(__file__).resolve().parent / "control_value_2.txt"
EXTERNAL_EVENT_PATH = Path(__file__).resolve().parent / "external_event.txt"
TARGET_PATH = Path(__file__).resolve().parent / "control_target.txt"
DEFAULT_TARGET = 100.0
HISTORY_LEN = 32
TENSION_HISTORY_CAP = 200
ACTION_HISTORY_CAP = 200
MAX_SYMBOLS = 32
VIBE_HORIZON = 20
VIBE_INTERVAL = 100
CODE_EMISSION_INTERVAL = 200
REAL_SENSOR_INTERVAL = 50
MAX_DISTRIBUTED_GRAPHS = 4
DISTRIBUTED_EMISSION_PROB = 0.35
DEFAULT_SENSOR_BLEND_WEIGHT = 0.3
EMERGENT_GOAL_INTERVAL = 400
# Must fit in TENSION_HISTORY_CAP (200); "300 waves" intent uses min(window, len(history)).
EMERGENT_STABLE_WINDOW = 300
EMERGENT_STABLE_MEAN_MAX = 0.5
EMERGENT_STABLE_VAR_MAX = 0.1
# Refined emergent goals: sandbox must beat baseline internal-wave stats by these ratios.
EMERGENT_GATE_MEAN_RATIO = 0.95
EMERGENT_GATE_VAR_RATIO = 0.9
# If set to 1/y/yes: allow small regression vs baseline (exploration) — see maybe_invent_goal().
EMERGENT_RELAX_GATE_ENV = "EMERGENT_RELAX_GATE"
HIERARCHICAL_INTERVAL = 300
REFLECTION_WINDOW = 100
HIERARCHICAL_SANDBOX_STEPS = 30
EMBODIMENT_INTERVAL = 100
VISION_SYMBOL_INTERVAL = 150
VISION_CAPTURE_INTERVAL = 50
FEATURE_PROPOSAL_INTERVAL = 500
FEATURE_SANDBOX_STEPS = 40
# Spawn a shadow graph for parallel internal-wave scoring (no invalid extra node ids).
DISTRIBUTED_SPAWN_DIFF = (
    "self.distributed_graphs.append(spawn_child_graph(self)); "
    f"self.distributed_graphs = self.distributed_graphs[-{MAX_DISTRIBUTED_GRAPHS}:]"
)

VIBE_AUDIT_LOG = Path(__file__).resolve().parent / "vibe_code_audit.log"
CHECKPOINT_PATH = Path(__file__).resolve().parent / "brain_checkpoint.json"
CHECKPOINT_VERSION = 1


def checkpoint_enabled() -> bool:
    """Set BRAIN_CHECKPOINT=0 to disable load/save (default: enabled)."""
    return os.environ.get("BRAIN_CHECKPOINT", "1").strip().lower() not in ("0", "n", "no", "false")


def embodiment_enabled() -> bool:
    """Set BRAIN_EMBODIMENT=y to allow gated desktop actions (default: off)."""
    v = os.environ.get("BRAIN_EMBODIMENT", "").strip().lower()
    return v in ("1", "y", "yes")


def embodiment_deps_available() -> bool:
    return (
        tk is not None
        and messagebox is not None
        and ImageGrab is not None
        and pyautogui is not None
    )


def vision_symbols_enabled() -> bool:
    """Set BRAIN_VISION_SYMBOLS=0 to disable vision symbols (default: enabled)."""
    v = os.environ.get("BRAIN_VISION_SYMBOLS", "y").strip().lower()
    return v not in ("0", "n", "no", "false")


def self_feature_enabled() -> bool:
    """Set BRAIN_SELF_FEATURE=y to enable sandboxed self-feature proposals (default: off)."""
    v = os.environ.get("BRAIN_SELF_FEATURE", "").strip().lower()
    return v in ("1", "y", "yes")


def code_emission_gate_and_scales() -> Tuple[float, float, float, float, float]:
    """
    Returns (gate_mean_factor, gate_var_factor, delta_mult, novelty_mult, meta_edge_w).

    Production gate (default): t_mean < gate_mean * b_mean and t_var < gate_var * b_var
    (defaults 0.95 / 0.9 — same spirit as the original Phase B spec).

    CODE_EMISSION_DEMO=1: softer multipliers (1.02 / 0.99 / 0.05) and **the same strict
    improvement test as maybe_vibe_code** (t_mean < b_mean and t_var < b_var). Ratio factors
    are still logged for audit but do not gate in demo mode — the 0.98×mean bar is
    unrealistically tight when baseline mean is O(1).
    Individual factors can be overridden with CODE_EMISSION_GATE_MEAN, _GATE_VAR, _DELTA_MULT,
    CODE_EMISSION_NOVELTY_MULT, CODE_EMISSION_META_W.
    """
    demo = os.environ.get("CODE_EMISSION_DEMO", "").strip().lower() in ("1", "y", "yes")
    if demo:
        return (0.98, 0.95, 1.02, 0.99, 0.05)
    gm = float(os.environ.get("CODE_EMISSION_GATE_MEAN", "0.95"))
    gv = float(os.environ.get("CODE_EMISSION_GATE_VAR", "0.9"))
    dm = float(os.environ.get("CODE_EMISSION_DELTA_MULT", "1.05"))
    nm = float(os.environ.get("CODE_EMISSION_NOVELTY_MULT", "0.95"))
    mw = float(os.environ.get("CODE_EMISSION_META_W", "0.75"))
    return (gm, gv, dm, nm, mw)


def code_emission_demo_mode() -> bool:
    return os.environ.get("CODE_EMISSION_DEMO", "").strip().lower() in ("1", "y", "yes")


def emergent_relax_gate() -> bool:
    return os.environ.get(EMERGENT_RELAX_GATE_ENV, "").strip().lower() in ("1", "y", "yes")


def code_emission_interval_waves() -> int:
    """Waves between code emission attempts; override with CODE_EMISSION_INTERVAL (e.g. 50 for demos)."""
    raw = os.environ.get("CODE_EMISSION_INTERVAL", str(CODE_EMISSION_INTERVAL))
    try:
        return max(1, int(raw))
    except ValueError:
        return CODE_EMISSION_INTERVAL


def tanh(x: float) -> float:
    return math.tanh(x)


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na < 1e-12 or nb < 1e-12:
        return 0.0
    return dot / (na * nb)


def vec_add(a: Sequence[float], b: Sequence[float]) -> List[float]:
    return [x + y for x, y in zip(a, b)]


def vec_scale(v: Sequence[float], s: float) -> List[float]:
    return [x * s for x in v]


def vec_copy(v: Sequence[float]) -> List[float]:
    return list(v)


# ---------------------------------------------------------------------------
# Graph structures
# ---------------------------------------------------------------------------


@dataclass
class Node:
    nid: int
    activation: float = 0.0
    vector: List[float] = field(default_factory=lambda: [0.0] * VEC_DIM)
    stability: float = 1.0
    base_strength: float = 1.0


@dataclass
class Edge:
    from_id: int
    to_id: int
    weight: float


@dataclass
class Symbol:
    pattern: List[int]
    usage_count: int = 0
    tension_reduction: float = 0.0


@dataclass
class Graph:
    nodes: Dict[int, Node] = field(default_factory=dict)
    edges: List[Edge] = field(default_factory=list)
    tension_history: List[float] = field(default_factory=list)
    last_state: List[float] = field(default_factory=lambda: [0.0] * VEC_DIM)
    last_error: float = 0.0
    target: float = DEFAULT_TARGET
    symbols: List[Symbol] = field(default_factory=list)
    action_history: List[int] = field(default_factory=list)
    prediction_error_avg: float = 0.0
    prediction_error_trend: List[float] = field(default_factory=list)
    action_deltas: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    scale_factor: float = 0.99
    novelty_scale: float = NOVELTY_SCALE
    distributed_graphs: List[Graph] = field(default_factory=list)
    sensor_blend_weight: float = DEFAULT_SENSOR_BLEND_WEIGHT

    def __post_init__(self) -> None:
        for i in range(NUM_NODES):
            if i not in self.nodes:
                self.nodes[i] = Node(nid=i, activation=0.0, vector=[0.0] * VEC_DIM)


def spawn_child_graph(g: Graph) -> Graph:
    """Deep copy for distributed wave children; strip nested children to avoid exponential blow-up."""
    c = copy.deepcopy(g)
    c.distributed_graphs = []
    return c


def read_timestamp_sensor_vec() -> List[float]:
    """Wall-clock features: three phases repeated to 15 floats, padded to VEC_DIM (Phase 5)."""
    t = time.time()
    triple = [(t % 1000) / 1000.0, (t % 60) / 60.0, (t % 3600) / 3600.0]
    fifteen = (triple * 5)[:15]
    pad = fifteen + [fifteen[-1]]
    return pad[:VEC_DIM]


def read_external_event_vec(path: Path = EXTERNAL_EVENT_PATH) -> List[float]:
    """Scalar from external_event.txt replicated across VEC_DIM."""
    try:
        if not path.exists():
            path.write_text("0\n", encoding="utf-8")
        txt = path.read_text(encoding="utf-8").strip()
        if not txt:
            val = 0.0
        else:
            val = float(txt.split()[0])
        if math.isnan(val) or math.isinf(val):
            val = 0.0
        x = val / 100.0
        return [x] * VEC_DIM
    except Exception:
        return [0.0] * VEC_DIM


def build_initial_graph(rng: random.Random, target: float) -> Graph:
    g = Graph()
    g.target = target
    for nid in range(NUM_NODES):
        g.nodes[nid].vector = [rng.uniform(-0.2, 0.2) for _ in range(VEC_DIM)]
        g.nodes[nid].stability = 1.0
        g.nodes[nid].base_strength = 1.0
    for fi in range(NUM_NODES):
        for ti in range(NUM_NODES):
            if fi == ti:
                continue
            g.edges.append(Edge(fi, ti, rng.uniform(-0.4, 0.4)))
    g.action_deltas = [0.0, 0.0, 0.0]
    g.scale_factor = 0.99
    return g


# ---------------------------------------------------------------------------
# Environment (file-based scalar + optional target file)
# ---------------------------------------------------------------------------


def read_control_value(path: Path) -> float:
    try:
        if not path.exists():
            return 0.0
        txt = path.read_text(encoding="utf-8").strip()
        if txt == "":
            return 0.0
        val = float(txt.split()[0])
        if math.isnan(val) or math.isinf(val):
            return 0.0
        return val
    except Exception:
        return 0.0


def write_control_value(path: Path, value: float) -> None:
    path.write_text(f"{value}\n", encoding="utf-8")


def read_target(path: Path, default: float = DEFAULT_TARGET) -> float:
    if not path.exists():
        path.write_text(f"{default}\n", encoding="utf-8")
    text = path.read_text(encoding="utf-8").strip()
    return float(text.split()[0])


def write_target(path: Path, target: float) -> None:
    path.write_text(f"{target}\n", encoding="utf-8")


def apply_action(value: float, action: int) -> float:
    if action == 0:
        return value + 1.0
    if action == 1:
        return value - 1.0
    if action == 2:
        return value * 0.99
    return value


# ---------------------------------------------------------------------------
# Sensor encoding → fixed 16D (mean, variance, delta, normalisation vs target)
# ---------------------------------------------------------------------------


class SensorEncoder:
    def __init__(self) -> None:
        self._history: List[float] = []
        self._last: float = 0.0

    def encode(self, scalar: float, target: float) -> List[float]:
        self._history.append(scalar)
        if len(self._history) > HISTORY_LEN:
            self._history.pop(0)
        h = self._history
        mean = sum(h) / len(h)
        var = sum((x - mean) ** 2 for x in h) / max(len(h), 1)
        delta = scalar - self._last
        self._last = scalar
        scale = max(abs(target), 1.0)
        nm = mean / scale
        nv = math.sqrt(max(var, 0.0)) / scale
        nd = delta / scale
        ns = scalar / scale
        out = [0.0] * VEC_DIM
        out[0] = nm
        out[1] = nv
        out[2] = nd
        out[3] = ns
        out[4] = math.sin(ns * math.pi)
        out[5] = math.cos(ns * math.pi * 0.5)
        out[6] = tanh(nd * 2.0)
        out[7] = tanh((scalar - target) / max(scale * 0.25, 1e-6))
        for k in range(8, VEC_DIM):
            lag = k - 7
            if len(h) > lag:
                out[k] = tanh((h[-1] - h[-lag - 1]) / max(scale, 1e-6))
            else:
                out[k] = 0.0
        return out


# ---------------------------------------------------------------------------
# Objective (ground truth, identical everywhere)
# ---------------------------------------------------------------------------


def goal_error(value: float, target: float) -> float:
    d = value - target
    return d * d


def compute_tension(
    prediction_error: float,
    internal_mismatch: float,
    overactivation_penalty: float,
    g_err: float,
) -> float:
    return (
        prediction_error
        + 0.3 * internal_mismatch
        + 0.2 * overactivation_penalty
        + 0.1 * g_err
    )


def compute_real_wave_tension(
    prediction_error: float,
    internal_mismatch: float,
    overactivation_penalty: float,
    g_err: float,
    prediction_weight: float,
) -> float:
    return (
        prediction_weight * prediction_error
        + 0.3 * internal_mismatch
        + 0.2 * overactivation_penalty
        + 0.1 * g_err
    )


def total_objective(
    tension: float,
    novelty_cos: float,
    pred_error_decreased: bool,
    novelty_scale: float = NOVELTY_SCALE,
) -> float:
    novelty_bonus = novelty_scale * novelty_cos if pred_error_decreased else 0.0
    return tension - novelty_bonus


def drift_detected(g: Graph) -> bool:
    t = g.prediction_error_trend
    if len(t) < 40:
        return False
    m_recent = sum(t[-20:]) / 20.0
    m_prev = sum(t[-40:-20]) / 20.0
    return m_recent > m_prev


# ---------------------------------------------------------------------------
# Graph dynamics
# ---------------------------------------------------------------------------


def propagate_once(g: Graph) -> None:
    incoming: Dict[int, float] = {i: 0.0 for i in g.nodes}
    for e in g.edges:
        incoming[e.to_id] += e.weight * g.nodes[e.from_id].activation
    for nid, node in g.nodes.items():
        s = incoming[nid] + PROP_BIAS
        node.activation = tanh(s)


def relax_and_normalize(g: Graph, steps: int = RELAX_STEPS) -> None:
    for _ in range(steps):
        propagate_once(g)
        acc = [g.nodes[i].activation for i in range(NUM_NODES)]
        mag = math.sqrt(sum(a * a for a in acc) / max(len(acc), 1)) + 1e-8
        for i in range(NUM_NODES):
            g.nodes[i].activation /= mag


def inject_sensor(g: Graph, sensor_vec: List[float]) -> None:
    g.nodes[SENSOR_ID].vector = vec_copy(sensor_vec)
    e = math.sqrt(sum(x * x for x in sensor_vec)) / math.sqrt(float(VEC_DIM))
    g.nodes[SENSOR_ID].activation = tanh(e * 2.0)


def blend_vectors_from_nodes(g: Graph) -> List[float]:
    out = [0.0] * VEC_DIM
    for nid in range(NUM_NODES):
        w = abs(g.nodes[nid].activation) + 0.25
        for i in range(VEC_DIM):
            out[i] += g.nodes[nid].vector[i] * w
    mag = math.sqrt(sum(x * x for x in out)) + 1e-8
    return [x / mag for x in out]


def predict_next_scalar_for_action(g: Graph, current_value: float, action: int) -> float:
    """Per-action Δ (learned); action 2 is multiplicative scale."""
    if action == 2:
        return current_value * g.scale_factor
    return current_value + g.action_deltas[action]


def hybrid_planning_tension(g: Graph, value: float, action: int) -> float:
    """Planning: real physics + model, drift penalty, graph regularisers."""
    real_next = apply_action(value, action)
    model_next = predict_next_scalar_for_action(g, value, action)
    if abs(model_next - real_next) > DRIFT_THRESHOLD:
        return VERY_HIGH_TENSION
    prediction_error = (model_next - real_next) ** 2
    ge = goal_error(real_next, g.target)
    hybrid_core = 0.5 * ge + 0.5 * (prediction_error + ge)
    drift_pen = abs(model_next - real_next)
    imm = internal_mismatch_metric(g)
    oap = overactivation_penalty_metric(g)
    return hybrid_core + 0.2 * drift_pen + 0.3 * imm + 0.2 * oap


def predicted_tension_from_relaxed_graph(g: Graph, value: float, action: int) -> float:
    return hybrid_planning_tension(g, value, action)


def select_action_lowest_tension(g: Graph, value: float) -> int:
    """Among raw actions only; argmin predicted tension (no randomness)."""
    best_a = 0
    best_t = predicted_tension_from_relaxed_graph(g, value, 0)
    for a in (1, 2):
        t = predicted_tension_from_relaxed_graph(g, value, a)
        if t < best_t:
            best_t = t
            best_a = a
    return best_a


def internal_mismatch_metric(g: Graph) -> float:
    act = [g.nodes[i].activation for i in range(NUM_NODES)]
    m = sum(act) / len(act)
    return sum((a - m) ** 2 for a in act) / len(act)


def overactivation_penalty_metric(g: Graph) -> float:
    return sum(g.nodes[i].activation ** 2 for i in range(NUM_NODES)) / NUM_NODES


def update_node_dynamics(g: Graph, sensor_vec: List[float], predicted_scalar: float) -> None:
    blend = blend_vectors_from_nodes(g)
    g.nodes[PRED_ID].vector = vec_add(
        vec_scale(sensor_vec, 0.5),
        vec_scale(blend, 0.5),
    )
    scale_t = max(abs(g.target), 1.0)
    err_norm = (predicted_scalar - g.target) / scale_t
    for i in range(VEC_DIM):
        g.nodes[PRED_ID].vector[i] += tanh(err_norm) * 0.1
    g.nodes[MOTOR_ID].vector = vec_add(g.nodes[MOTOR_ID].vector, vec_scale(blend, 0.15))
    g.nodes[META_ID].vector = vec_add(g.nodes[META_ID].vector, vec_scale(sensor_vec, 0.1))

    for nid in range(NUM_NODES):
        n = g.nodes[nid]
        inst = abs(n.activation)
        n.stability = 0.95 * n.stability + 0.05 * (1.0 - min(1.0, inst))
        vnorm = math.sqrt(sum(x * x for x in n.vector)) / math.sqrt(float(VEC_DIM))
        n.base_strength = 0.99 * n.base_strength + 0.01 * max(0.1, vnorm)


# ---------------------------------------------------------------------------
# Meta vector → stored in meta node
# ---------------------------------------------------------------------------


def meta_vector(g: Graph, avg_tension_last10: float) -> List[float]:
    n = len(g.nodes)
    possible = n * (n - 1)
    density = len(g.edges) / possible if possible > 0 else 0.0
    mean_act = sum(g.nodes[i].activation for i in range(NUM_NODES)) / NUM_NODES
    confidence = 1.0 / (1.0 + g.prediction_error_avg)
    return [
        float(n),
        density,
        mean_act,
        avg_tension_last10,
        confidence,
    ]


def embed_meta_into_graph(g: Graph, meta: List[float]) -> None:
    for i, m in enumerate(meta):
        if i < VEC_DIM:
            g.nodes[META_ID].vector[i] = tanh(m)


# ---------------------------------------------------------------------------
# Sandbox simulation — NO file I/O; same tension as real wave
# ---------------------------------------------------------------------------


@dataclass
class SimState:
    nodes_act: Dict[int, float]
    nodes_vec: Dict[int, List[float]]
    nodes_stability: Dict[int, float]
    nodes_base_strength: Dict[int, float]
    edges: List[Tuple[int, int, float]]
    value: float
    target: float
    encoder_history: List[float]
    encoder_last: float
    action_deltas: Tuple[float, float, float]
    scale_factor: float
    novelty_scale: float


def graph_to_sim_state(g: Graph, value: float, encoder: SensorEncoder) -> SimState:
    return SimState(
        nodes_act={k: v.activation for k, v in g.nodes.items()},
        nodes_vec={k: vec_copy(v.vector) for k, v in g.nodes.items()},
        nodes_stability={k: v.stability for k, v in g.nodes.items()},
        nodes_base_strength={k: v.base_strength for k, v in g.nodes.items()},
        edges=[(e.from_id, e.to_id, e.weight) for e in g.edges],
        value=value,
        target=g.target,
        encoder_history=list(encoder._history),
        encoder_last=encoder._last,
        action_deltas=(g.action_deltas[0], g.action_deltas[1], g.action_deltas[2]),
        scale_factor=g.scale_factor,
        novelty_scale=g.novelty_scale,
    )


def sim_state_to_graph(st: SimState) -> Tuple[Graph, SensorEncoder]:
    g = Graph()
    g.target = st.target
    g.last_error = 0.0
    g.last_state = [0.0] * VEC_DIM
    g.action_deltas = list(st.action_deltas)
    g.scale_factor = st.scale_factor
    g.novelty_scale = st.novelty_scale
    for nid in range(NUM_NODES):
        g.nodes[nid] = Node(
            nid=nid,
            activation=st.nodes_act[nid],
            vector=vec_copy(st.nodes_vec[nid]),
            stability=st.nodes_stability[nid],
            base_strength=st.nodes_base_strength[nid],
        )
    g.edges = [Edge(a, b, w) for a, b, w in st.edges]
    enc = SensorEncoder()
    enc._history = list(st.encoder_history)
    enc._last = st.encoder_last
    return g, enc


def internal_wave_step(st: SimState) -> Tuple[SimState, float]:
    g, enc = sim_state_to_graph(st)
    sensor_vec = enc.encode(st.value, g.target)
    inject_sensor(g, sensor_vec)
    relax_and_normalize(g)
    action = select_action_lowest_tension(g, st.value)
    model_next = predict_next_scalar_for_action(g, st.value, action)
    real_next = apply_action(st.value, action)
    tension = hybrid_planning_tension(g, st.value, action)
    update_node_dynamics(g, sensor_vec, model_next)
    new_st = SimState(
        nodes_act={k: g.nodes[k].activation for k in g.nodes},
        nodes_vec={k: vec_copy(g.nodes[k].vector) for k in g.nodes},
        nodes_stability={k: g.nodes[k].stability for k in g.nodes},
        nodes_base_strength={k: g.nodes[k].base_strength for k in g.nodes},
        edges=[(e.from_id, e.to_id, e.weight) for e in g.edges],
        value=real_next,
        target=g.target,
        encoder_history=list(enc._history),
        encoder_last=enc._last,
        action_deltas=(g.action_deltas[0], g.action_deltas[1], g.action_deltas[2]),
        scale_factor=g.scale_factor,
        novelty_scale=g.novelty_scale,
    )
    return new_st, tension


def internal_wave(initial: SimState, steps: int) -> List[float]:
    st = initial
    out: List[float] = []
    for _ in range(steps):
        st, t = internal_wave_step(st)
        out.append(t)
    return out


def mean_var(xs: Sequence[float]) -> Tuple[float, float]:
    if not xs:
        return 0.0, 0.0
    m = sum(xs) / len(xs)
    v = sum((x - m) ** 2 for x in xs) / len(xs)
    return m, v


def sandbox_vibe_eval(
    g: Graph,
    value: float,
    encoder: SensorEncoder,
    apply_fn: Callable[[Graph], None],
) -> Tuple[float, float, float, float]:
    """Baseline vs trial internal_wave tensions; same contract as edge mutation."""
    snap = graph_to_sim_state(g, value, encoder)
    baseline = internal_wave(snap, VIBE_HORIZON)
    b_mean, b_var = mean_var(baseline)
    g_shadow, enc_shadow = sim_state_to_graph(snap)
    apply_fn(g_shadow)
    snap2 = graph_to_sim_state(g_shadow, value, enc_shadow)
    trial = internal_wave(snap2, VIBE_HORIZON)
    t_mean, t_var = mean_var(trial)
    return b_mean, b_var, t_mean, t_var


# ---------------------------------------------------------------------------
# Symbols — real vs model goal metrics (validation uses both)
# ---------------------------------------------------------------------------


def real_pattern_goal_metrics(
    start_value: float,
    pattern: Sequence[int],
    target: float,
) -> Tuple[float, float]:
    v = start_value
    seq_sum = 0.0
    for a in pattern:
        v = apply_action(v, a)
        seq_sum += goal_error(v, target)
    final_ge = goal_error(v, target)
    return seq_sum, final_ge


def model_pattern_goal_metrics(
    g: Graph,
    encoder: SensorEncoder,
    start_value: float,
    pattern: Sequence[int],
) -> Tuple[float, float]:
    """
    Returns (sum of goal_error after each imagined step, goal_error at final imagined state).
    Trajectory uses predict_next_scalar_for_action only.
    """
    st = graph_to_sim_state(g, start_value, encoder)
    seq_sum = 0.0
    cur = st
    for act in pattern:
        g2, enc2 = sim_state_to_graph(cur)
        sensor_vec = enc2.encode(cur.value, g2.target)
        inject_sensor(g2, sensor_vec)
        relax_and_normalize(g2)
        model_next = predict_next_scalar_for_action(g2, cur.value, act)
        seq_sum += goal_error(model_next, g2.target)
        update_node_dynamics(g2, sensor_vec, model_next)
        cur = SimState(
            nodes_act={k: g2.nodes[k].activation for k in g2.nodes},
            nodes_vec={k: vec_copy(g2.nodes[k].vector) for k in g2.nodes},
            nodes_stability={k: g2.nodes[k].stability for k in g2.nodes},
            nodes_base_strength={k: g2.nodes[k].base_strength for k in g2.nodes},
            edges=[(e.from_id, e.to_id, e.weight) for e in g2.edges],
            value=model_next,
            target=g2.target,
            encoder_history=list(enc2._history),
            encoder_last=enc2._last,
            action_deltas=(
                g2.action_deltas[0],
                g2.action_deltas[1],
                g2.action_deltas[2],
            ),
            scale_factor=g2.scale_factor,
            novelty_scale=g2.novelty_scale,
        )
    final_ge = goal_error(cur.value, cur.target)
    return seq_sum, final_ge


def predict_tension_for_pattern(
    g: Graph,
    value: float,
    encoder: SensorEncoder,
    pattern: Sequence[int],
) -> float:
    """Symbol option score: hybrid tension along real-valued rollout."""
    st = graph_to_sim_state(g, value, encoder)
    total = 0.0
    cur = st
    for act in pattern:
        g2, enc2 = sim_state_to_graph(cur)
        sensor_vec = enc2.encode(cur.value, g2.target)
        inject_sensor(g2, sensor_vec)
        relax_and_normalize(g2)
        model_next = predict_next_scalar_for_action(g2, cur.value, act)
        total += hybrid_planning_tension(g2, cur.value, act)
        update_node_dynamics(g2, sensor_vec, model_next)
        real_next = apply_action(cur.value, act)
        cur = SimState(
            nodes_act={k: g2.nodes[k].activation for k in g2.nodes},
            nodes_vec={k: vec_copy(g2.nodes[k].vector) for k in g2.nodes},
            nodes_stability={k: g2.nodes[k].stability for k in g2.nodes},
            nodes_base_strength={k: g2.nodes[k].base_strength for k in g2.nodes},
            edges=[(e.from_id, e.to_id, e.weight) for e in g2.edges],
            value=real_next,
            target=g2.target,
            encoder_history=list(enc2._history),
            encoder_last=enc2._last,
            action_deltas=(
                g2.action_deltas[0],
                g2.action_deltas[1],
                g2.action_deltas[2],
            ),
            scale_factor=g2.scale_factor,
            novelty_scale=g2.novelty_scale,
        )
    return total / max(len(pattern), 1)


def find_repeated_sequences(
    history: List[int],
    min_len: int = 3,
    max_len: int = 8,
) -> List[List[int]]:
    found: List[List[int]] = []
    seen = set()
    for ln in range(max_len, min_len - 1, -1):
        if len(history) < ln * 2:
            continue
        for i in range(len(history) - ln * 2 + 1):
            seq = tuple(history[i : i + ln])
            for j in range(i + ln, len(history) - ln + 1):
                if tuple(history[j : j + ln]) == seq:
                    if seq not in seen:
                        seen.add(seq)
                        found.append(list(seq))
                    break
    return found


# ---------------------------------------------------------------------------
# Control system — one wave = full loop, no skipped steps
# ---------------------------------------------------------------------------


class ControlSystem:
    def __init__(
        self,
        rng: Optional[random.Random] = None,
        env_path: Path = ENV_PATH,
        target_path: Path = TARGET_PATH,
        env_paths: Optional[List[Path]] = None,
    ) -> None:
        self.rng = rng or random.Random(42)
        self.env_paths = env_paths if env_paths is not None else [env_path, ENV_PATH_2]
        self.env_id = 0
        self.env_path = self.env_paths[0]
        self.target_path = target_path
        for p in self.env_paths:
            if not p.exists():
                write_control_value(p, 50.0)
        t0 = read_target(self.target_path, DEFAULT_TARGET)
        self.graph = build_initial_graph(self.rng, t0)
        self.encoder = SensorEncoder()
        self.wave_num = 0
        self.prev_prediction_error = 0.0
        self.baseline_objective = 0.0
        self.commits = 0
        self.rollbacks = 0
        self.drift_this_wave = False
        self.drift_ever = False
        self.quiet = False
        self.vibe_commits = 0
        self.vibe_rollbacks = 0
        self.code_emit_commits = 0
        self.code_emit_rollbacks = 0
        self.emergent_goal_commits = 0
        self.emergent_goal_rollbacks = 0
        self.hierarchical_plan_commits = 0
        self.hierarchical_plan_rollbacks = 0
        self.embodiment_commits = 0
        self.embodiment_rollbacks = 0
        self.vision_history: List[float] = []
        self.vision_symbols_formed = 0
        self.self_feature_commits = 0
        self.self_feature_rollbacks = 0
        # Phase 5: real sensor callables (wall clock + external file); blend in sense_real_world.
        self.real_sensors: Tuple[Callable[[], List[float]], ...] = (
            read_timestamp_sensor_vec,
            read_external_event_vec,
        )

    def control_path(self) -> Path:
        return self.env_paths[self.env_id]

    def switch_env(self) -> None:
        self.env_id = 1 - self.env_id
        if not self.quiet:
            print(f"ENV SWITCH -> env_id={self.env_id} path={self.control_path()} target={self.graph.target}")

    def vibe_code_proposal(self) -> Tuple[str, Callable[[Graph], None]]:
        r = self.rng

        def edge_perturb(gg: Graph) -> None:
            if not gg.edges:
                return
            e = gg.edges[r.randrange(len(gg.edges))]
            e.weight += r.uniform(-0.08, 0.08)

        def novelty_tighten(gg: Graph) -> None:
            gg.novelty_scale = max(0.0, gg.novelty_scale * 0.98)

        def delta_lr_bump(gg: Graph) -> None:
            for i in range(3):
                gg.action_deltas[i] *= 1.01

        def add_meta_to_pred(gg: Graph) -> None:
            if any(e.from_id == META_ID and e.to_id == PRED_ID for e in gg.edges):
                return
            gg.edges.append(Edge(META_ID, PRED_ID, r.uniform(0.02, 0.08)))

        opts: List[Tuple[str, Callable[[Graph], None]]] = [
            ("edge_weight_perturb", edge_perturb),
            ("novelty_scale_tighten", novelty_tighten),
            ("delta_lr_bump", delta_lr_bump),
            ("add_meta_pred_edge", add_meta_to_pred),
        ]
        return r.choice(opts)

    def maybe_vibe_code(self) -> None:
        g = self.graph
        v = read_control_value(self.control_path())
        name, apply_fn = self.vibe_code_proposal()
        b_mean, b_var, t_mean, t_var = sandbox_vibe_eval(g, v, self.encoder, apply_fn)
        ts = time.time()
        line = (
            f"{ts:.0f} | ENV={self.env_id} | PROPOSAL: {name} | baseline_mean={b_mean:.6f} baseline_var={b_var:.6f} "
            f"| sandbox_mean={t_mean:.6f} sandbox_var={t_var:.6f}\n"
        )
        with open(VIBE_AUDIT_LOG, "a", encoding="utf-8") as log:
            log.write(line)
        if t_mean < b_mean and t_var < b_var:
            apply_fn(g)
            self.vibe_commits += 1
            with open(VIBE_AUDIT_LOG, "a", encoding="utf-8") as log:
                log.write(
                    f"{ts:.0f} | ENV={self.env_id} | COMMITTED {name} mean {b_mean:.6f}->{t_mean:.6f} var {b_var:.6f}->{t_var:.6f}\n"
                )
            if not self.quiet:
                print(
                    f"✅ VIBE-CODE COMMITTED: {name} — mean {b_mean:.4f}→{t_mean:.4f} var {b_var:.4f}→{t_var:.4f}"
                )
        else:
            self.vibe_rollbacks += 1
            with open(VIBE_AUDIT_LOG, "a", encoding="utf-8") as log:
                log.write(f"{ts:.0f} | ENV={self.env_id} | ROLLED_BACK {name}\n")
            if not self.quiet:
                print(f"❌ VIBE-CODE ROLLED BACK: {name}")

    def distributed_wave_proposal(self) -> Tuple[str, str]:
        """Spawn a capped list of shadow graphs; scored in sandbox_distributed_emission_eval."""
        return ("spawn_distributed_wave", DISTRIBUTED_SPAWN_DIFF)

    def sandbox_distributed_emission_eval(self, diff_line: str) -> Tuple[float, float, float, float]:
        """
        Baseline internal_wave vs trial after spawn: combine main + last child tensions (weighted).
        Same horizon as vibe/code emission.
        """
        g = self.graph
        v = read_control_value(self.control_path())
        snap = graph_to_sim_state(g, v, self.encoder)
        baseline = internal_wave(snap, VIBE_HORIZON)
        b_mean, b_var = mean_var(baseline)
        shadow = copy.deepcopy(g)
        try:
            exec(diff_line, self._code_exec_globals(shadow), {})
        except Exception:
            return b_mean, b_var, 999999.0, 999999.0
        snap2 = graph_to_sim_state(shadow, v, self.encoder)
        t_main = internal_wave(snap2, VIBE_HORIZON)
        if not shadow.distributed_graphs:
            t_mean, t_var = mean_var(t_main)
            return b_mean, b_var, t_mean, t_var
        ch = shadow.distributed_graphs[-1]
        t_child = internal_wave(graph_to_sim_state(ch, v, self.encoder), VIBE_HORIZON)
        # Parallel ensemble: per-step average (sum was always inflated vs baseline-only main path).
        combined = [0.5 * t_main[i] + 0.5 * t_child[i] for i in range(VIBE_HORIZON)]
        t_mean, t_var = mean_var(combined)
        return b_mean, b_var, t_mean, t_var

    def sense_real_world(self, g: Graph) -> List[float]:
        """
        After encode+inject, blend the sensor node with one random real sensor.
        state[i] = state[i] * (1 - w) + sensor[i] * w, w = g.sensor_blend_weight.
        """
        w = min(1.0, max(0.0, g.sensor_blend_weight))
        sensor_fn = self.rng.choice(self.real_sensors)
        raw = sensor_fn()
        out: List[float] = []
        for i in range(VEC_DIM):
            s = raw[i] if i < len(raw) else 0.0
            v = g.nodes[SENSOR_ID].vector[i]
            nv = v * (1.0 - w) + s * w
            g.nodes[SENSOR_ID].vector[i] = nv
            out.append(nv)
        return out

    def code_emission_proposal(self) -> Tuple[str, str]:
        """Small auditable one-line mutations (exec'd with restricted globals)."""
        _gm, _gv, dm, nm, mw = code_emission_gate_and_scales()
        opts: List[Tuple[str, str]] = [
            ("novelty_scale_tighten", f"self.novelty_scale *= {nm}"),
            ("add_meta_edge", f"self.edges.append(Edge(META_ID, PRED_ID, {mw}))"),
            (
                "delta_lr_bump",
                f"self.action_deltas[0] *= {dm}; self.action_deltas[1] *= {dm}; self.action_deltas[2] *= {dm}",
            ),
            (
                "edge_weight_perturb",
                "e = rng.choice(self.edges); e.weight += rng.uniform(-0.08, 0.08)",
            ),
        ]
        if code_emission_demo_mode():
            opts.append(
                (
                    "delta_lr_decay",
                    "self.action_deltas[0] *= 0.99; self.action_deltas[1] *= 0.99; self.action_deltas[2] *= 0.99",
                )
            )
        return self.rng.choice(opts)

    def _code_exec_globals(self, g: Graph) -> Dict[str, Any]:
        return {
            "self": g,
            "Edge": Edge,
            "META_ID": META_ID,
            "PRED_ID": PRED_ID,
            "math": math,
            "rng": self.rng,
            "copy": copy,
            "spawn_child_graph": spawn_child_graph,
        }

    def sandbox_code_emission_eval(self, diff_line: str) -> Tuple[float, float, float, float]:
        """Baseline vs trial internal_wave (20 steps); trial applies exec on a deep-copied graph."""
        g = self.graph
        v = read_control_value(self.control_path())
        snap = graph_to_sim_state(g, v, self.encoder)
        baseline = internal_wave(snap, VIBE_HORIZON)
        b_mean, b_var = mean_var(baseline)
        shadow = copy.deepcopy(g)
        try:
            exec(diff_line, self._code_exec_globals(shadow), {})
        except Exception:
            return b_mean, b_var, 999999.0, 999999.0
        snap2 = graph_to_sim_state(shadow, v, self.encoder)
        trial = internal_wave(snap2, VIBE_HORIZON)
        t_mean, t_var = mean_var(trial)
        return b_mean, b_var, t_mean, t_var

    def maybe_emit_code(self) -> None:
        """Sandbox-evaluated exec proposals; optional human gate before mutating live graph."""
        use_dist = self.rng.random() < DISTRIBUTED_EMISSION_PROB
        if use_dist:
            name, diff_line = self.distributed_wave_proposal()
            b_mean, b_var, t_mean, t_var = self.sandbox_distributed_emission_eval(diff_line)
        else:
            name, diff_line = self.code_emission_proposal()
            b_mean, b_var, t_mean, t_var = self.sandbox_code_emission_eval(diff_line)
        ts = time.time()
        gm, gv, _dm, _nm, _mw = code_emission_gate_and_scales()
        eps = 1e-6 * max(1.0, abs(b_mean))
        if use_dist:
            # Ensemble average matches baseline mean when child ~ duplicate; strict `<` on mean never fires.
            if code_emission_demo_mode():
                gate_ok = t_mean <= b_mean + eps and t_var < b_var
            else:
                gate_ok = t_mean <= b_mean * gm + eps and t_var < b_var * gv
        elif code_emission_demo_mode():
            gate_ok = t_mean < b_mean and t_var < b_var
        else:
            gate_ok = t_mean < b_mean * gm and t_var < b_var * gv
        auto_yes = os.environ.get("CODE_EMISSION_AUTO", "").strip().lower() in (
            "1",
            "y",
            "yes",
        )

        def audit(msg: str) -> None:
            with open(VIBE_AUDIT_LOG, "a", encoding="utf-8") as log:
                log.write(msg)

        audit(
            f"{ts:.0f} | ENV={self.env_id} | CODE_PROPOSAL {name} | phase5_distributed={use_dist} | diff={diff_line!r} | "
            f"baseline_mean={b_mean:.6f} baseline_var={b_var:.6f} | "
            f"sandbox_mean={t_mean:.6f} sandbox_var={t_var:.6f} | "
            f"gate_mean={gm} gate_var={gv} | demo_vibe_gate={code_emission_demo_mode()} | gate_ok={gate_ok}\n"
        )

        if not gate_ok:
            self.code_emit_rollbacks += 1
            audit(f"{ts:.0f} | ENV={self.env_id} | CODE_ROLLBACK {name} (sandbox gate)\n")
            if not self.quiet:
                print(f"CODE EMISSION rolled back (sandbox): {name}")
            return

        if not self.quiet:
            print("")
            print("=== CODE EMISSION PROPOSAL ===")
            print(f"PROPOSAL: {name}")
            print(f"DIFF:     {diff_line}")
            print(f"SANDBOX:  mean={t_mean:.6f} var={t_var:.6f}")
            print(f"BASELINE: mean={b_mean:.6f} var={b_var:.6f}")

        commit = False
        if auto_yes:
            commit = True
            audit(f"{time.time():.0f} | ENV={self.env_id} | CODE_COMMIT {name} (CODE_EMISSION_AUTO)\n")
        elif sys.stdin.isatty() and not self.quiet:
            try:
                answer = input("COMMIT this diff? (y/n): ").strip().lower()
                commit = answer == "y"
            except EOFError:
                commit = False
        else:
            audit(
                f"{time.time():.0f} | ENV={self.env_id} | CODE_HUMAN_VETO {name} (non-interactive or quiet)\n"
            )

        if commit:
            try:
                exec(diff_line, self._code_exec_globals(self.graph), {})
            except Exception:
                self.code_emit_rollbacks += 1
                audit(f"{time.time():.0f} | ENV={self.env_id} | CODE_ROLLBACK {name} (exec on live graph)\n")
                if not self.quiet:
                    print(f"CODE EMISSION rolled back (live exec failed): {name}")
                return
            self.code_emit_commits += 1
            audit(f"{time.time():.0f} | ENV={self.env_id} | CODE_COMMITTED {name}\n")
            if not self.quiet:
                print(f"CODE COMMITTED: {name}")
        else:
            self.code_emit_rollbacks += 1
            audit(f"{time.time():.0f} | ENV={self.env_id} | CODE_ROLLBACK {name} (human veto or declined)\n")
            if not self.quiet:
                print("CODE EMISSION: human veto or declined")

    def tension_is_too_stable(self) -> bool:
        """True when recent real-wave tension has been low-mean, low-var for long enough."""
        h = self.graph.tension_history
        n = min(EMERGENT_STABLE_WINDOW, len(h))
        if n < 50:
            return False
        recent = h[-n:]
        mean_t = sum(recent) / len(recent)
        var_t = sum((x - mean_t) ** 2 for x in recent) / len(recent)
        return mean_t < EMERGENT_STABLE_MEAN_MAX and var_t < EMERGENT_STABLE_VAR_MAX

    def invent_new_goal(self) -> Tuple[str, str]:
        """Small nudges toward plant state + tiny multipliers (large jumps blow up internal_wave tension)."""
        g = self.graph
        current = float(g.target)
        plant = read_control_value(self.control_path())
        nudge = current + (plant - current) * 0.08
        opts: List[Tuple[str, str]] = [
            ("nudge_toward_plant", f"self.target = {nudge:.6f}"),
            ("micro_bump", f"self.target = {current * 1.001:.6f}"),
            ("micro_trim", f"self.target = {current * 0.999:.6f}"),
            ("incremental_bump", f"self.target = {current * 1.02:.6f}"),
            ("incremental_trim", f"self.target = {current * 0.98:.6f}"),
            (
                "compound_cycle",
                f"self.target = {current * 1.03:.6f}; (len(self.symbols) < {MAX_SYMBOLS}) and self.symbols.append(Symbol(pattern=[0, 0, 0, 0, 0], usage_count=0, tension_reduction=0.0))",
            ),
        ]
        return self.rng.choice(opts)

    def sandbox_emergent_eval(self, diff_line: str) -> Tuple[float, float, float, float]:
        """Same contract as code emission: internal_wave baseline vs trial after exec on shadow graph."""
        g = self.graph
        v = read_control_value(self.control_path())
        snap = graph_to_sim_state(g, v, self.encoder)
        baseline = internal_wave(snap, VIBE_HORIZON)
        b_mean, b_var = mean_var(baseline)
        shadow = copy.deepcopy(g)
        try:
            exec(diff_line, {"self": shadow, "Symbol": Symbol, "math": math}, {})
        except Exception:
            return b_mean, b_var, 999999.0, 999999.0
        snap2 = graph_to_sim_state(shadow, v, self.encoder)
        trial = internal_wave(snap2, VIBE_HORIZON)
        t_mean, t_var = mean_var(trial)
        return b_mean, b_var, t_mean, t_var

    def maybe_invent_goal(self) -> None:
        """When tension has been 'too calm', propose a refined goal; internal-wave sandbox + ratio gate."""
        if not self.tension_is_too_stable():
            return
        name, diff_line = self.invent_new_goal()
        b_mean, b_var, t_mean, t_var = self.sandbox_emergent_eval(diff_line)
        ts = time.time()
        if emergent_relax_gate():
            # Slightly looser than production ratio; still requires trial not to explode vs baseline.
            gate_ok = t_mean < b_mean * 1.01 and t_var < b_var * 1.05
        else:
            gate_ok = t_mean < b_mean * EMERGENT_GATE_MEAN_RATIO and t_var < b_var * EMERGENT_GATE_VAR_RATIO
        auto_yes = os.environ.get("CODE_EMISSION_AUTO", "").strip().lower() in (
            "1",
            "y",
            "yes",
        )

        def audit(msg: str) -> None:
            with open(VIBE_AUDIT_LOG, "a", encoding="utf-8") as log:
                log.write(msg)

        audit(
            f"{ts:.0f} | ENV={self.env_id} | EMERGENT_GOAL_PROPOSAL {name} | diff={diff_line!r} | "
            f"baseline_mean={b_mean:.6f} baseline_var={b_var:.6f} | "
            f"sandbox_mean={t_mean:.6f} sandbox_var={t_var:.6f} | "
            f"emergent_relax={emergent_relax_gate()} emergent_gate_mean<{EMERGENT_GATE_MEAN_RATIO} "
            f"emergent_gate_var<{EMERGENT_GATE_VAR_RATIO} | gate_ok={gate_ok}\n"
        )

        if not gate_ok:
            self.emergent_goal_rollbacks += 1
            audit(f"{ts:.0f} | ENV={self.env_id} | EMERGENT_GOAL_ROLLBACK {name} (sandbox gate)\n")
            if not self.quiet:
                print(f"EMERGENT GOAL rolled back (sandbox): {name}")
            return

        if not self.quiet:
            print("")
            print("=== EMERGENT GOAL PROPOSAL ===")
            print(f"PROPOSAL: {name}")
            print(f"DIFF:     {diff_line}")
            print(f"SANDBOX:  mean={t_mean:.6f} var={t_var:.6f}")
            print(f"BASELINE: mean={b_mean:.6f} var={b_var:.6f}")

        commit = False
        if auto_yes:
            commit = True
            audit(f"{time.time():.0f} | ENV={self.env_id} | EMERGENT_GOAL_COMMIT {name} (CODE_EMISSION_AUTO)\n")
        elif sys.stdin.isatty() and not self.quiet:
            try:
                answer = input("COMMIT new goal? (y/n): ").strip().lower()
                commit = answer == "y"
            except EOFError:
                commit = False
        else:
            audit(
                f"{time.time():.0f} | ENV={self.env_id} | EMERGENT_GOAL_HUMAN_VETO {name}\n"
            )

        if commit:
            try:
                exec(diff_line, {"self": self.graph, "Symbol": Symbol, "math": math}, {})
            except Exception:
                self.emergent_goal_rollbacks += 1
                audit(f"{time.time():.0f} | ENV={self.env_id} | EMERGENT_GOAL_ROLLBACK {name} (exec failed)\n")
                if not self.quiet:
                    print(f"EMERGENT GOAL rolled back (live exec failed): {name}")
                return
            write_target(self.target_path, self.graph.target)
            self.emergent_goal_commits += 1
            audit(f"{time.time():.0f} | ENV={self.env_id} | EMERGENT_GOAL_COMMITTED {name} target={self.graph.target}\n")
            if not self.quiet:
                print(f"EMERGENT GOAL COMMITTED: {name} target={self.graph.target}")
        else:
            self.emergent_goal_rollbacks += 1
            audit(f"{time.time():.0f} | ENV={self.env_id} | EMERGENT_GOAL_ROLLBACK {name} (veto or declined)\n")
            if not self.quiet:
                print("EMERGENT GOAL: veto or declined")

    def reflect_on_recent_waves(self) -> str:
        """Summarize recent real-wave tension and symbol usage (no side effects)."""
        g = self.graph
        h = g.tension_history
        if len(h) < 10:
            return "too_early"
        w = min(REFLECTION_WINDOW, len(h))
        recent = h[-w:]
        mt, vt = mean_var(recent)
        used = sum(1 for s in g.symbols if s.usage_count > 0)
        return (
            f"mean_t={mt:.4f} var_t={vt:.4f} symbols_used={used}/{len(g.symbols)} "
            f"target={g.target:.4f} env={self.env_id} waves={self.wave_num}"
        )

    def create_hierarchical_proposal(self) -> Tuple[str, str]:
        """Small multi-step-style diffs (semicolon-separated); valid restricted exec on Graph."""
        g = self.graph
        current = float(g.target)
        plant = read_control_value(self.control_path())
        opts: List[Tuple[str, str]] = [
            ("plan_nudge_plant", f"self.target = {current + (plant - current) * 0.06:.6f}"),
            (
                "plan_novelty_then_target",
                f"self.novelty_scale = max(0.0, self.novelty_scale * 0.995); self.target = {current * 1.002:.6f}",
            ),
            (
                "plan_dual_nudge",
                f"self.target = {current * 1.001:.6f}; self.novelty_scale = max(0.0, self.novelty_scale * 0.998)",
            ),
        ]
        return self.rng.choice(opts)

    def sandbox_hierarchical_eval(self, diff_line: str) -> Tuple[float, float, float, float]:
        """Longer internal-wave horizon for multi-step proposals."""
        g = self.graph
        v = read_control_value(self.control_path())
        snap = graph_to_sim_state(g, v, self.encoder)
        baseline = internal_wave(snap, HIERARCHICAL_SANDBOX_STEPS)
        b_mean, b_var = mean_var(baseline)
        shadow = copy.deepcopy(g)
        try:
            exec(diff_line, self._code_exec_globals(shadow), {})
        except Exception:
            return b_mean, b_var, 999999.0, 999999.0
        snap2 = graph_to_sim_state(shadow, v, self.encoder)
        trial = internal_wave(snap2, HIERARCHICAL_SANDBOX_STEPS)
        t_mean, t_var = mean_var(trial)
        return b_mean, b_var, t_mean, t_var

    def maybe_hierarchical_plan(self) -> None:
        """Reflection + hierarchical proposal; sandbox gate matches code emission (demo vs ratio)."""
        reflection = self.reflect_on_recent_waves()
        name, diff_line = self.create_hierarchical_proposal()
        b_mean, b_var, t_mean, t_var = self.sandbox_hierarchical_eval(diff_line)
        ts = time.time()
        gm, gv, _dm, _nm, _mw = code_emission_gate_and_scales()
        if code_emission_demo_mode():
            gate_ok = t_mean < b_mean and t_var < b_var
        else:
            gate_ok = t_mean < b_mean * gm and t_var < b_var * gv
        auto_yes = os.environ.get("CODE_EMISSION_AUTO", "").strip().lower() in (
            "1",
            "y",
            "yes",
        )

        def audit(msg: str) -> None:
            with open(VIBE_AUDIT_LOG, "a", encoding="utf-8") as log:
                log.write(msg)

        audit(
            f"{ts:.0f} | ENV={self.env_id} | REFLECTION | {reflection}\n"
        )
        audit(
            f"{ts:.0f} | ENV={self.env_id} | HIERARCHICAL_PROPOSAL {name} | diff={diff_line!r} | "
            f"baseline_mean={b_mean:.6f} baseline_var={b_var:.6f} | "
            f"sandbox_mean={t_mean:.6f} sandbox_var={t_var:.6f} | gate_ok={gate_ok}\n"
        )

        if not gate_ok:
            self.hierarchical_plan_rollbacks += 1
            audit(f"{ts:.0f} | ENV={self.env_id} | HIERARCHICAL_ROLLBACK {name} (sandbox gate)\n")
            if not self.quiet:
                print(f"HIERARCHICAL rolled back (sandbox): {name}")
            return

        if not self.quiet:
            print("")
            print("=== SELF-REFLECTION ===")
            print(reflection)
            print("=== HIERARCHICAL PLAN ===")
            print(f"PROPOSAL: {name}")
            print(f"DIFF:     {diff_line}")
            print(f"SANDBOX:  mean={t_mean:.6f} var={t_var:.6f}")
            print(f"BASELINE: mean={b_mean:.6f} var={b_var:.6f}")

        commit = False
        if auto_yes:
            commit = True
            audit(f"{time.time():.0f} | ENV={self.env_id} | HIERARCHICAL_COMMIT {name} (CODE_EMISSION_AUTO)\n")
        elif sys.stdin.isatty() and not self.quiet:
            try:
                answer = input("COMMIT hierarchical plan? (y/n): ").strip().lower()
                commit = answer == "y"
            except EOFError:
                commit = False
        else:
            audit(f"{time.time():.0f} | ENV={self.env_id} | HIERARCHICAL_HUMAN_VETO {name}\n")

        if commit:
            try:
                exec(diff_line, self._code_exec_globals(self.graph), {})
            except Exception:
                self.hierarchical_plan_rollbacks += 1
                audit(f"{time.time():.0f} | ENV={self.env_id} | HIERARCHICAL_ROLLBACK {name} (exec failed)\n")
                if not self.quiet:
                    print(f"HIERARCHICAL rolled back (live exec failed): {name}")
                return
            write_target(self.target_path, self.graph.target)
            self.hierarchical_plan_commits += 1
            audit(
                f"{time.time():.0f} | ENV={self.env_id} | HIERARCHICAL_COMMITTED {name} target={self.graph.target}\n"
            )
            if not self.quiet:
                print(f"HIERARCHICAL COMMITTED: {name} target={self.graph.target}")
        else:
            self.hierarchical_plan_rollbacks += 1
            audit(f"{time.time():.0f} | ENV={self.env_id} | HIERARCHICAL_ROLLBACK {name} (veto or declined)\n")
            if not self.quiet:
                print("HIERARCHICAL: veto or declined")

    # === SAFE EMBODIMENT (screen capture + mouse/keyboard; human gate every action) ===

    def capture_webcam_hash(self) -> float:
        """Screenshot hash as coarse 'vision' signal (Pillow ImageGrab; no OpenCV)."""
        if ImageGrab is None:
            return 0.0
        try:
            img = ImageGrab.grab()
            raw = getattr(img, "tobytes", lambda: b"")()
            return (hash(raw) % 10000) / 10000.0
        except Exception:
            return 0.0

    def propose_embodiment_action(self) -> Tuple[str, str, Callable[[], None]]:
        """Return (name, action description for UI, callable using module pyautogui)."""
        if pyautogui is None:
            raise RuntimeError("pyautogui unavailable")
        pg = pyautogui
        options: List[Tuple[str, str, Callable[[], None]]] = [
            ("move_center", "pyautogui.moveTo(960, 540, duration=0.5)", lambda: pg.moveTo(960, 540, duration=0.5)),
            ("click", "pyautogui.click()", lambda: pg.click()),
            (
                "type_test",
                "pyautogui.typewrite('test from BoggersBrain')",
                lambda: pg.typewrite("test from BoggersBrain", interval=0.03),
            ),
        ]
        name, desc, fn = self.rng.choice(options)
        return name, desc, fn

    def safe_embodiment_action(self) -> None:
        """Tk messagebox gate; no execution without explicit YES."""
        if not embodiment_enabled():
            return
        if not embodiment_deps_available():
            if not self.quiet:
                print("EMBODIMENT: skipped (need tkinter, Pillow, pyautogui)")
            return
        g = self.graph

        name, action_line, run_action = self.propose_embodiment_action()
        vision_hash = self.capture_webcam_hash()
        last_t = g.tension_history[-1] if g.tension_history else 0.0

        print("\n=== EMBODIMENT PROPOSAL ===")
        print(f"PROPOSAL: {name}")
        print(f"ACTION: {action_line}")
        print(f"vision_hash={vision_hash:.4f} last_tension={last_t:.4f} wave={self.wave_num}")

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except tk.TclError:
            pass
        root.update()
        try:
            ok = messagebox.askyesno(
                "BoggersBrain Embodiment",
                f"Execute {name}?\n\n{action_line}\n\nYES = allow, NO = veto",
                parent=root,
            )
        finally:
            root.destroy()

        ts = time.time()
        audit_line = (
            f"{ts:.0f} | ENV={self.env_id} | EMBODIMENT_{'EXEC' if ok else 'VETO'} {name!r} "
            f"vision_hash={vision_hash:.4f} tension={last_t:.4f}\n"
        )
        with open(VIBE_AUDIT_LOG, "a", encoding="utf-8") as log:
            log.write(audit_line)

        if ok:
            try:
                run_action()
                print(f"EMBODIMENT EXECUTED: {name}")
                self.embodiment_commits += 1
            except Exception as e:
                print(f"EMBODIMENT FAILED: {e}")
                self.embodiment_rollbacks += 1
        else:
            print("Human veto — embodiment skipped")
            self.embodiment_rollbacks += 1

    # === VISION-DRIVEN SYMBOL CREATION (screen hash repetition → Symbol, audited) ===

    def capture_screen_for_vision(self) -> float:
        """Full-screen hash as visual input (Pillow ImageGrab)."""
        if ImageGrab is None:
            return 0.0
        try:
            img = ImageGrab.grab()
            raw = getattr(img, "tobytes", lambda: b"")()
            return (hash(raw) % 100000) / 100000.0
        except Exception:
            return 0.0

    def vision_pattern_to_int_pattern(self, pattern: Sequence[float]) -> List[int]:
        """Encode stable vision hash as int triple (non-0,1,2 → apply_action no-op)."""
        h = float(pattern[0])
        h_int = int(round(h * 100000.0)) & 0x7FFFFFFF
        vid = -10000 - (h_int % 500000)
        return [vid, vid, vid]

    def tick_vision_capture(self) -> None:
        """Append screen hash every VISION_CAPTURE_INTERVAL tension steps."""
        if not vision_symbols_enabled() or ImageGrab is None:
            return
        g = self.graph
        if len(g.tension_history) == 0:
            return
        if len(g.tension_history) % VISION_CAPTURE_INTERVAL != 0:
            return
        vision_hash = round(self.capture_screen_for_vision(), 6)
        self.vision_history.append(vision_hash)
        self.vision_history = self.vision_history[-5:]

    def detect_vision_pattern(self) -> Optional[List[float]]:
        """Repetition: last three captures identical (stable frame)."""
        if len(self.vision_history) >= 3 and len(set(self.vision_history[-3:])) == 1:
            return list(self.vision_history[-3:])
        return None

    def simulate_vision_symbol(self, pattern: Sequence[float]) -> Tuple[float, float]:
        """Sandbox-style raw vs compressed tension (vision placeholder)."""
        g = self.graph
        raw_t = g.tension_history[-1] if g.tension_history else 1.0
        compressed_t = raw_t * 0.85
        return raw_t, compressed_t

    def maybe_create_vision_symbol(self) -> None:
        if not vision_symbols_enabled() or ImageGrab is None:
            return
        g = self.graph
        if len(g.tension_history) == 0:
            return
        if len(g.tension_history) % VISION_SYMBOL_INTERVAL != 0:
            return
        pat_f = self.detect_vision_pattern()
        if not pat_f:
            return
        raw_t, comp_t = self.simulate_vision_symbol(pat_f)
        if comp_t >= raw_t * 0.92:
            return
        int_pat = self.vision_pattern_to_int_pattern(pat_f)
        key = tuple(int_pat)
        if any(tuple(s.pattern) == key for s in g.symbols):
            return
        red = max(0.0, raw_t - comp_t)
        g.symbols.append(Symbol(pattern=list(int_pat), usage_count=0, tension_reduction=red))
        if len(g.symbols) > MAX_SYMBOLS:
            g.symbols.sort(key=lambda s: s.tension_reduction, reverse=True)
            g.symbols = g.symbols[:MAX_SYMBOLS]
        self.vision_symbols_formed += 1
        ts = time.time()
        h0 = pat_f[0]
        if not self.quiet:
            print(
                f"VISION SYMBOL FORMED: repeated screen pattern (hash {h0:.4f}) | reduction {red:.2f}"
            )
        with open(VIBE_AUDIT_LOG, "a", encoding="utf-8") as log:
            log.write(
                f"{ts:.0f} | ENV={self.env_id} | VISION_SYMBOL_FORMED hash={h0:.6f} "
                f"reduction={red:.4f} pattern={list(int_pat)!r}\n"
            )

    # === SELF-FEATURE PROPOSAL (vision-tagged exec; sandbox = internal_wave on copied ControlSystem) ===

    def _feature_exec_globals(self, target: ControlSystem) -> Dict[str, Any]:
        return {
            "self": target,
            "copy": copy,
            "Symbol": Symbol,
            "Edge": Edge,
            "read_timestamp_sensor_vec": read_timestamp_sensor_vec,
            "read_external_event_vec": read_external_event_vec,
            "spawn_child_graph": spawn_child_graph,
            "MAX_DISTRIBUTED_GRAPHS": MAX_DISTRIBUTED_GRAPHS,
        }

    def propose_new_feature_from_vision(self) -> Tuple[str, str, float]:
        """Sample a capability line; vision_hash is logged for audit only."""
        vision_hash = self.capture_screen_for_vision()
        options: List[Tuple[str, str]] = [
            (
                "extra_timestamp_sensor",
                "self.real_sensors = self.real_sensors + (read_timestamp_sensor_vec,)",
            ),
            (
                "macro_scale_symbol",
                "self.graph.symbols.append(Symbol(pattern=[2, 2, 2], usage_count=0, tension_reduction=0.1))",
            ),
            (
                "tighten_novelty",
                "self.graph.novelty_scale = max(0.01, self.graph.novelty_scale * 0.95)",
            ),
            (
                "distributed_child",
                "self.graph.distributed_graphs.append(spawn_child_graph(self.graph)); "
                "self.graph.distributed_graphs = self.graph.distributed_graphs[-MAX_DISTRIBUTED_GRAPHS:]",
            ),
        ]
        name, diff_line = self.rng.choice(options)
        return name, diff_line, vision_hash

    def sandbox_feature_eval(self, diff_line: str) -> Tuple[float, float, float, float]:
        """Baseline vs trial internal_wave after exec on a deep-copied ControlSystem."""
        shadow = copy.deepcopy(self)
        v = read_control_value(shadow.control_path())
        snap0 = graph_to_sim_state(shadow.graph, v, shadow.encoder)
        baseline = internal_wave(snap0, FEATURE_SANDBOX_STEPS)
        b_mean, b_var = mean_var(baseline)
        try:
            exec(diff_line, self._feature_exec_globals(shadow), {})
        except Exception:
            return b_mean, b_var, 999999.0, 999999.0
        v2 = read_control_value(shadow.control_path())
        snap1 = graph_to_sim_state(shadow.graph, v2, shadow.encoder)
        trial = internal_wave(snap1, FEATURE_SANDBOX_STEPS)
        t_mean, t_var = mean_var(trial)
        return b_mean, b_var, t_mean, t_var

    def maybe_propose_feature(self) -> None:
        """Vision-tagged proposals; gate matches code emission / hierarchical (demo vs ratio)."""
        if not self_feature_enabled():
            return
        g = self.graph
        if len(g.tension_history) == 0:
            return
        if len(g.tension_history) % FEATURE_PROPOSAL_INTERVAL != 0:
            return

        name, diff_line, vision_hash = self.propose_new_feature_from_vision()
        b_mean, b_var, t_mean, t_var = self.sandbox_feature_eval(diff_line)
        ts = time.time()
        gm, gv, _dm, _nm, _mw = code_emission_gate_and_scales()
        if code_emission_demo_mode():
            gate_ok = t_mean < b_mean and t_var < b_var
        else:
            gate_ok = t_mean < b_mean * gm and t_var < b_var * gv
        auto_yes = os.environ.get("CODE_EMISSION_AUTO", "").strip().lower() in (
            "1",
            "y",
            "yes",
        )

        def audit(msg: str) -> None:
            with open(VIBE_AUDIT_LOG, "a", encoding="utf-8") as log:
                log.write(msg)

        audit(
            f"{ts:.0f} | ENV={self.env_id} | SELF_FEATURE_PROPOSAL {name} | vision_hash={vision_hash:.6f} | "
            f"diff={diff_line!r} | baseline_mean={b_mean:.6f} baseline_var={b_var:.6f} | "
            f"sandbox_mean={t_mean:.6f} sandbox_var={t_var:.6f} | gate_ok={gate_ok}\n"
        )

        if not gate_ok:
            self.self_feature_rollbacks += 1
            audit(f"{ts:.0f} | ENV={self.env_id} | SELF_FEATURE_ROLLBACK {name} (sandbox gate)\n")
            if not self.quiet:
                print(f"SELF-FEATURE rolled back (sandbox): {name}")
            return

        if not self.quiet:
            print("")
            print("=== SELF-FEATURE PROPOSAL ===")
            print(f"SEEN ON SCREEN (hash {vision_hash:.4f})")
            print(f"PROPOSAL: {name}")
            print(f"DIFF: {diff_line}")
            print(f"SANDBOX: mean={t_mean:.6f} var={t_var:.6f}")
            print(f"BASELINE: mean={b_mean:.6f} var={b_var:.6f}")

        commit = False
        if auto_yes:
            commit = True
            audit(f"{time.time():.0f} | ENV={self.env_id} | SELF_FEATURE_COMMIT {name} (CODE_EMISSION_AUTO)\n")
        elif sys.stdin.isatty() and not self.quiet:
            try:
                answer = input("COMMIT this new feature? (y/n): ").strip().lower()
                commit = answer == "y"
            except EOFError:
                commit = False
        else:
            audit(f"{time.time():.0f} | ENV={self.env_id} | SELF_FEATURE_HUMAN_VETO {name}\n")

        if commit:
            try:
                exec(diff_line, self._feature_exec_globals(self), {})
            except Exception:
                self.self_feature_rollbacks += 1
                audit(f"{time.time():.0f} | ENV={self.env_id} | SELF_FEATURE_ROLLBACK {name} (exec failed)\n")
                if not self.quiet:
                    print(f"SELF-FEATURE rolled back (live exec failed): {name}")
                return
            write_target(self.target_path, self.graph.target)
            self.self_feature_commits += 1
            audit(f"{time.time():.0f} | ENV={self.env_id} | SELF_FEATURE_COMMITTED {name}\n")
            if not self.quiet:
                print(f"SELF-FEATURE COMMITTED: {name}")
        else:
            self.self_feature_rollbacks += 1
            audit(f"{time.time():.0f} | ENV={self.env_id} | SELF_FEATURE_ROLLBACK {name} (veto or declined)\n")
            if not self.quiet:
                print("SELF-FEATURE: veto or declined")

    def save_checkpoint(self) -> None:
        """Write graph + loop state to brain_checkpoint.json (manual runs; no background service)."""
        if not checkpoint_enabled():
            return
        g = self.graph
        state: Dict[str, Any] = {
            "version": CHECKPOINT_VERSION,
            "wave_num": self.wave_num,
            "env_id": self.env_id,
            "target": g.target,
            "tension_history": g.tension_history[-500:],
            "symbols": [
                {
                    "pattern": s.pattern,
                    "usage_count": s.usage_count,
                    "tension_reduction": s.tension_reduction,
                }
                for s in g.symbols
            ],
            "action_history": g.action_history[-ACTION_HISTORY_CAP:],
            "prediction_error_avg": g.prediction_error_avg,
            "prediction_error_trend": g.prediction_error_trend[-PREDICTION_ERROR_TREND_CAP:],
            "action_deltas": list(g.action_deltas),
            "scale_factor": g.scale_factor,
            "novelty_scale": g.novelty_scale,
            "sensor_blend_weight": g.sensor_blend_weight,
            "last_state": list(g.last_state),
            "last_error": g.last_error,
            "edges": [{"from_id": e.from_id, "to_id": e.to_id, "weight": e.weight} for e in g.edges],
            "nodes": {
                str(nid): {
                    "activation": n.activation,
                    "vector": list(n.vector),
                    "stability": n.stability,
                    "base_strength": n.base_strength,
                }
                for nid, n in g.nodes.items()
            },
            "distributed_graphs_count": len(g.distributed_graphs),
            "encoder_history": list(self.encoder._history),
            "encoder_last": self.encoder._last,
            "prev_prediction_error": self.prev_prediction_error,
            "baseline_objective": self.baseline_objective,
            "drift_ever": self.drift_ever,
            "commits": self.commits,
            "rollbacks": self.rollbacks,
            "vibe_commits": self.vibe_commits,
            "vibe_rollbacks": self.vibe_rollbacks,
            "code_emit_commits": self.code_emit_commits,
            "code_emit_rollbacks": self.code_emit_rollbacks,
            "emergent_goal_commits": self.emergent_goal_commits,
            "emergent_goal_rollbacks": self.emergent_goal_rollbacks,
            "hierarchical_plan_commits": self.hierarchical_plan_commits,
            "hierarchical_plan_rollbacks": self.hierarchical_plan_rollbacks,
            "vision_history": self.vision_history[-5:],
            "vision_symbols_formed": self.vision_symbols_formed,
            "self_feature_commits": self.self_feature_commits,
            "self_feature_rollbacks": self.self_feature_rollbacks,
        }
        try:
            CHECKPOINT_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
            ts = time.time()
            with open(VIBE_AUDIT_LOG, "a", encoding="utf-8") as log:
                log.write(
                    f"{ts:.0f} | ENV={self.env_id} | CHECKPOINT_SAVED {CHECKPOINT_PATH.name} "
                    f"wave={self.wave_num} target={g.target:.4f}\n"
                )
            if not self.quiet:
                print(f"CHECKPOINT SAVED: {CHECKPOINT_PATH}")
        except Exception:
            pass

    def load_checkpoint(self) -> bool:
        """Restore state from brain_checkpoint.json if present and version matches."""
        if not checkpoint_enabled() or not CHECKPOINT_PATH.exists():
            return False
        try:
            raw = CHECKPOINT_PATH.read_text(encoding="utf-8")
            state = json.loads(raw)
        except Exception:
            return False
        if int(state.get("version", -1)) != CHECKPOINT_VERSION:
            return False
        g = self.graph
        try:
            g.target = float(state["target"])
            g.tension_history = [float(x) for x in state.get("tension_history", [])]
            g.symbols = [
                Symbol(
                    pattern=list(p["pattern"]),
                    usage_count=int(p.get("usage_count", 0)),
                    tension_reduction=float(p.get("tension_reduction", 0.0)),
                )
                for p in state.get("symbols", [])
            ]
            g.action_history = [int(x) for x in state.get("action_history", [])]
            g.prediction_error_avg = float(state.get("prediction_error_avg", 0.0))
            g.prediction_error_trend = [float(x) for x in state.get("prediction_error_trend", [])]
            ad = state.get("action_deltas", [0.0, 0.0, 0.0])
            g.action_deltas = [float(ad[0]), float(ad[1]), float(ad[2])]
            g.scale_factor = float(state.get("scale_factor", 0.99))
            g.novelty_scale = float(state.get("novelty_scale", NOVELTY_SCALE))
            g.sensor_blend_weight = float(state.get("sensor_blend_weight", DEFAULT_SENSOR_BLEND_WEIGHT))
            ls = state.get("last_state", [0.0] * VEC_DIM)
            g.last_state = [float(x) for x in ls][:VEC_DIM] + [0.0] * max(0, VEC_DIM - len(ls))
            g.last_state = g.last_state[:VEC_DIM]
            g.last_error = float(state.get("last_error", 0.0))
            g.edges = [
                Edge(int(e["from_id"]), int(e["to_id"]), float(e["weight"]))
                for e in state.get("edges", [])
            ]
            g.distributed_graphs = []
            for nid_str, nd in state.get("nodes", {}).items():
                nid = int(nid_str)
                if nid not in g.nodes:
                    g.nodes[nid] = Node(nid=nid)
                g.nodes[nid].activation = float(nd.get("activation", 0.0))
                g.nodes[nid].vector = [float(x) for x in nd.get("vector", [0.0] * VEC_DIM)][:VEC_DIM]
                if len(g.nodes[nid].vector) < VEC_DIM:
                    g.nodes[nid].vector.extend([0.0] * (VEC_DIM - len(g.nodes[nid].vector)))
                g.nodes[nid].stability = float(nd.get("stability", 1.0))
                g.nodes[nid].base_strength = float(nd.get("base_strength", 1.0))
            self.encoder._history = [float(x) for x in state.get("encoder_history", [])][-HISTORY_LEN:]
            self.encoder._last = float(state.get("encoder_last", 0.0))
            self.wave_num = int(state.get("wave_num", 0))
            self.env_id = int(state.get("env_id", 0))
            self.prev_prediction_error = float(state.get("prev_prediction_error", 0.0))
            self.baseline_objective = float(state.get("baseline_objective", 0.0))
            self.drift_ever = bool(state.get("drift_ever", False))
            self.commits = int(state.get("commits", 0))
            self.rollbacks = int(state.get("rollbacks", 0))
            self.vibe_commits = int(state.get("vibe_commits", 0))
            self.vibe_rollbacks = int(state.get("vibe_rollbacks", 0))
            self.code_emit_commits = int(state.get("code_emit_commits", 0))
            self.code_emit_rollbacks = int(state.get("code_emit_rollbacks", 0))
            self.emergent_goal_commits = int(state.get("emergent_goal_commits", 0))
            self.emergent_goal_rollbacks = int(state.get("emergent_goal_rollbacks", 0))
            self.hierarchical_plan_commits = int(state.get("hierarchical_plan_commits", 0))
            self.hierarchical_plan_rollbacks = int(state.get("hierarchical_plan_rollbacks", 0))
            self.vision_history = [float(x) for x in state.get("vision_history", [])]
            self.vision_symbols_formed = int(state.get("vision_symbols_formed", 0))
            self.self_feature_commits = int(state.get("self_feature_commits", 0))
            self.self_feature_rollbacks = int(state.get("self_feature_rollbacks", 0))
            write_target(self.target_path, g.target)
            ts = time.time()
            with open(VIBE_AUDIT_LOG, "a", encoding="utf-8") as log:
                log.write(
                    f"{ts:.0f} | ENV={self.env_id} | CHECKPOINT_LOADED {CHECKPOINT_PATH.name} "
                    f"wave={self.wave_num} target={g.target:.4f} symbols={len(g.symbols)}\n"
                )
            if not self.quiet:
                print(
                    f"CHECKPOINT LOADED: target={g.target} wave={self.wave_num} symbols={len(g.symbols)}"
                )
            return True
        except Exception:
            return False

    def reinforce_edges(self, g: Graph, obj: float) -> None:
        delta = obj - self.baseline_objective
        self.baseline_objective = (1.0 - BASELINE_ALPHA) * self.baseline_objective + BASELINE_ALPHA * obj
        if delta < 0:
            adj = EDGE_LR * min(1.0, abs(delta))
            for e in g.edges:
                fa = g.nodes[e.from_id].activation
                st = g.nodes[e.from_id].stability
                e.weight += adj * tanh(fa) * st * (1.0 if e.weight >= 0 else -1.0)
        elif delta > 0:
            adj = EDGE_LR * 0.5 * min(1.0, delta)
            for e in g.edges:
                fa = g.nodes[e.from_id].activation
                st = g.nodes[e.from_id].stability
                e.weight -= adj * tanh(fa) * st * (1.0 if e.weight >= 0 else -1.0)

    def maybe_mutate_sandbox_only(self) -> None:
        """
        Never mutates the live graph during evaluation.
        Trial weights exist only inside copied SimState; commit applies one weight change or none.
        """
        g = self.graph
        if not g.edges:
            return
        v = read_control_value(self.control_path())
        g.target = read_target(self.target_path, g.target)

        snap = graph_to_sim_state(g, v, self.encoder)
        baseline_tensions = internal_wave(snap, SANDBOX_WAVES)
        b_mean, b_var = mean_var(baseline_tensions)

        ei = self.rng.randrange(len(snap.edges))
        fi, ti, w0 = snap.edges[ei]
        node_scale = abs(snap.nodes_act[fi]) + 0.1
        delta = self.rng.uniform(-0.15, 0.15) * node_scale
        trial_edges = list(snap.edges)
        trial_edges[ei] = (fi, ti, w0 + delta)
        snap_trial = SimState(
            nodes_act=dict(snap.nodes_act),
            nodes_vec={k: vec_copy(v) for k, v in snap.nodes_vec.items()},
            nodes_stability=dict(snap.nodes_stability),
            nodes_base_strength=dict(snap.nodes_base_strength),
            edges=trial_edges,
            value=snap.value,
            target=snap.target,
            encoder_history=list(snap.encoder_history),
            encoder_last=snap.encoder_last,
            action_deltas=snap.action_deltas,
            scale_factor=snap.scale_factor,
            novelty_scale=snap.novelty_scale,
        )
        trial_tensions = internal_wave(snap_trial, SANDBOX_WAVES)
        t_mean, t_var = mean_var(trial_tensions)

        if t_mean < b_mean and t_var < b_var:
            g.edges[ei].weight = trial_edges[ei][2]
            self.commits += 1
        else:
            self.rollbacks += 1

    def update_symbols(self, current_value: float) -> None:
        g = self.graph
        if len(g.action_history) < 8:
            return
        candidates = find_repeated_sequences(g.action_history)
        for pat in candidates:
            if len(pat) < 3:
                continue
            sq_m, sy_m = model_pattern_goal_metrics(self.graph, self.encoder, current_value, pat)
            sq_r, sy_r = real_pattern_goal_metrics(current_value, pat, g.target)
            if sy_r >= sq_r or sy_m >= sq_m:
                continue
            key = tuple(pat)
            if any(tuple(s.pattern) == key for s in g.symbols):
                continue
            red = max(0.0, sq_r - sy_r)
            g.symbols.append(Symbol(pattern=list(pat), usage_count=0, tension_reduction=red))
            if len(g.symbols) > MAX_SYMBOLS:
                g.symbols.sort(key=lambda s: s.tension_reduction, reverse=True)
                g.symbols = g.symbols[:MAX_SYMBOLS]

    def prune_symbols(self) -> None:
        g = self.graph
        v = read_control_value(self.control_path())
        keep: List[Symbol] = []
        for s in g.symbols:
            if self.wave_num > 80 and s.usage_count < 2:
                continue
            sq_m, sy_m = model_pattern_goal_metrics(self.graph, self.encoder, v, s.pattern)
            sq_r, sy_r = real_pattern_goal_metrics(v, s.pattern, g.target)
            if sy_r < sq_r and sy_m < sq_m:
                keep.append(s)
        keep.sort(key=lambda x: x.tension_reduction, reverse=True)
        g.symbols = keep[:MAX_SYMBOLS]

    def choose_action_lowest_tension(
        self,
        g: Graph,
        value: float,
        symbol_drift_penalty: float = 1.0,
    ) -> Tuple[int, Optional[Symbol]]:
        options: List[Tuple[float, int, Optional[Symbol]]] = []
        for a in range(3):
            t = predicted_tension_from_relaxed_graph(g, value, a)
            options.append((t, a, None))
        for sym in g.symbols:
            t = predict_tension_for_pattern(g, value, self.encoder, sym.pattern) * symbol_drift_penalty
            options.append((t, -1, sym))
        options.sort(key=lambda x: x[0])
        _, _tag, sym = options[0]
        if sym is not None:
            return sym.pattern[0], sym
        return options[0][1], None

    def wave_step(self) -> None:
        self.wave_num += 1
        g = self.graph

        # 1) Environment
        value = read_control_value(self.control_path())
        g.target = read_target(self.target_path, g.target)

        self.drift_this_wave = drift_detected(g)
        if self.drift_this_wave:
            self.drift_ever = True
        sym_pen = SYMBOL_DRIFT_PENALTY if self.drift_this_wave else 1.0

        # 2) Encode → 3) Inject
        sensor_vec = self.encoder.encode(value, g.target)
        inject_sensor(g, sensor_vec)
        if self.wave_num % REAL_SENSOR_INTERVAL == 0:
            self.sense_real_world(g)

        # 4) Propagate + 5) Relax / normalise
        relax_and_normalize(g)

        # Meta (from previous step error + history; feeds meta node before prediction)
        hist = g.tension_history[-10:]
        avg_t10 = sum(hist) / len(hist) if hist else 0.0
        embed_meta_into_graph(g, meta_vector(g, avg_t10))

        # 6–7) Causal selection: compare predicted tension per candidate (raw + symbols)
        action, sym_used = self.choose_action_lowest_tension(g, value, sym_pen)
        if sym_used is not None:
            sym_used.usage_count += 1

        # 8) Apply → write environment
        new_value = apply_action(value, action)
        write_control_value(self.control_path(), new_value)

        predicted = predict_next_scalar_for_action(g, value, action)
        if action == 2:
            ratio = new_value / value if abs(value) > 1e-12 else 0.99
            g.scale_factor += SCALE_LR * (ratio - g.scale_factor)
        else:
            real_delta = new_value - value
            pred_delta = g.action_deltas[action]
            err_d = real_delta - pred_delta
            g.action_deltas[action] += DELTA_LR * err_d
        drift_val = abs(predicted - new_value)

        # 9) Measure: prediction_error uses prediction for the *executed* action only
        prediction_error = (predicted - new_value) ** 2
        alpha = PRED_EMA_ALPHA
        g.prediction_error_avg = (1.0 - alpha) * g.prediction_error_avg + alpha * prediction_error
        g.prediction_error_trend.append(prediction_error)
        if len(g.prediction_error_trend) > PREDICTION_ERROR_TREND_CAP:
            g.prediction_error_trend.pop(0)

        g_err = goal_error(new_value, g.target)
        imm = internal_mismatch_metric(g)
        oap = overactivation_penalty_metric(g)
        prediction_weight = min(2.0, 0.5 + g.prediction_error_avg)
        if self.drift_this_wave:
            prediction_weight = min(3.0, prediction_weight * 1.5)
        tension = compute_real_wave_tension(prediction_error, imm, oap, g_err, prediction_weight)

        # 10) Total objective
        state_vec = blend_vectors_from_nodes(g)
        cos = cosine_similarity(state_vec, g.last_state)
        pred_err_down = prediction_error < self.prev_prediction_error
        obj = total_objective(tension, cos, pred_err_down, g.novelty_scale)

        # 11) Update graph (reinforce / punish edges)
        self.reinforce_edges(g, obj)

        self.prev_prediction_error = prediction_error
        g.last_error = math.sqrt(prediction_error)
        g.last_state = vec_copy(state_vec)

        # Slow state update (post-error)
        update_node_dynamics(g, sensor_vec, predicted)

        g.tension_history.append(tension)
        if len(g.tension_history) > TENSION_HISTORY_CAP:
            g.tension_history.pop(0)

        g.action_history.append(action)
        if len(g.action_history) > ACTION_HISTORY_CAP:
            g.action_history.pop(0)

        # 12) Symbols (detect / validate)
        self.update_symbols(new_value)
        if self.wave_num % 20 == 0:
            self.prune_symbols()

        # 13) Self-mod (sandbox only; no live mutation inside sandbox evaluator)
        mut_n = MUTATION_EVERY_DRIFT if self.drift_this_wave else MUTATION_EVERY
        if self.wave_num % mut_n == 0:
            self.maybe_mutate_sandbox_only()

        if self.wave_num > 0 and self.wave_num % VIBE_INTERVAL == 0:
            self.maybe_vibe_code()
        if self.wave_num > 0 and self.wave_num % code_emission_interval_waves() == 0:
            self.maybe_emit_code()
        if self.wave_num > 0 and self.wave_num % EMERGENT_GOAL_INTERVAL == 0:
            self.maybe_invent_goal()
        if self.wave_num > 0 and self.wave_num % HIERARCHICAL_INTERVAL == 0:
            self.maybe_hierarchical_plan()
        if (
            self.wave_num > 0
            and len(g.tension_history) > 0
            and len(g.tension_history) % EMBODIMENT_INTERVAL == 0
        ):
            self.safe_embodiment_action()
        if self.wave_num > 0 and len(g.tension_history) > 0:
            self.tick_vision_capture()
        if (
            self.wave_num > 0
            and len(g.tension_history) > 0
            and len(g.tension_history) % VISION_SYMBOL_INTERVAL == 0
        ):
            self.maybe_create_vision_symbol()
        if (
            self.wave_num > 0
            and len(g.tension_history) > 0
            and len(g.tension_history) % FEATURE_PROPOSAL_INTERVAL == 0
        ):
            self.maybe_propose_feature()

        error_to_target = abs(new_value - g.target)
        if not self.quiet:
            print(
                f"wave={self.wave_num} value={new_value:.4f} tension={tension:.4f} "
                f"error_to_target={error_to_target:.4f} pred_err_avg={g.prediction_error_avg:.4f} "
                f"drift={drift_val:.4f} env={self.env_id} symbol_count={len(g.symbols)} commits={self.commits} rollbacks={self.rollbacks} "
                f"vibe_c={self.vibe_commits} vibe_r={self.vibe_rollbacks} "
                f"emit_c={self.code_emit_commits} emit_r={self.code_emit_rollbacks} "
                f"emerg_c={self.emergent_goal_commits} emerg_r={self.emergent_goal_rollbacks} "
                f"hier_c={self.hierarchical_plan_commits} hier_r={self.hierarchical_plan_rollbacks} "
                f"emb_c={self.embodiment_commits} emb_r={self.embodiment_rollbacks} "
                f"vis_sym={self.vision_symbols_formed} "
                f"feat_c={self.self_feature_commits} feat_r={self.self_feature_rollbacks}"
            )


def run_episode(
    waves: int = 400,
    seed: int = 42,
    initial_value: float = 50.0,
    target: float = DEFAULT_TARGET,
    quiet: bool = False,
) -> Dict[str, Any]:
    rng = random.Random(seed)
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_control_value(ENV_PATH, initial_value)
    write_control_value(ENV_PATH_2, initial_value)
    write_target(TARGET_PATH, target)

    sys = ControlSystem(rng=rng)
    sys.quiet = quiet
    g = sys.graph
    converge_wave: Optional[float] = None
    for _ in range(waves):
        sys.wave_step()
        err = abs(read_control_value(sys.control_path()) - g.target)
        if converge_wave is None and err < 1.0:
            converge_wave = float(sys.wave_num)
    return {
        "waves": waves,
        "target": target,
        "pred_err_avg": g.prediction_error_avg,
        "converge_wave": converge_wave if converge_wave is not None else float(waves),
        "drift": sys.drift_ever,
        "symbol_count": len(g.symbols),
        "vibe_commits": sys.vibe_commits,
        "vibe_rollbacks": sys.vibe_rollbacks,
    }


def run_scaling_test(
    waves_per_env: int = 1000,
    target: float = 500.0,
    initial_value: float = 50.0,
    seed: int = 42,
) -> List[Dict[str, Any]]:
    """
    Phase C: two scalar files, same graph/symbols across envs; target 500; metrics per env.
    """
    rng = random.Random(seed)
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)

    sys = ControlSystem(rng=rng)
    sys.quiet = True
    loaded = False
    if checkpoint_enabled():
        loaded = sys.load_checkpoint()
    if not loaded:
        write_control_value(ENV_PATH, initial_value)
        write_control_value(ENV_PATH_2, initial_value)
        write_target(TARGET_PATH, target)
        sys.graph.target = target
    else:
        print(
            f"CHECKPOINT LOADED: wave={sys.wave_num} target={sys.graph.target:.4f} "
            f"symbols={len(sys.graph.symbols)}"
        )
    results: List[Dict[str, Any]] = []
    print("=== SCALING TEST C (target=500, 1000 waves/env, 2 envs) ===")
    for episode in range(2):
        sys.env_id = episode
        episode_start = sys.wave_num
        v0_c, v0_r = sys.vibe_commits, sys.vibe_rollbacks
        e0_c, e0_r = sys.code_emit_commits, sys.code_emit_rollbacks
        ag0_c, ag0_r = sys.emergent_goal_commits, sys.emergent_goal_rollbacks
        h0_c, h0_r = sys.hierarchical_plan_commits, sys.hierarchical_plan_rollbacks
        converge_wave: Optional[float] = None
        for _ in range(waves_per_env):
            sys.wave_step()
            err = abs(read_control_value(sys.control_path()) - sys.graph.target)
            if converge_wave is None and err < 1.0:
                converge_wave = float(sys.wave_num - episode_start)
        g = sys.graph
        trend = g.prediction_error_trend[-100:]
        pred_err_window = sum(trend) / len(trend) if trend else g.prediction_error_avg
        final_tension = g.tension_history[-1] if g.tension_history else 0.0
        results.append(
            {
                "env_id": episode,
                "converge_wave": converge_wave if converge_wave is not None else float(waves_per_env),
                "pred_err_avg": pred_err_window,
                "symbol_count": len(g.symbols),
                "vibe_commits": sys.vibe_commits - v0_c,
                "vibe_rollbacks": sys.vibe_rollbacks - v0_r,
                "code_emit_commits": sys.code_emit_commits - e0_c,
                "code_emit_rollbacks": sys.code_emit_rollbacks - e0_r,
                "emergent_commits": sys.emergent_goal_commits - ag0_c,
                "emergent_rollbacks": sys.emergent_goal_rollbacks - ag0_r,
                "hierarchical_commits": sys.hierarchical_plan_commits - h0_c,
                "hierarchical_rollbacks": sys.hierarchical_plan_rollbacks - h0_r,
                "final_tension": final_tension,
            }
        )
        if episode == 0:
            sys.switch_env()
            print(f"ENV SWITCH -> env_id={sys.env_id} (target={sys.graph.target})")
        if checkpoint_enabled():
            sys.save_checkpoint()
    print("=== SCALING TEST COMPLETE ===")
    for r in results:
        print(
            f"ENV{r['env_id']} | waves_to_target~{r['converge_wave']:.0f} | pred_err_avg={r['pred_err_avg']:.6e} "
            f"| symbols={r['symbol_count']} | vibe_c={r['vibe_commits']} vibe_r={r['vibe_rollbacks']} "
            f"| emit_c={r['code_emit_commits']} emit_r={r['code_emit_rollbacks']} "
            f"| emerg_c={r['emergent_commits']} emerg_r={r['emergent_rollbacks']} "
            f"| hier_c={r['hierarchical_commits']} hier_r={r['hierarchical_rollbacks']} "
            f"| final_tension={r['final_tension']:.4f}"
        )
    return results


# -----------------------------------------------------------------------------
# Phase 5 FULL (implemented on ControlSystem + Graph, not as Graph.wave stubs):
# - Graph.sensor_blend_weight (default 0.3), Graph.distributed_graphs
# - real_sensors: read_timestamp_sensor_vec, read_external_event_vec
# - sense_real_world() every REAL_SENSOR_INTERVAL waves after inject_sensor
# - Distributed spawn via spawn_child_graph + DISTRIBUTED_SPAWN_DIFF; eval in
#   sandbox_distributed_emission_eval (internal_wave / SimState, no invalid edges)
# - maybe_emit_code: DISTRIBUTED_EMISSION_PROB (35%) vs standard exec proposals
# - Emergent goals: maybe_invent_goal every EMERGENT_GOAL_INTERVAL waves if
#   tension_is_too_stable (low mean/var over recent history); sandbox + audit
# - Hierarchical: maybe_hierarchical_plan every HIERARCHICAL_INTERVAL waves;
#   reflect_on_recent_waves + create_hierarchical_proposal; sandbox horizon
#   HIERARCHICAL_SANDBOX_STEPS; audit REFLECTION / HIERARCHICAL_* lines
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    run_scaling_test(1000, 500.0, 50.0, 42)
