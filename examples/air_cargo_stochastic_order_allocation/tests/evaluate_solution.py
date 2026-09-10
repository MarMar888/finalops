#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path

ENV_NAME = "air_cargo_stochastic_order_allocation"
_THIS_FILE = Path(__file__).resolve()
if len(_THIS_FILE.parents) > 3:
    REPO_ROOT = _THIS_FILE.parents[3]
    DEFAULT_ENV_DIR = REPO_ROOT / "agent_envs" / ENV_NAME
else:
    REPO_ROOT = Path("/")
    DEFAULT_ENV_DIR = Path("/app")
COLUMNS = ["row_type", "order_id", "aircraft_id", "value"]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_data(env_dir: Path = DEFAULT_ENV_DIR) -> dict:
    data_dir = env_dir / "data"
    aircraft = {r["aircraft_id"]: r for r in read_csv(data_dir / "aircraft.csv")}
    orders = {r["order_id"]: r for r in read_csv(data_dir / "orders.csv")}
    scenarios = {r["scenario_id"]: r for r in read_csv(data_dir / "scenarios.csv")}
    capacity = {
        (r["scenario_id"], r["aircraft_id"]): r
        for r in read_csv(data_dir / "scenario_aircraft_capacity.csv")
    }
    show_rows = read_csv(data_dir / "scenario_order_show.csv")
    show = {}
    for row in show_rows:
        scenario_id = row["scenario_id"]
        for order_id in orders:
            show[scenario_id, order_id] = int(row[order_id])
    segment_rules = {
        r["customer_segment"]: float(r["min_expected_service_rate"])
        for r in read_csv(data_dir / "segment_rules.csv")
    }
    ramp_team = {r["aircraft_id"]: r for r in read_csv(data_dir / "aircraft_ramp_team.csv")}
    ramp_capacity = {
        (r["scenario_id"], r["ramp_team"]): r
        for r in read_csv(data_dir / "scenario_ramp_team_capacity.csv")
    }
    config = json.loads((data_dir / "config.json").read_text(encoding="utf-8"))
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


def truthy(row: dict[str, str], field: str) -> bool:
    return int(row[field]) == 1


def net_order_value(order: dict[str, str], aircraft: dict[str, str]) -> float:
    delay_hours = max(0.0, float(aircraft["transit_hours"]) - float(order["due_hours"]))
    return (
        float(order["revenue"])
        - float(order["handling_cost"])
        - float(order["weight_kg"]) * float(aircraft["cost_per_kg"])
        - delay_hours * float(order["late_penalty_per_hour"])
    )


def evaluate(solution_path: Path, env_dir: Path = DEFAULT_ENV_DIR) -> dict:
    data = load_data(env_dir)
    tol = float(data["config"]["feasibility_tolerance"])
    errors: list[str] = []
    assigned: dict[str, str] = {}
    seen: set[tuple[str, str, str]] = set()

    try:
        with solution_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames != COLUMNS:
                return {
                    "environment": ENV_NAME,
                    "feasible": False,
                    "errors": [f"Solution columns must be exactly {COLUMNS}"],
                    "error_count": 1,
                }
            for line, row in enumerate(reader, start=2):
                rt = row["row_type"].strip()
                order_id = row["order_id"].strip()
                aircraft_id = row["aircraft_id"].strip()
                key = (rt, order_id, aircraft_id)
                if key in seen:
                    errors.append(f"Line {line}: duplicate row key {key}")
                    continue
                seen.add(key)
                try:
                    value = float(row["value"])
                except ValueError:
                    errors.append(f"Line {line}: value not numeric")
                    continue
                if not math.isfinite(value):
                    errors.append(f"Line {line}: value must be finite")
                    continue
                if rt != "assign":
                    errors.append(f"Line {line}: unknown row_type {rt}")
                    continue
                if order_id not in data["orders"] or aircraft_id not in data["aircraft"]:
                    errors.append(f"Line {line}: invalid order or aircraft id")
                    continue
                if abs(value - 1.0) > tol:
                    errors.append(f"Line {line}: assign value must be 1")
                    continue
                if order_id in assigned:
                    errors.append(f"{order_id} is assigned more than once")
                    continue
                assigned[order_id] = aircraft_id
    except FileNotFoundError:
        return {
            "environment": ENV_NAME,
            "feasible": False,
            "errors": [f"Solution file not found: {solution_path}"],
            "error_count": 1,
        }

    for order_id, aircraft_id in assigned.items():
        order = data["orders"][order_id]
        aircraft = data["aircraft"][aircraft_id]
        if order["route_id"] != aircraft["route_id"]:
            errors.append(f"{order_id} assigned to aircraft on wrong route")
        if truthy(order, "cold_chain") and not truthy(aircraft, "cold_chain_capable"):
            errors.append(f"{order_id} requires cold-chain aircraft")
        if truthy(order, "hazmat") and not truthy(aircraft, "hazmat_allowed"):
            errors.append(f"{order_id} requires hazmat permission")
        if truthy(order, "requires_widebody") and not truthy(aircraft, "widebody"):
            errors.append(f"{order_id} requires widebody aircraft")

    expected_profit = 0.0
    expected_carbon_penalty = 0.0
    worst_priority_shortfall = 0.0
    scenario_details = {}
    expected_segment_weight = defaultdict(float)
    accepted_segment_weight = defaultdict(float)

    for scenario_id, scenario in data["scenarios"].items():
        probability = float(scenario["probability"])
        loaded_weight = defaultdict(float)
        loaded_volume = defaultdict(float)
        cold_count = defaultdict(float)
        team_uld_minutes = defaultdict(float)
        team_cold_slots = defaultdict(float)
        team_hazmat_minutes = defaultdict(float)
        scenario_profit = 0.0
        priority_shortfall = 0.0
        carbon_penalty = 0.0

        for order_id, order in data["orders"].items():
            if not data["show"][scenario_id, order_id]:
                continue
            segment = order["customer_segment"]
            weight = float(order["weight_kg"])
            expected_segment_weight[segment] += probability * weight
            if order_id in assigned:
                aircraft_id = assigned[order_id]
                aircraft = data["aircraft"][aircraft_id]
                loaded_weight[aircraft_id] += weight
                loaded_volume[aircraft_id] += float(order["volume_cbm"])
                cold_count[aircraft_id] += 1 if truthy(order, "cold_chain") else 0
                team = data["ramp_team"][aircraft_id]["ramp_team"]
                team_uld_minutes[team] += float(order["volume_cbm"]) * float(data["ramp_team"][aircraft_id]["uld_build_minutes_per_cbm"])
                if truthy(order, "cold_chain"):
                    team_cold_slots[team] += float(data["ramp_team"][aircraft_id]["cold_chain_slots_per_order"])
                if truthy(order, "hazmat"):
                    team_hazmat_minutes[team] += float(data["ramp_team"][aircraft_id]["hazmat_screening_minutes_per_order"])
                accepted_segment_weight[segment] += probability * weight
                scenario_profit += net_order_value(order, aircraft)
            else:
                scenario_profit -= float(order["lost_booking_penalty"])
                priority_shortfall += float(order["priority_weight"])

        for aircraft_id, aircraft in data["aircraft"].items():
            cap = data["capacity"].get((scenario_id, aircraft_id))
            if cap is None:
                errors.append(f"Missing capacity row for {scenario_id},{aircraft_id}")
                continue
            max_weight = float(aircraft["weight_capacity_kg"]) * float(cap["weight_factor"])
            max_volume = float(aircraft["volume_capacity_cbm"]) * float(cap["volume_factor"])
            if loaded_weight[aircraft_id] > max_weight + tol:
                errors.append(f"{scenario_id},{aircraft_id} exceeds realized weight capacity")
            if loaded_volume[aircraft_id] > max_volume + tol:
                errors.append(f"{scenario_id},{aircraft_id} exceeds realized volume capacity")
            if cold_count[aircraft_id] > float(aircraft["max_cold_chain_orders"]) + tol:
                errors.append(f"{scenario_id},{aircraft_id} exceeds cold-chain handling limit")
            overage = max(
                0.0,
                loaded_weight[aircraft_id] * float(aircraft["carbon_kg_per_kg"])
                - float(aircraft["carbon_allowance_kg"]),
            )
            carbon_penalty += overage * float(data["config"]["carbon_penalty_per_kg"])

        for (cap_scenario, team), cap in data["ramp_capacity"].items():
            if cap_scenario != scenario_id:
                continue
            if team_uld_minutes[team] > float(cap["uld_build_minutes_capacity"]) + tol:
                errors.append(f"{scenario_id},{team} exceeds ULD build minutes capacity")
            if team_cold_slots[team] > float(cap["cold_chain_slot_capacity"]) + tol:
                errors.append(f"{scenario_id},{team} exceeds cold-chain staging slots")
            if team_hazmat_minutes[team] > float(cap["hazmat_screening_minutes_capacity"]) + tol:
                errors.append(f"{scenario_id},{team} exceeds hazmat screening minutes")

        scenario_profit -= carbon_penalty
        expected_profit += probability * scenario_profit
        expected_carbon_penalty += probability * carbon_penalty
        worst_priority_shortfall = max(worst_priority_shortfall, priority_shortfall)
        scenario_details[scenario_id] = {
            "loaded_weight": dict(loaded_weight),
            "loaded_volume": dict(loaded_volume),
            "carbon_penalty": carbon_penalty,
            "profit_after_carbon": scenario_profit,
            "priority_shortfall": priority_shortfall,
            "ramp_team_uld_minutes": dict(team_uld_minutes),
            "ramp_team_cold_slots": dict(team_cold_slots),
            "ramp_team_hazmat_minutes": dict(team_hazmat_minutes),
        }

    for segment, floor in data["segment_rules"].items():
        if floor <= 0 or expected_segment_weight[segment] <= tol:
            continue
        service_rate = accepted_segment_weight[segment] / expected_segment_weight[segment]
        if service_rate + 1e-7 < floor:
            errors.append(f"{segment} expected service rate {service_rate:.4f} below floor {floor:.4f}")

    probability_sum = sum(float(r["probability"]) for r in data["scenarios"].values())
    if abs(probability_sum - 1.0) > 1e-6:
        errors.append("scenario probabilities do not sum to 1")

    tail_penalty = float(data["config"]["priority_tail_penalty"]) * worst_priority_shortfall
    profit = expected_profit - tail_penalty
    return {
        "environment": ENV_NAME,
        "feasible": not errors,
        "profit": profit,
        "objective": profit,
        "expected_profit_before_tail": expected_profit,
        "expected_carbon_penalty": expected_carbon_penalty,
        "priority_tail_penalty": tail_penalty,
        "worst_priority_shortfall": worst_priority_shortfall,
        "accepted_order_count": len(assigned),
        "scenario_details": scenario_details,
        "errors": errors[:200],
        "error_count": len(errors),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--solution", required=True, type=Path)
    parser.add_argument("--env-dir", default=DEFAULT_ENV_DIR, type=Path)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.solution, args.env_dir), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
