#!/usr/bin/env python3
"""Solve air_cargo_stochastic_order_allocation from scratch with PySCIPOpt.

Formulation is documented in model.md. This deterministic-equivalent MIP
mirrors tests/evaluate_solution.py exactly (same net_order_value, same
carbon-penalty and priority-tail-penalty definitions) so the objective
reported by SCIP should match the evaluator's `profit` field.
"""
from __future__ import annotations

import csv
import json
import os
import time
from collections import defaultdict
from pathlib import Path

from pyscipopt import Model, quicksum

APP_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = APP_DIR / "data"
SUB_DIR = APP_DIR / "submissions"

GAP = float(os.environ.get("ORCLAW_SCIP_GAP", "0.0005"))
TIME_LIMIT = min(300.0, float(os.environ.get("ORCLAW_SOLVE_TIME_LIMIT_SECONDS", "300")))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def truthy(row: dict[str, str], field: str) -> bool:
    return int(row[field]) == 1


def load_data() -> dict:
    aircraft = {r["aircraft_id"]: r for r in read_csv(DATA_DIR / "aircraft.csv")}
    orders = {r["order_id"]: r for r in read_csv(DATA_DIR / "orders.csv")}
    scenarios = {r["scenario_id"]: r for r in read_csv(DATA_DIR / "scenarios.csv")}
    capacity = {
        (r["scenario_id"], r["aircraft_id"]): r
        for r in read_csv(DATA_DIR / "scenario_aircraft_capacity.csv")
    }
    show_rows = read_csv(DATA_DIR / "scenario_order_show.csv")
    show = {}
    for row in show_rows:
        sid = row["scenario_id"]
        for oid in orders:
            show[sid, oid] = int(row[oid])
    segment_rules = {
        r["customer_segment"]: float(r["min_expected_service_rate"])
        for r in read_csv(DATA_DIR / "segment_rules.csv")
    }
    ramp_team = {r["aircraft_id"]: r for r in read_csv(DATA_DIR / "aircraft_ramp_team.csv")}
    ramp_capacity = {
        (r["scenario_id"], r["ramp_team"]): r
        for r in read_csv(DATA_DIR / "scenario_ramp_team_capacity.csv")
    }
    config = json.loads((DATA_DIR / "config.json").read_text(encoding="utf-8"))
    return {
        "aircraft": aircraft,
        "orders": orders,
        "scenarios": scenarios,
        "capacity": capacity,
        "show": show,
        "segment_rules": segment_rules,
        "ramp_team": ramp_team,
        "ramp_capacity": ramp_capacity,
        "config": config,
    }


def net_order_value(order: dict[str, str], aircraft: dict[str, str]) -> float:
    delay_hours = max(0.0, float(aircraft["transit_hours"]) - float(order["due_hours"]))
    return (
        float(order["revenue"])
        - float(order["handling_cost"])
        - float(order["weight_kg"]) * float(aircraft["cost_per_kg"])
        - delay_hours * float(order["late_penalty_per_hour"])
    )


def eligible_aircraft(order: dict[str, str], aircraft: dict[str, dict[str, str]]) -> list[str]:
    out = []
    for aid, a in aircraft.items():
        if order["route_id"] != a["route_id"]:
            continue
        if truthy(order, "cold_chain") and not truthy(a, "cold_chain_capable"):
            continue
        if truthy(order, "hazmat") and not truthy(a, "hazmat_allowed"):
            continue
        if truthy(order, "requires_widebody") and not truthy(a, "widebody"):
            continue
        out.append(aid)
    return out


def build_and_solve(data: dict):
    orders = data["orders"]
    aircraft = data["aircraft"]
    scenarios = data["scenarios"]
    show = data["show"]
    capacity = data["capacity"]
    segment_rules = data["segment_rules"]
    ramp_team = data["ramp_team"]
    ramp_capacity = data["ramp_capacity"]
    config = data["config"]

    tol = float(config["feasibility_tolerance"])
    carbon_pen = float(config["carbon_penalty_per_kg"])
    tail_pen = float(config["priority_tail_penalty"])

    teams = sorted({r["ramp_team"] for r in ramp_team.values()})
    aircraft_by_team = defaultdict(list)
    for aid, r in ramp_team.items():
        aircraft_by_team[r["ramp_team"]].append(aid)

    elig = {oid: eligible_aircraft(o, aircraft) for oid, o in orders.items()}
    value = {
        (oid, aid): net_order_value(orders[oid], aircraft[aid])
        for oid, ks in elig.items()
        for aid in ks
    }

    m = Model("air_cargo_stochastic_order_allocation")
    m.setParam("limits/gap", GAP)
    m.setParam("limits/time", TIME_LIMIT)
    m.setParam("display/verblevel", 4)

    x = {}
    for oid, ks in elig.items():
        for aid in ks:
            x[oid, aid] = m.addVar(vtype="B", name=f"x[{oid},{aid}]")

    # (a) at most one aircraft per order
    for oid, ks in elig.items():
        if ks:
            m.addCons(quicksum(x[oid, aid] for aid in ks) <= 1, name=f"one_aircraft[{oid}]")

    carbon = {
        (sid, aid): m.addVar(vtype="C", lb=0.0, name=f"carbon[{sid},{aid}]")
        for sid in scenarios
        for aid in aircraft
    }
    shortfall = {sid: m.addVar(vtype="C", lb=0.0, name=f"shortfall[{sid}]") for sid in scenarios}
    T = m.addVar(vtype="C", lb=0.0, name="T")

    for sid in scenarios:
        for aid, a in aircraft.items():
            cap = capacity[sid, aid]
            max_w = float(a["weight_capacity_kg"]) * float(cap["weight_factor"])
            max_v = float(a["volume_capacity_cbm"]) * float(cap["volume_factor"])
            loaded_w = quicksum(
                show[sid, oid] * float(orders[oid]["weight_kg"]) * x[oid, aid]
                for oid, ks in elig.items()
                if aid in ks
            )
            loaded_v = quicksum(
                show[sid, oid] * float(orders[oid]["volume_cbm"]) * x[oid, aid]
                for oid, ks in elig.items()
                if aid in ks
            )
            m.addCons(loaded_w <= max_w, name=f"wcap[{sid},{aid}]")
            m.addCons(loaded_v <= max_v, name=f"vcap[{sid},{aid}]")

            cold_count = quicksum(
                show[sid, oid] * x[oid, aid]
                for oid, ks in elig.items()
                if aid in ks and truthy(orders[oid], "cold_chain")
            )
            m.addCons(cold_count <= float(a["max_cold_chain_orders"]), name=f"coldcap[{sid},{aid}]")

            m.addCons(
                carbon[sid, aid]
                >= carbon_pen * (float(a["carbon_kg_per_kg"]) * loaded_w - float(a["carbon_allowance_kg"])),
                name=f"carbon_def[{sid},{aid}]",
            )

        for t in teams:
            cap = ramp_capacity[sid, t]
            aids = aircraft_by_team[t]
            uld_minutes = quicksum(
                show[sid, oid] * float(orders[oid]["volume_cbm"]) * float(ramp_team[aid]["uld_build_minutes_per_cbm"]) * x[oid, aid]
                for aid in aids
                for oid, ks in elig.items()
                if aid in ks
            )
            cold_slots = quicksum(
                show[sid, oid] * float(ramp_team[aid]["cold_chain_slots_per_order"]) * x[oid, aid]
                for aid in aids
                for oid, ks in elig.items()
                if aid in ks and truthy(orders[oid], "cold_chain")
            )
            hazmat_minutes = quicksum(
                show[sid, oid] * float(ramp_team[aid]["hazmat_screening_minutes_per_order"]) * x[oid, aid]
                for aid in aids
                for oid, ks in elig.items()
                if aid in ks and truthy(orders[oid], "hazmat")
            )
            m.addCons(uld_minutes <= float(cap["uld_build_minutes_capacity"]), name=f"uld[{sid},{t}]")
            m.addCons(cold_slots <= float(cap["cold_chain_slot_capacity"]), name=f"coldslot[{sid},{t}]")
            m.addCons(hazmat_minutes <= float(cap["hazmat_screening_minutes_capacity"]), name=f"hazmin[{sid},{t}]")

        shortfall_expr = quicksum(
            show[sid, oid] * float(orders[oid]["priority_weight"]) * (1 - quicksum(x[oid, aid] for aid in ks))
            for oid, ks in elig.items()
            if ks
        )
        # orders with no eligible aircraft always count fully toward shortfall when they show
        shortfall_expr += quicksum(
            show[sid, oid] * float(orders[oid]["priority_weight"])
            for oid, ks in elig.items()
            if not ks
        )
        m.addCons(shortfall[sid] == shortfall_expr, name=f"shortfall_def[{sid}]")
        m.addCons(T >= shortfall[sid], name=f"tail[{sid}]")

    # (j) segment expected service-rate floor
    expected_seg_weight = defaultdict(float)
    for oid, o in orders.items():
        seg = o["customer_segment"]
        exp_show = sum(float(scenarios[sid]["probability"]) * show[sid, oid] for sid in scenarios)
        expected_seg_weight[seg] += exp_show * float(o["weight_kg"])

    for seg, floor in segment_rules.items():
        if floor <= 0 or expected_seg_weight[seg] <= tol:
            continue
        lhs_terms = []
        for oid, o in orders.items():
            if o["customer_segment"] != seg:
                continue
            ks = elig[oid]
            if not ks:
                continue
            exp_show = sum(float(scenarios[sid]["probability"]) * show[sid, oid] for sid in scenarios)
            w = float(o["weight_kg"])
            for aid in ks:
                lhs_terms.append(exp_show * w * x[oid, aid])
        m.addCons(
            quicksum(lhs_terms) >= floor * expected_seg_weight[seg],
            name=f"service_floor[{seg}]",
        )

    # objective
    obj_terms = []
    for sid, sc in scenarios.items():
        prob = float(sc["probability"])
        scenario_terms = []
        for oid, ks in elig.items():
            o = orders[oid]
            if not ks:
                # never accepted; if it shows, always incurs lost-booking penalty
                scenario_terms.append(-show[sid, oid] * float(o["lost_booking_penalty"]))
                continue
            for aid in ks:
                scenario_terms.append(show[sid, oid] * value[oid, aid] * x[oid, aid])
            not_accepted = 1 - quicksum(x[oid, aid] for aid in ks)
            scenario_terms.append(-show[sid, oid] * float(o["lost_booking_penalty"]) * not_accepted)
        scenario_terms.append(-quicksum(carbon[sid, aid] for aid in aircraft))
        obj_terms.append(prob * quicksum(scenario_terms))

    m.setObjective(quicksum(obj_terms) - tail_pen * T, "maximize")

    start = time.time()
    m.optimize()
    elapsed = time.time() - start

    status = m.getStatus()
    result = {
        "status": status,
        "elapsed_sec": elapsed,
        "time_limit": TIME_LIMIT,
        "gap_setting": GAP,
    }
    if m.getNSols() > 0:
        result["objective"] = m.getObjVal()
        result["dual_bound"] = m.getDualbound()
        try:
            result["gap"] = m.getGap()
        except Exception:
            result["gap"] = None
        assignments = []
        for (oid, aid), var in x.items():
            if m.getVal(var) > 0.5:
                assignments.append((oid, aid))
        result["assignments"] = assignments
    else:
        result["assignments"] = []

    return result


def write_solution(assignments: list[tuple[str, str]]) -> Path:
    path = SUB_DIR / "solution.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["row_type", "order_id", "aircraft_id", "value"])
        for oid, aid in sorted(assignments):
            writer.writerow(["assign", oid, aid, 1])
    return path


def main() -> None:
    data = load_data()
    result = build_and_solve(data)

    sol_path = write_solution(result["assignments"])

    log_lines = [
        "# Solve Log",
        "",
        f"Command: `python {Path(__file__).name}`",
        "",
        f"- SCIP status: `{result['status']}`",
        f"- Time limit used: {result['time_limit']} s (ORCLAW_SOLVE_TIME_LIMIT_SECONDS honored, capped at 300s)",
        f"- Relative gap setting: {result['gap_setting']}",
        f"- Elapsed wall time: {result['elapsed_sec']:.2f} s",
    ]
    if "objective" in result:
        log_lines += [
            f"- Objective (profit): {result['objective']:.8f}",
            f"- Dual bound: {result['dual_bound']:.8f}",
            f"- Reported gap: {result.get('gap')}",
            f"- Accepted orders: {len(result['assignments'])}",
        ]
    else:
        log_lines.append("- No incumbent solution found.")

    log_lines += [
        "",
        f"Solution written to `{sol_path}` with schema `row_type,order_id,aircraft_id,value`.",
    ]

    (SUB_DIR / "solve_log.md").write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    print("\n".join(log_lines))


if __name__ == "__main__":
    main()
