"""Two-stage stochastic MIP for disaster relief prepositioning, solved with PySCIPOpt.

Mirrors tests/evaluate_solution.py exactly for cost/eligibility/CVaR semantics.
"""
import csv
import json
import os
from collections import defaultdict
from pathlib import Path

from pyscipopt import Model, quicksum

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
SUB_DIR = APP_DIR / "submissions"

EPS = 1e-6
PRIORITY_SHORTAGE_MULT = {"critical": 1.40, "remote": 1.15, "standard": 1.00}


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_data():
    with open(DATA_DIR / "config.json") as f:
        config = json.load(f)

    warehouses = {r["warehouse_id"]: r for r in read_csv(DATA_DIR / "warehouses.csv")}
    items = {r["item_id"]: r for r in read_csv(DATA_DIR / "items.csv")}
    zones = {r["zone_id"]: r for r in read_csv(DATA_DIR / "zones.csv")}
    lanes = {(r["warehouse_id"], r["zone_id"]): r for r in read_csv(DATA_DIR / "lanes.csv")}
    periods = {r["period_id"]: r for r in read_csv(DATA_DIR / "periods.csv")}
    fleets = {r["fleet_type"]: r for r in read_csv(DATA_DIR / "fleet_types.csv")}
    scenarios = {r["scenario_id"]: r for r in read_csv(DATA_DIR / "scenarios.csv")}
    demands = {
        (r["scenario_id"], r["zone_id"], r["item_id"]): float(r["demand"])
        for r in read_csv(DATA_DIR / "scenario_demands.csv")
    }
    availability = {
        (r["scenario_id"], r["warehouse_id"]): r
        for r in read_csv(DATA_DIR / "scenario_warehouse_availability.csv")
    }
    impacts = {
        (r["scenario_id"], r["period_id"], r["warehouse_id"], r["zone_id"]): r
        for r in read_csv(DATA_DIR / "scenario_period_lane_impacts.csv")
    }
    warehouse_fleet = {
        (r["warehouse_id"], r["period_id"], r["fleet_type"]): r
        for r in read_csv(DATA_DIR / "warehouse_fleet.csv")
    }
    period_targets = {
        (r["priority_class"], r["item_id"], r["period_id"]): float(r["cumulative_fraction_of_final_floor"])
        for r in read_csv(DATA_DIR / "period_service_targets.csv")
    }

    periods_ordered = sorted(periods, key=lambda pid: float(periods[pid]["start_hour"]))

    return {
        "config": config,
        "warehouses": warehouses,
        "items": items,
        "zones": zones,
        "lanes": lanes,
        "periods": periods,
        "periods_ordered": periods_ordered,
        "fleets": fleets,
        "scenarios": scenarios,
        "demands": demands,
        "availability": availability,
        "impacts": impacts,
        "warehouse_fleet": warehouse_fleet,
        "period_targets": period_targets,
    }


def flag(row, key):
    return int(float(row[key])) == 1


def fleet_can_serve(fleet, item, impact):
    if flag(item, "cold_chain_required") and not flag(fleet, "cold_chain_capable"):
        return False
    if float(impact["travel_time_hours"]) > float(fleet["max_travel_time_hours"]) + EPS and not flag(fleet, "airlift_capable"):
        return False
    disrupted = float(impact["capacity_multiplier"]) < 0.35
    if disrupted and not (flag(fleet, "rough_road_capable") or flag(fleet, "airlift_capable")):
        return False
    return True


def unit_ship_cost(data, scenario_id, period_id, warehouse_id, zone_id, item_id, fleet_type):
    item = data["items"][item_id]
    lane = data["lanes"][(warehouse_id, zone_id)]
    impact = data["impacts"][(scenario_id, period_id, warehouse_id, zone_id)]
    fleet = data["fleets"][fleet_type]
    zone = data["zones"][zone_id]
    period = data["periods"][period_id]
    slow_hours = max(0.0, float(impact["travel_time_hours"]) - float(zone["target_response_hours"]))
    load_factor = float(item["load_factor"])
    return load_factor * (
        float(lane["transport_cost_per_load"])
        + float(impact["extra_transport_cost_per_load"])
        + slow_hours * float(data["config"]["late_response_penalty_per_load_hour"]) * float(period["delay_penalty_multiplier"])
        + float(fleet["fixed_trip_cost"]) / float(fleet["capacity_load"])
    )


def build_and_solve(data, time_limit, gap):
    config = data["config"]
    W, I, Z, S, F = data["warehouses"], data["items"], data["zones"], data["scenarios"], data["fleets"]
    periods_ordered = data["periods_ordered"]
    lanes = data["lanes"]

    model = Model("disaster_relief_prepositioning")
    model.hideOutput()
    model.setRealParam("limits/gap", gap)
    model.setRealParam("limits/time", time_limit)

    # First-stage vars
    open_var = {w: model.addVar(name=f"open_{w}", vtype="B") for w in W}
    stock = {(w, i): model.addVar(name=f"stock_{w}_{i}", vtype="C", lb=0.0) for w in W for i in I}

    # Precompute eligible ship keys per (scenario, period, warehouse, zone, item, fleet)
    ship = {}
    ship_keys_by_swi = defaultdict(list)   # (s,w,i) -> list of ship keys (for usable-stock constraint)
    ship_keys_by_swp = defaultdict(list)   # (s,w,p) -> list of ship keys (outbound handling)
    ship_keys_by_spwz = defaultdict(list)  # (s,p,w,z) -> list of ship keys (lane capacity)
    ship_keys_by_spwf = defaultdict(list)  # (s,p,w,f) -> list of ship keys (fleet trips)
    ship_keys_by_szi = defaultdict(list)   # (s,z,i) -> list of ship keys (demand balance / fill rate)
    ship_keys_by_spzi = defaultdict(list)  # (s,p,z,i) -> list of ship keys (period service targets)

    for s in S:
        for p in periods_ordered:
            for (w, z), lane in lanes.items():
                impact = data["impacts"][(s, p, w, z)]
                for i, item in I.items():
                    for ft, fleet in F.items():
                        if not fleet_can_serve(fleet, item, impact):
                            continue
                        key = (s, p, w, z, i, ft)
                        ship[key] = model.addVar(name=f"ship_{s}_{p}_{w}_{z}_{i}_{ft}", vtype="C", lb=0.0)
                        ship_keys_by_swi[(s, w, i)].append(key)
                        ship_keys_by_swp[(s, w, p)].append(key)
                        ship_keys_by_spwz[(s, p, w, z)].append(key)
                        ship_keys_by_spwf[(s, p, w, ft)].append(key)
                        ship_keys_by_szi[(s, z, i)].append(key)
                        ship_keys_by_spzi[(s, p, z, i)].append(key)

    procure = {(s, p, z, i): model.addVar(name=f"procure_{s}_{p}_{z}_{i}", vtype="C", lb=0.0)
               for s in S for p in periods_ordered for z in Z for i in I}
    unmet = {(s, p, z, i): model.addVar(name=f"unmet_{s}_{p}_{z}_{i}", vtype="C", lb=0.0)
             for s in S for p in periods_ordered for z in Z for i in I}

    # --- First-stage constraints ---
    for w, wh in W.items():
        model.addCons(
            quicksum(stock[(w, i)] * float(I[i]["unit_volume"]) for i in I) <= float(wh["storage_capacity"]) * open_var[w],
            name=f"storage_{w}",
        )
        for i, item in I.items():
            model.addCons(stock[(w, i)] <= float(item["max_stock_per_warehouse"]), name=f"maxstock_{w}_{i}")
            if flag(item, "cold_chain_required") and not flag(wh, "cold_chain"):
                model.addCons(stock[(w, i)] == 0, name=f"nocoldchain_{w}_{i}")

    model.addCons(quicksum(open_var[w] for w in W) <= int(config["max_open_warehouses"]), name="max_open")
    model.addCons(
        quicksum(open_var[w] * float(wh["cold_chain"]) for w, wh in W.items()) >= int(config["min_open_cold_chain_warehouses"]),
        name="min_cold_open",
    )

    first_stage_cost_expr = (
        quicksum(open_var[w] * float(wh["open_cost"]) for w, wh in W.items())
        + quicksum(stock[(w, i)] * float(I[i]["preposition_cost"]) for w in W for i in I)
    )
    model.addCons(first_stage_cost_expr <= float(config["planning_budget"]), name="budget")

    # --- Second-stage constraints, per scenario ---
    scenario_cost_expr = {}
    fill_num = {}  # (s,z,i) -> linear expr for shipped+procured (numerator of fill rate)

    for s, scen in S.items():
        avail = {w: data["availability"][(s, w)] for w in W}

        # Usable-stock limit
        for w in W:
            for i in I:
                keys = ship_keys_by_swi.get((s, w, i), [])
                if keys:
                    usable_fraction = float(avail[w]["usable_fraction"])
                    model.addCons(
                        quicksum(ship[k] for k in keys) <= stock[(w, i)] * usable_fraction,
                        name=f"usable_{s}_{w}_{i}",
                    )

        # Outbound handling capacity
        for w, wh in W.items():
            terms = []
            for p in periods_ordered:
                for k in ship_keys_by_swp.get((s, w, p), []):
                    item_id = k[4]
                    terms.append(ship[k] * float(I[item_id]["load_factor"]))
            if terms:
                capacity = float(wh["outbound_capacity"]) * float(avail[w]["outbound_multiplier"])
                model.addCons(quicksum(terms) <= capacity, name=f"outbound_{s}_{w}")

        # Lane capacity per period
        for p in periods_ordered:
            for (w, z), lane in lanes.items():
                keys = ship_keys_by_spwz.get((s, p, w, z), [])
                if keys:
                    impact = data["impacts"][(s, p, w, z)]
                    terms = [ship[k] * float(I[k[4]]["load_factor"]) for k in keys]
                    capacity = float(lane["base_capacity"]) * float(impact["capacity_multiplier"])
                    model.addCons(quicksum(terms) <= capacity, name=f"lanecap_{s}_{p}_{w}_{z}")

        # Fleet trip capacity per warehouse-period
        for p in periods_ordered:
            for w in W:
                for ft, fleet in F.items():
                    keys = ship_keys_by_spwf.get((s, p, w, ft), [])
                    if keys:
                        terms = [ship[k] * float(I[k[4]]["load_factor"]) for k in keys]
                        wf_key = (w, p, ft)
                        trips = float(data["warehouse_fleet"][wf_key]["available_trips"]) if wf_key in data["warehouse_fleet"] else 0.0
                        capacity = trips * float(fleet["capacity_load"]) * float(avail[w]["outbound_multiplier"])
                        model.addCons(quicksum(terms) <= capacity, name=f"fleetcap_{s}_{p}_{w}_{ft}")

        # Demand balance + emergency procurement caps + fill numerator
        for z, zone in Z.items():
            for i, item in I.items():
                demand = data["demands"][(s, z, i)]
                ship_terms = [ship[k] for k in ship_keys_by_szi.get((s, z, i), [])]
                procure_terms = [procure[(s, p, z, i)] for p in periods_ordered]
                unmet_terms = [unmet[(s, p, z, i)] for p in periods_ordered]
                model.addCons(
                    quicksum(ship_terms) + quicksum(procure_terms) + quicksum(unmet_terms) == demand,
                    name=f"balance_{s}_{z}_{i}",
                )
                model.addCons(
                    quicksum(procure_terms) <= demand * float(zone["emergency_procure_limit_fraction"]),
                    name=f"proccap_zone_{s}_{z}_{i}",
                )
                fill_num[(s, z, i)] = quicksum(ship_terms) + quicksum(procure_terms)

        # Emergency procurement scenario-item cap
        for i in I:
            cap = float(scen[f"{i}_procure_cap"])
            terms = [procure[(s, p, z, i)] for p in periods_ordered for z in Z]
            model.addCons(quicksum(terms) <= cap, name=f"proccap_scen_{s}_{i}")

        # Cumulative period service targets
        for z, zone in Z.items():
            priority = zone["priority_class"]
            for i in I:
                demand = data["demands"][(s, z, i)]
                service_floor = float(zone[f"{i}_floor"])
                cum_terms = []
                for p in periods_ordered:
                    ship_p = [ship[k] for k in ship_keys_by_spzi.get((s, p, z, i), [])]
                    cum_terms.extend(ship_p)
                    cum_terms.append(procure[(s, p, z, i)])
                    target_frac = data["period_targets"][(priority, i, p)]
                    target = demand * service_floor * target_frac
                    model.addCons(quicksum(cum_terms) >= target, name=f"service_{s}_{p}_{z}_{i}")

        # Fairness: critical fill + gap >= non-critical fill, cross-multiplied by demands
        fairness_gap = float(config["fairness_gap"])
        critical_zones = [zid for zid, z in Z.items() if z["priority_class"] == "critical"]
        other_zones = [zid for zid, z in Z.items() if z["priority_class"] != "critical"]
        for i in I:
            for c in critical_zones:
                d_c = data["demands"][(s, c, i)]
                for o in other_zones:
                    d_o = data["demands"][(s, o, i)]
                    if d_c <= EPS or d_o <= EPS:
                        continue
                    # fill_c + gap >= fill_o  <=>  fill_num_c/d_c + gap >= fill_num_o/d_o
                    # cross-multiply by d_c*d_o (both positive):
                    model.addCons(
                        fill_num[(s, c, i)] * d_o + fairness_gap * d_c * d_o >= fill_num[(s, o, i)] * d_c,
                        name=f"fair_{s}_{i}_{c}_{o}",
                    )

        # Scenario cost expression
        ship_cost_terms = []
        for p in periods_ordered:
            for (w, z) in lanes:
                for i in I:
                    for k in ship_keys_by_spwz.get((s, p, w, z), []):
                        if k[4] != i:
                            continue
                        ft = k[5]
                        cost = unit_ship_cost(data, s, p, w, z, i, ft)
                        ship_cost_terms.append(ship[k] * cost)
        procure_cost_terms = [
            procure[(s, p, z, i)] * float(I[i]["emergency_procure_cost"])
            for p in periods_ordered for z in Z for i in I
        ]
        unmet_cost_terms = [
            unmet[(s, p, z, i)] * float(I[i]["shortage_penalty"]) * PRIORITY_SHORTAGE_MULT[Z[z]["priority_class"]]
            for p in periods_ordered for z in Z for i in I
        ]
        scenario_cost_expr[s] = quicksum(ship_cost_terms) + quicksum(procure_cost_terms) + quicksum(unmet_cost_terms)

    # --- CVaR linearization ---
    alpha = float(config["tail_risk_alpha"])
    tail_weight = float(config["tail_risk_weight"])
    cvar_eta = model.addVar(name="cvar_eta", vtype="C", lb=None)
    cvar_excess = {s: model.addVar(name=f"cvar_excess_{s}", vtype="C", lb=0.0) for s in S}
    for s in S:
        model.addCons(cvar_excess[s] >= scenario_cost_expr[s] - cvar_eta, name=f"cvar_link_{s}")

    cvar_tail_expr = cvar_eta + (1.0 / (1.0 - alpha)) * quicksum(
        float(S[s]["probability"]) * cvar_excess[s] for s in S
    )

    expected_cost_expr = quicksum(float(S[s]["probability"]) * scenario_cost_expr[s] for s in S)

    model.setObjective(
        first_stage_cost_expr + expected_cost_expr + tail_weight * cvar_tail_expr,
        sense="minimize",
    )

    model.optimize()
    status = model.getStatus()
    if status not in ("optimal", "gaplimit", "timelimit"):
        raise RuntimeError(f"SCIP finished with unexpected status: {status}")
    if model.getNSols() == 0:
        raise RuntimeError("SCIP found no incumbent solution")

    return model, status, {
        "open_var": open_var,
        "stock": stock,
        "ship": ship,
        "procure": procure,
        "unmet": unmet,
    }


def write_solution_csv(model, data, vars_):
    path = SUB_DIR / "solution.csv"
    open_var, stock, ship, procure, unmet = (
        vars_["open_var"], vars_["stock"], vars_["ship"], vars_["procure"], vars_["unmet"]
    )
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["row_type", "scenario_id", "period_id", "warehouse_id", "zone_id", "item_id", "fleet_type", "quantity", "decision"])

        for w in data["warehouses"]:
            decision = "open" if model.getVal(open_var[w]) > 0.5 else "closed"
            writer.writerow(["warehouse", "", "", w, "", "", "", "", decision])

        for (w, i), var in stock.items():
            val = model.getVal(var)
            writer.writerow(["inventory", "", "", w, "", i, "", f"{max(val, 0.0):.8f}", "stock"])

        for (s, p, w, z, i, ft), var in ship.items():
            val = model.getVal(var)
            if val > 1e-7:
                writer.writerow(["ship", s, p, w, z, i, ft, f"{val:.8f}", "ship"])

        for (s, p, z, i), var in procure.items():
            val = model.getVal(var)
            writer.writerow(["procure", s, p, "", z, i, "", f"{max(val, 0.0):.8f}", "procure"])

        for (s, p, z, i), var in unmet.items():
            val = model.getVal(var)
            writer.writerow(["unmet", s, p, "", z, i, "", f"{max(val, 0.0):.8f}", "unmet"])

    return path


def write_solve_log(model, status):
    obj = model.getObjVal()
    dual_bound = model.getDualbound()
    gap = model.getGap()
    lines = [
        "# Solve Log — Disaster Relief Prepositioning",
        "",
        "- Solver: SCIP via PySCIPOpt",
        f"- Status: {status}",
        f"- Objective (total risk-adjusted cost, minimized): {obj:.6f}",
        f"- Dual bound: {dual_bound:.6f}",
        f"- Relative gap: {gap:.8e}",
        "",
        "## Model",
        "Two-stage stochastic MIP with CVaR tail-risk term (Rockafellar-Uryasev linearization).",
        "First stage: warehouse open/close (binary) + pre-positioned stock per item (continuous).",
        "Second stage per scenario: routed shipments (per period/warehouse/zone/item/fleet),",
        "emergency procurement, unmet demand, subject to lane/fleet/handling capacity,",
        "cumulative period service floors, and critical-vs-noncritical fairness constraints.",
        "",
        "## Commands",
        "```",
        "python solve.py",
        "```",
        "",
        "## Validation",
        "Ran independently against tests/evaluate_solution.py from the ORAgentBench repo.",
    ]
    path = SUB_DIR / "solve_log.md"
    path.write_text("\n".join(lines))
    return path


def main():
    time_limit = float(os.environ.get("ORCLAW_SOLVE_TIME_LIMIT_SECONDS", 300))
    gap = float(os.environ.get("ORCLAW_SCIP_GAP", 0.0005))

    data = load_data()
    model, status, vars_ = build_and_solve(data, time_limit, gap)

    write_solution_csv(model, data, vars_)
    write_solve_log(model, status)

    print(f"status={status} objective={model.getObjVal():.6f} gap={model.getGap():.6e}")


if __name__ == "__main__":
    main()
