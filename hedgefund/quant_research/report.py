"""AuthoringReport: the result of one author_strategy.py run (ADR-0009)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from hedgefund.quant_research.dsl import PrimitiveSide, StrategySpec


@dataclass
class AuthoringReport:
    spec: StrategySpec
    wf_summary: dict[str, Any]
    neighborhood_effective_n: float
    cumulative_search_n: float
    passes_gate: bool
    status: str  # "FROZEN — eligible for holdout" | "FAIL — refine in-sample"

    def print_report(self) -> None:
        s = self.wf_summary
        er = self.spec.exit_rule
        r = self.spec.rationale

        print("\n" + "=" * 62)
        print("AUTHORING REPORT")
        print("=" * 62)
        print(f"Strategy:    {self.spec.name}")
        print(f"Direction:   {self.spec.direction}")
        print()
        print("Entry:")
        for pred in self.spec.entry.predicates:
            print(f"  {_pred_str(pred)}")
        print(f"  Logic:     {self.spec.entry.logic}")
        print()
        print("Exit:")
        print(f"  Stop:      {er.stop.kind}({er.stop.value})")
        print(f"  R/R:       {er.reward_risk}×")
        if er.max_hold_days:
            print(f"  Max hold:  {er.max_hold_days} days")
        print()
        print("Rationale:")
        print(f"  Mechanism:         {r.mechanism}")
        print(f"  Why not arb'd:     {r.why_not_arbitraged}")
        print(f"  What breaks it:    {r.what_would_break_it}")
        print(f"  Known anomaly:     {r.known_anomaly_disclosure}")
        print()
        print("Walk-forward results:")
        print(f"  OOS mean Sharpe:   {s.get('oos_mean_sharpe', float('nan')):.3f}")
        print(f"  PSR:               {s.get('psr', float('nan')):.3f}")
        print(f"  DSR:               {s.get('dsr', float('nan')):.3f}")
        print(f"  PBO:               {s.get('pbo', float('nan')):.3f}")
        print(f"  Folds:             {s.get('n_folds', 0)}")
        if s.get("best_params"):
            print(f"  Best params:       {json.dumps(s['best_params'])}")
        print()
        print(f"Neighbourhood eff-N:  {self.neighborhood_effective_n:.2f}")
        print(f"Cumulative search-N:  {self.cumulative_search_n:.0f}")
        print()
        print(f"Gate:    {'PASS' if self.passes_gate else 'FAIL'}")
        print(f"Status:  {self.status}")
        print("=" * 62)


def _pred_str(pred) -> str:
    def _side(s) -> str:
        if isinstance(s, (int, float)):
            return str(s)
        assert isinstance(s, PrimitiveSide)
        n = s.primitive.name
        p = f"({s.primitive.period})" if s.primitive.period is not None else ""
        sc = f" * {s.scale}" if s.scale != 1.0 else ""
        return f"{n}{p}{sc}"
    return f"{_side(pred.lhs)} {pred.op} {_side(pred.rhs)}"
