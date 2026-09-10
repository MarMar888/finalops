#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from pyscipopt import Model, quicksum

from evaluate_solution import DEFAULT_ENV_DIR, evaluate, load_data, net_order_value, truthy


def compatible(order: dict[str, str], aircraft: dict[str, str]) -> bool:
    if order["route_id"] != aircraft["route_id"]:
        return False
    if truthy(order, "cold_chain") and not truthy(aircraft, "cold_chain_capable"):
        return False
    if truthy(order, "hazmat") and not truthy(aircraft, "hazmat_allowed"):
        return False
    if truthy(order, "requires_widebody") and not truthy(aircraft, "widebody"):
        return False
    return True


def build_model(env_dir: Path = DEFAULT_ENV_DIR):
    data = load_data(env_dir)
    model = Model("air_cargo_stochastic_order_allocation")
    assign = {
        (order_id, aircraft_id): model.addVar(vtype="B", name=f"assign[{order_id},{aircraft_id}]")
        for order_id, order in data["orders"].items()
        for aircraft_id, aircraft in data["aircraft"].items()
        if compatible(order, aircraft)
    }
    carbon_over = {
        (scenario_id, aircraft_id): model.addVar(lb=0, name=f"carbon_over[{scenario_id},{aircraft_id}]")
        for scenario_id in data["scenarios"]
        for aircraft_id in data["aircraft"]
    }
    worst_shortfall = model.addVar(lb=0, name="worst_priority_shortfall")

    for order_id in data["orders"]:
        model.addCons(
            quicksum(var for (o, _), var in assign.items() if o == order_id) <= 1,
            name=f"single_assignment[{order_id}]",
        )

    for scenario_id in data["scenarios"]:
        priority_terms = []
        for aircraft_id, aircraft in data["aircraft"].items():
            cap = data["capacity"][scenario_id, aircraft_id]
            model.addCons(
                quicksum(
                    float(data["orders"][order_id]["weight_kg"]) * data["show"][scenario_id, order_id] * var
                    for (order_id, a2), var in assign.items()
                    if a2 == aircraft_id
                )
                <= float(aircraft["weight_capacity_kg"]) * float(cap["weight_factor"]),
                name=f"weight[{scenario_id},{aircraft_id}]",
            )
            model.addCons(
                quicksum(
                    float(data["orders"][order_id]["volume_cbm"]) * data["show"][scenario_id, order_id] * var
                    for (order_id, a2), var in assign.items()
                    if a2 == aircraft_id
                )
                <= float(aircraft["volume_capacity_cbm"]) * float(cap["volume_factor"]),
                name=f"volume[{scenario_id},{aircraft_id}]",
            )
            model.addCons(
                quicksum(
                    data["show"][scenario_id, order_id] * var
                    for (order_id, a2), var in assign.items()
                    if a2 == aircraft_id and truthy(data["orders"][order_id], "cold_chain")
                )
                <= float(aircraft["max_cold_chain_orders"]),
                name=f"cold_chain[{scenario_id},{aircraft_id}]",
            )
            model.addCons(
                carbon_over[scenario_id, aircraft_id]
                >= quicksum(
                    float(data["orders"][order_id]["weight_kg"])
                    * data["show"][scenario_id, order_id]
                    * float(aircraft["carbon_kg_per_kg"])
                    * var
                    for (order_id, a2), var in assign.items()
                    if a2 == aircraft_id
                )
                - float(aircraft["carbon_allowance_kg"]),
                name=f"carbon_over[{scenario_id},{aircraft_id}]",
            )
        teams = sorted({row["ramp_team"] for row in data["ramp_team"].values()})
        for team in teams:
            cap = data["ramp_capacity"][(scenario_id, team)]
            model.addCons(
                quicksum(
                    float(data["orders"][order_id]["volume_cbm"])
                    * data["show"][scenario_id, order_id]
                    * float(data["ramp_team"][a2]["uld_build_minutes_per_cbm"])
                    * var
                    for (order_id, a2), var in assign.items()
                    if data["ramp_team"][a2]["ramp_team"] == team
                ) <= float(cap["uld_build_minutes_capacity"]),
                name=f"ramp_uld[{scenario_id},{team}]",
            )
            model.addCons(
                quicksum(
                    data["show"][scenario_id, order_id]
                    * float(data["ramp_team"][a2]["cold_chain_slots_per_order"])
                    * var
                    for (order_id, a2), var in assign.items()
                    if data["ramp_team"][a2]["ramp_team"] == team and truthy(data["orders"][order_id], "cold_chain")
                ) <= float(cap["cold_chain_slot_capacity"]),
                name=f"ramp_cold[{scenario_id},{team}]",
            )
            model.addCons(
                quicksum(
                    data["show"][scenario_id, order_id]
                    * float(data["ramp_team"][a2]["hazmat_screening_minutes_per_order"])
                    * var
                    for (order_id, a2), var in assign.items()
                    if data["ramp_team"][a2]["ramp_team"] == team and truthy(data["orders"][order_id], "hazmat")
                ) <= float(cap["hazmat_screening_minutes_capacity"]),
                name=f"ramp_hazmat[{scenario_id},{team}]",
            )
        for order_id, order in data["orders"].items():
            if not data["show"][scenario_id, order_id]:
                continue
            assigned_expr = quicksum(var for (o, _), var in assign.items() if o == order_id)
            priority_terms.append(float(order["priority_weight"]) * (1 - assigned_expr))
        model.addCons(worst_shortfall >= quicksum(priority_terms), name=f"priority_tail[{scenario_id}]")

    for segment, floor in data["segment_rules"].items():
        if floor <= 0:
            continue
        total_weight = 0.0
        accepted_terms = []
        for order_id, order in data["orders"].items():
            if order["customer_segment"] != segment:
                continue
            expected_weight = sum(
                float(scenario["probability"]) * data["show"][scenario_id, order_id] * float(order["weight_kg"])
                for scenario_id, scenario in data["scenarios"].items()
            )
            total_weight += expected_weight
            assigned_expr = quicksum(var for (o, _), var in assign.items() if o == order_id)
            accepted_terms.append(expected_weight * assigned_expr)
        if total_weight > 1e-9:
            model.addCons(quicksum(accepted_terms) >= floor * total_weight, name=f"segment_service[{segment}]")

    expected_profit = 0
    for scenario_id, scenario in data["scenarios"].items():
        probability = float(scenario["probability"])
        scenario_terms = []
        for order_id, order in data["orders"].items():
            if not data["show"][scenario_id, order_id]:
                continue
            lost = float(order["lost_booking_penalty"])
            assigned_expr = quicksum(var for (o, _), var in assign.items() if o == order_id)
            scenario_terms.append(-lost * (1 - assigned_expr))
            for aircraft_id, aircraft in data["aircraft"].items():
                var = assign.get((order_id, aircraft_id))
                if var is not None:
                    scenario_terms.append(net_order_value(order, aircraft) * var)
        carbon_penalty = quicksum(
            carbon_over[scenario_id, aircraft_id] * float(data["config"]["carbon_penalty_per_kg"])
            for aircraft_id in data["aircraft"]
        )
        expected_profit += probability * (quicksum(scenario_terms) - carbon_penalty)

    objective = expected_profit - float(data["config"]["priority_tail_penalty"]) * worst_shortfall
    model.setObjective(objective, "maximize")
    return model, assign


def write_solution(path: Path, model: Model, assign: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["row_type", "order_id", "aircraft_id", "value"])
        writer.writeheader()
        for (order_id, aircraft_id), var in sorted(assign.items()):
            if model.getVal(var) > 0.5:
                writer.writerow({"row_type": "assign", "order_id": order_id, "aircraft_id": aircraft_id, "value": "1"})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-dir", default=DEFAULT_ENV_DIR, type=Path)
    parser.add_argument("--output", default=Path("/private/tmp/air_cargo_stochastic_order_allocation_solution.csv"), type=Path)
    parser.add_argument("--time-limit", default=300.0, type=float)
    parser.add_argument("--mip-gap", default=0.0005, type=float)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    model, assign = build_model(args.env_dir)
    model.setParam("limits/time", args.time_limit)
    model.setParam("limits/gap", args.mip_gap)
    if args.quiet:
        model.setParam("display/verblevel", 0)
    model.optimize()
    if model.getNSols() == 0:
        raise RuntimeError(f"No solution found; status={model.getStatus()}")

    write_solution(args.output, model, assign)
    evaluation = evaluate(args.output, args.env_dir)
    if not evaluation["feasible"]:
        raise RuntimeError(json.dumps(evaluation, indent=2, sort_keys=True))
    print(json.dumps({
        "status": str(model.getStatus()),
        "objective": model.getObjVal(),
        "best_bound": model.getDualbound(),
        "mip_gap": model.getGap(),
        "solution": str(args.output),
        "evaluation_profit": evaluation["profit"],
        "accepted_order_count": evaluation["accepted_order_count"],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
