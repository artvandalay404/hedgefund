"""Harness-generated neighbor families and effective-N (ADR-0010 §3).

generate_neighborhood: varies each period parameter ±1 step, caps at K_MAX.
The neighbor family is deterministic (same theory → same neighbors), bounded,
and ungameable — the LLM cannot influence which neighbors are generated.

participation_ratio: N_eff = (Σλ)² / Σλ² over return-correlation eigenvalues.
Charges the family as ~1 effective trial rather than K (they are correlated
by construction).  Full population-wide 1−R² accounting → #26.
"""
from __future__ import annotations

import json
import random
from typing import Any

import numpy as np

from hedgefund.quant_research.dsl import PrimitiveSide, StrategySpec
from hedgefund.quant_research.registry import REGISTRY

K_MAX = 9


def generate_neighborhood(spec: StrategySpec, k_max: int = K_MAX) -> list[StrategySpec]:
    """Return up to k_max neighboring specs (period params varied ±1 step)."""
    params: list[tuple[str, int]] = []
    for pred in spec.entry.predicates:
        for side in (pred.lhs, pred.rhs):
            if isinstance(side, PrimitiveSide) and side.primitive.period is not None:
                key = (side.primitive.name, side.primitive.period)
                if key not in params:
                    params.append(key)

    neighbors: list[StrategySpec] = []
    for name, period in params:
        step = REGISTRY[name].step if name in REGISTRY and REGISTRY[name].step > 0 else 1
        for delta in (-step, step):
            new_period = period + delta
            if new_period < 2:
                continue
            neighbors.append(_replace_period(spec, name, period, new_period))

    if len(neighbors) > k_max:
        rng = random.Random(hash(spec.name) & 0xFFFF_FFFF)
        neighbors = rng.sample(neighbors, k_max)

    return neighbors


def participation_ratio(return_vectors: list[list[float]]) -> float:
    """Effective-N via the participation ratio of return-correlation eigenvalues.

    Returns a value in [1, K] where K = number of vectors.  A tightly
    correlated family scores near 1; uncorrelated configs score near K.
    """
    valid = [v for v in return_vectors if len(v) > 1]
    if len(valid) <= 1:
        return 1.0

    matrix = np.array(valid, dtype=float)
    stds = np.std(matrix, axis=1)
    matrix = matrix[stds > 1e-10]
    if len(matrix) <= 1:
        return 1.0

    corr = np.corrcoef(matrix)
    eigs = np.linalg.eigvalsh(corr)
    eigs = eigs[eigs > 1e-10]
    if len(eigs) == 0:
        return 1.0

    return float(eigs.sum() ** 2 / (eigs ** 2).sum())


# ── helpers ──────────────────────────────────────────────────────────────────

def _replace_period(
    spec: StrategySpec, name: str, old_period: int, new_period: int
) -> StrategySpec:
    data = json.loads(spec.model_dump_json(by_alias=True))
    _walk(data, name, old_period, new_period)
    return StrategySpec.model_validate(data)


def _walk(obj: Any, name: str, old: int, new: int) -> None:
    if isinstance(obj, dict):
        if obj.get("name") == name and obj.get("period") == old:
            obj["period"] = new
        for v in obj.values():
            _walk(v, name, old, new)
    elif isinstance(obj, list):
        for item in obj:
            _walk(item, name, old, new)
