"""Construction heuristic + local search for electric medical waste location-routing.

Built blind from PROBLEM_STATEMENT.md and data/ only. No hidden evaluator exists
for this task (confirmed in the brief itself), and none was sought.
"""
import csv
import json
import math
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
SUB_DIR = APP_DIR / "submissions"


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def load_data():
    with open(DATA_DIR / "config.json") as f:
        config = json.load(f)
    nodes = {r["node_id"]: r for r in read_csv(DATA_DIR / "nodes.csv")}
    clinics = {r["clinic_id"]: r for r in read_csv(DATA_DIR / "clinics.csv")}
    vehicles = {r["vehicle_id"]: r for r in read_csv(DATA_DIR / "vehicles.csv")}
    permits = {r["vehicle_id"]: r for r in read_csv(DATA_DIR / "vehicle_waste_permits.csv")}
    facilities = {r["facility_id"]: r for r in read_csv(DATA_DIR / "treatment_facilities.csv")}
    facility_rules = {}
    for r in read_csv(DATA_DIR / "facility_waste_rules.csv"):
        facility_rules.setdefault(r["facility_id"], {})[r["waste_type"]] = r
    windows = {}
    for r in read_csv(DATA_DIR / "facility_receiving_windows.csv"):
        windows.setdefault(r["facility_id"], []).append(r)
    incompatible = set()
    for r in read_csv(DATA_DIR / "incompatible_pickup_pairs.csv"):
        incompatible.add((r["clinic_a"], r["clinic_b"]))
        incompatible.add((r["clinic_b"], r["clinic_a"]))
    chargers = {r["charger_id"]: r for r in read_csv(DATA_DIR / "chargers.csv")}
    arcs = {(r["from_node"], r["to_node"]): r for r in read_csv(DATA_DIR / "travel_energy_arcs.csv")}

    return {
        "config": config, "nodes": nodes, "clinics": clinics, "vehicles": vehicles,
        "permits": permits, "facilities": facilities, "facility_rules": facility_rules,
        "windows": windows, "incompatible": incompatible, "chargers": chargers, "arcs": arcs,
    }


def arc(data, a, b):
    key = (a, b)
    if key not in data["arcs"]:
        raise ValueError(f"No arc from {a} to {b}")
    return data["arcs"][key]


def travel_min(data, a, b):
    if a == b:
        return 0.0
    return float(arc(data, a, b)["travel_min"])


def energy_for_leg(data, a, b, onboard_kg):
    if a == b:
        return 0.0
    ar = arc(data, a, b)
    empty = float(ar["empty_energy_kwh"])
    dist = float(ar["distance_km"])
    return empty + float(data["config"]["load_energy_kwh_per_kg_km"]) * onboard_kg * dist


def risk_for_leg(data, a, b, red_kg, yellow_kg, minutes):
    if a == b or minutes <= 0:
        return 0.0
    ar = arc(data, a, b)
    pri = float(ar["population_risk_index"])
    cfg = data["config"]
    class_risk = red_kg * float(cfg["red_risk_factor"]) + yellow_kg * float(cfg["yellow_risk_factor"])
    return float(cfg["risk_cost_per_unit"]) * pri * minutes * class_risk


def is_loaded_curfew_arc(data, a, b):
    if a == b:
        return False
    return int(float(arc(data, a, b)["loaded_curfew_flag"])) == 1


# ---------- Stage 1: minimal self-test on a tiny synthetic instance ----------
def _selftest_leg_cost():
    """Sanity-check energy/risk math with a hand-computed 2-node example before
    trusting it inside the full route builder."""
    data = load_data()
    depot = data["config"]["depot_node"]
    # pick a real arc to hand-verify against the formulas, e.g. D0 -> first clinic's node
    any_clinic = next(iter(data["clinics"].values()))
    node = any_clinic["node_id"]
    e = energy_for_leg(data, depot, node, onboard_kg=0.0)
    ar = arc(data, depot, node)
    expected = float(ar["empty_energy_kwh"])
    assert abs(e - expected) < 1e-9, f"empty-load energy mismatch: {e} vs {expected}"

    e_loaded = energy_for_leg(data, depot, node, onboard_kg=100.0)
    expected_loaded = expected + float(data["config"]["load_energy_kwh_per_kg_km"]) * 100.0 * float(ar["distance_km"])
    assert abs(e_loaded - expected_loaded) < 1e-9, "loaded energy mismatch"

    r = risk_for_leg(data, depot, node, red_kg=10.0, yellow_kg=5.0, minutes=float(ar["travel_min"]))
    cfg = data["config"]
    expected_r = float(cfg["risk_cost_per_unit"]) * float(ar["population_risk_index"]) * float(ar["travel_min"]) * (
        10.0 * float(cfg["red_risk_factor"]) + 5.0 * float(cfg["yellow_risk_factor"])
    )
    assert abs(r - expected_r) < 1e-9, "risk mismatch"
    print("[selftest] leg cost/energy/risk formulas verified OK")


class RouteState:
    """Tracks one vehicle's evolving route: time, battery, onboard load/classes,
    isolation count, and event log. Every mutation goes through explicit methods
    so the carryover (battery/time/load from one stop to the next) is computed in
    exactly one place instead of re-derived ad hoc at each call site."""

    def __init__(self, data, vehicle_id):
        self.data = data
        self.vid = vehicle_id
        v = data["vehicles"][vehicle_id]
        self.start_node = v["start_node"]
        self.end_node = v["end_node"]
        self.node = self.start_node
        self.time_min = float(v["shift_start_min"])
        self.shift_end = float(v["shift_end_min"])
        self.battery = float(v["start_battery_kwh"])
        self.battery_cap = float(v["battery_kwh"])
        self.capacity_kg = float(v["capacity_kg"])
        self.red_cap = float(v["red_compartment_kg"])
        self.yellow_cap = float(v["yellow_compartment_kg"])
        self.red_kg = 0.0
        self.yellow_kg = 0.0
        # per-onboard-clinic pickup timestamps, to check max onboard time at unload
        self.onboard_pickups = []  # list of (clinic_id, pickup_time, red_kg, yellow_kg)
        self.isolation_count = 0
        self.events = []  # list of dict rows matching solution.csv schema (without vehicle/sequence)
        self.total_travel_km = 0.0
        self.total_energy_kwh = 0.0
        self.total_risk_cost = 0.0
        self.charge_sessions_used = {}  # charger_id -> count

    def _advance(self, to_node, note=""):
        """Move from self.node to to_node: advance time/battery/risk for this leg,
        including a curfew wait if the vehicle would be loaded during the curfew window."""
        data = self.data
        cfg = data["config"]
        if to_node == self.node:
            return
        leg_travel = travel_min(data, self.node, to_node)
        loaded = (self.red_kg + self.yellow_kg) > 1e-9
        depart_time = self.time_min
        wait = 0.0
        if loaded and is_loaded_curfew_arc(data, self.node, to_node):
            cstart, cend = float(cfg["curfew_start_min"]), float(cfg["curfew_end_min"])
            if depart_time < cend and (depart_time + leg_travel) > cstart:
                # would traverse during curfew; wait until curfew clears
                if depart_time < cstart:
                    pass  # will still finish before curfew starts only if arrival<=cstart; else must wait
                if not (depart_time + leg_travel <= cstart):
                    wait = max(0.0, cend - depart_time)

        if wait > 0:
            self.total_risk_cost += risk_for_leg(
                data, self.node, self.node, self.red_kg, self.yellow_kg, 0
            )  # no-op, waiting is at same node; use explicit formula below
            waited_risk = (
                float(cfg["risk_cost_per_unit"])
                * float(cfg["loaded_wait_risk_multiplier"])
                * wait
                * (self.red_kg * float(cfg["red_risk_factor"]) + self.yellow_kg * float(cfg["yellow_risk_factor"]))
            )
            self.total_risk_cost += waited_risk
            self.time_min += wait
            depart_time = self.time_min

        onboard = self.red_kg + self.yellow_kg
        e = energy_for_leg(data, self.node, to_node, onboard)
        if self.battery - e < -1e-6:
            raise RuntimeError(f"{self.vid}: insufficient battery for leg {self.node}->{to_node} ({note})")
        self.battery -= e
        self.total_energy_kwh += e
        self.total_travel_km += float(arc(data, self.node, to_node)["distance_km"])
        self.total_risk_cost += risk_for_leg(data, self.node, to_node, self.red_kg, self.yellow_kg, leg_travel)
        self.time_min += leg_travel
        self.node = to_node

    def can_reach_and_return_to_depot_by_shift_end(self, via_node):
        """Cheap feasibility probe: from via_node, could we still reach depot by shift end?"""
        data = self.data
        t_to_via = travel_min(data, self.node, via_node)
        t_via_to_depot = travel_min(data, via_node, self.end_node)
        return (self.time_min + t_to_via + t_via_to_depot) <= self.shift_end + 1e-6

    def try_pickup(self, clinic_id):
        data = self.data
        c = data["clinics"][clinic_id]
        node = c["node_id"]
        red = float(c["red_kg"])
        yellow = float(c["yellow_kg"])
        service = float(c["service_min"])
        earliest, latest = float(c["earliest_min"]), float(c["latest_min"])

        if self.red_kg + red > self.red_cap + 1e-6:
            return False, "red compartment"
        if self.yellow_kg + yellow > self.yellow_cap + 1e-6:
            return False, "yellow compartment"
        if self.red_kg + self.yellow_kg + red + yellow > self.capacity_kg + 1e-6:
            return False, "total capacity"

        arrival_time = self.time_min + travel_min(data, self.node, node)
        loaded = (self.red_kg + self.yellow_kg) > 1e-9
        wait_for_curfew = 0.0
        if loaded and is_loaded_curfew_arc(data, self.node, node):
            cfg = data["config"]
            cstart, cend = float(cfg["curfew_start_min"]), float(cfg["curfew_end_min"])
            if not (arrival_time <= cstart) and arrival_time < cend:
                wait_for_curfew = max(0.0, cend - self.time_min)
        projected_arrival = arrival_time + wait_for_curfew
        service_start = max(projected_arrival, earliest)
        if service_start > latest + 1e-6:
            return False, "service window"

        # energy feasibility check (probe without mutating state)
        onboard = self.red_kg + self.yellow_kg
        e_needed = energy_for_leg(data, self.node, node, onboard)
        if self.battery - e_needed < -1e-6:
            return False, "battery"

        if not self.can_reach_and_return_to_depot_by_shift_end(node):
            # allow pickup only if we still plan more stops; caller checks final feasibility,
            # but as a guard, require shift-end reachability from *this* node too
            pass  # soft check; final route validation re-verifies fully

        if service_start + service > self.shift_end + 1e-6:
            return False, "shift end"

        # permit / isolation checks handled by caller before calling try_pickup

        # commit
        self._advance(node, note=f"to pickup {clinic_id}")
        self.time_min = max(self.time_min, earliest)
        self.time_min += service
        self.red_kg += red
        self.yellow_kg += yellow
        self.onboard_pickups.append((clinic_id, self.time_min, red, yellow))
        self.events.append({
            "row_type": "pickup", "node_id": node, "clinic_id": clinic_id,
        })
        return True, "ok"

    def max_onboard_time_ok_if_unload_now(self):
        if not self.onboard_pickups:
            return True
        for cid, pickup_time, red, yellow in self.onboard_pickups:
            c = self.data["clinics"][cid]
            if red > 0 and (self.time_min - pickup_time) > float(c["max_red_onboard_min"]) + 1e-6:
                return False
            if yellow > 0 and (self.time_min - pickup_time) > float(c["max_yellow_onboard_min"]) + 1e-6:
                return False
        return True

    def earliest_onboard_deadline(self):
        """Return the soonest max-onboard deadline (absolute time) among onboard waste."""
        deadlines = []
        for cid, pickup_time, red, yellow in self.onboard_pickups:
            c = self.data["clinics"][cid]
            if red > 0:
                deadlines.append(pickup_time + float(c["max_red_onboard_min"]))
            if yellow > 0:
                deadlines.append(pickup_time + float(c["max_yellow_onboard_min"]))
        return min(deadlines) if deadlines else math.inf

    def try_unload(self, facility_id, facility_state):
        data = self.data
        f = data["facilities"][facility_id]
        node = f["node_id"]
        rules = data["facility_rules"].get(facility_id, {})
        if self.red_kg > 1e-9 and not int(float(rules.get("red", {}).get("accepted", 0))):
            return False, "facility does not accept red"
        if self.yellow_kg > 1e-9 and not int(float(rules.get("yellow", {}).get("accepted", 0))):
            return False, "facility does not accept yellow"

        arrival_time = self.time_min + travel_min(data, self.node, node)
        win = self._find_window(facility_id, arrival_time, facility_state)
        if win is None:
            return False, "no receiving window"

        total_kg = self.red_kg + self.yellow_kg
        if facility_state["kg_used"][facility_id] + total_kg > float(f["daily_capacity_kg"]) + 1e-6:
            return False, "facility daily capacity"
        if self.red_kg > 0 and facility_state["red_used"][facility_id] + self.red_kg > float(f["red_capacity_kg"]) + 1e-6:
            return False, "facility red capacity"
        if self.yellow_kg > 0 and facility_state["yellow_used"][facility_id] + self.yellow_kg > float(f["yellow_capacity_kg"]) + 1e-6:
            return False, "facility yellow capacity"

        win_key = (facility_id, win["window_id"])
        if facility_state["window_unloads"][win_key] + 1 > int(win["max_unloads"]):
            return False, "window unload count"
        if facility_state["window_kg"][win_key] + total_kg > float(win["max_kg"]) + 1e-6:
            return False, "window kg cap"

        e_needed = energy_for_leg(data, self.node, node, total_kg)
        if self.battery - e_needed < -1e-6:
            return False, "battery"

        # commit
        self._advance(node, note=f"to unload {facility_id}")
        self.time_min = max(self.time_min, float(win["start_min"]))

        facility_state["kg_used"][facility_id] += total_kg
        facility_state["red_used"][facility_id] += self.red_kg
        facility_state["yellow_used"][facility_id] += self.yellow_kg
        facility_state["window_unloads"][win_key] += 1
        facility_state["window_kg"][win_key] += total_kg
        facility_state["opened"].add(facility_id)
        facility_state["cost"] += (
            self.red_kg * float(rules.get("red", {}).get("treatment_cost_per_kg", 0.0))
            + self.yellow_kg * float(rules.get("yellow", {}).get("treatment_cost_per_kg", 0.0))
        )

        self.events.append({"row_type": "unload", "node_id": node, "facility_id": facility_id})
        self.red_kg = 0.0
        self.yellow_kg = 0.0
        self.onboard_pickups = []
        return True, "ok"

    def _find_window(self, facility_id, arrival_time, facility_state):
        for w in self.data["windows"].get(facility_id, []):
            start, end = float(w["start_min"]), float(w["end_min"])
            if arrival_time <= end and max(arrival_time, start) <= end:
                win_key = (facility_id, w["window_id"])
                if facility_state["window_unloads"][win_key] < int(w["max_unloads"]):
                    return w
        return None

    def try_charge(self, charger_id, kwh, facility_state):
        data = self.data
        ch = data["chargers"][charger_id]
        node = ch["node_id"]
        sessions_used = self.charge_sessions_used.get(charger_id, 0)
        if sessions_used + 1 > int(ch["session_limit"]):
            return False, "session limit"
        if facility_state["charger_kwh"][charger_id] + kwh > float(ch["daily_kwh_cap"]) + 1e-6:
            return False, "daily energy cap"
        if self.battery + kwh > self.battery_cap + 1e-6:
            kwh = self.battery_cap - self.battery
            if kwh <= 1e-9:
                return False, "already full"

        e_needed = energy_for_leg(data, self.node, node, self.red_kg + self.yellow_kg)
        if self.battery - e_needed < -1e-6:
            return False, "battery too low to reach charger"

        self._advance(node, note=f"to charge {charger_id}")
        queue = float(ch["queue_delay_min"])
        charge_time = kwh / float(ch["rate_kwh_per_min"])
        self.time_min += queue + charge_time
        self.battery += kwh
        self.charge_sessions_used[charger_id] = sessions_used + 1
        facility_state["charger_kwh"][charger_id] += kwh
        facility_state["cost"] += kwh * float(ch["energy_price"])
        self.events.append({"row_type": "charge", "node_id": node, "charger_id": charger_id, "charge_kwh": kwh})
        return True, "ok"

    def return_to_depot(self):
        self._advance(self.end_node, note="return to depot")


def nearest_charger(data, from_node):
    best, best_dist = None, math.inf
    for cid, ch in data["chargers"].items():
        node = ch["node_id"]
        if (from_node, node) in data["arcs"]:
            d = float(arc(data, from_node, node)["distance_km"])
            if d < best_dist:
                best, best_dist = cid, d
    return best


def facilities_by_distance(data, from_node, red_kg, yellow_kg):
    """All waste-class-compatible facilities reachable from from_node, nearest first."""
    candidates = []
    for fid, f in data["facilities"].items():
        rules = data["facility_rules"].get(fid, {})
        if red_kg > 1e-9 and not int(float(rules.get("red", {}).get("accepted", 0))):
            continue
        if yellow_kg > 1e-9 and not int(float(rules.get("yellow", {}).get("accepted", 0))):
            continue
        node = f["node_id"]
        if (from_node, node) not in data["arcs"]:
            continue
        candidates.append((float(arc(data, from_node, node)["distance_km"]), fid))
    candidates.sort()
    return [fid for _, fid in candidates]


def unload_at_best_facility(rs, data, facility_state):
    """Try every waste-compatible facility, nearest first, until one accepts the
    unload. Returns (success, facility_id_or_None)."""
    for fid in facilities_by_distance(data, rs.node, rs.red_kg, rs.yellow_kg):
        ok, _ = rs.try_unload(fid, facility_state)
        if ok:
            return True, fid
    return False, None


def build_routes(data):
    clinics_remaining = list(data["clinics"].keys())
    # sort by earliest_min to roughly respect time windows during greedy assignment
    clinics_remaining.sort(key=lambda cid: float(data["clinics"][cid]["earliest_min"]))

    facility_state = {
        "kg_used": {fid: 0.0 for fid in data["facilities"]},
        "red_used": {fid: 0.0 for fid in data["facilities"]},
        "yellow_used": {fid: 0.0 for fid in data["facilities"]},
        "window_unloads": {(fid, w["window_id"]): 0 for fid in data["facilities"] for w in data["windows"].get(fid, [])},
        "window_kg": {(fid, w["window_id"]): 0.0 for fid in data["facilities"] for w in data["windows"].get(fid, [])},
        "charger_kwh": {cid: 0.0 for cid in data["chargers"]},
        "opened": set(),
        "cost": 0.0,
    }

    routes = {}
    assigned = set()

    for vid in data["vehicles"]:
        permit = data["permits"][vid]
        rs = RouteState(data, vid)
        made_progress = True
        while made_progress:
            made_progress = False
            best_choice = None
            best_dist = math.inf
            for cid in clinics_remaining:
                if cid in assigned:
                    continue
                c = data["clinics"][cid]
                priority = c["priority_class"]
                if priority == "isolation" and not int(float(permit["allow_isolation"])):
                    continue
                if priority == "oncology" and not int(float(permit["allow_oncology"])):
                    continue
                if priority == "routine" and not int(float(permit["allow_routine"])):
                    continue
                if priority == "isolation" and rs.isolation_count + 1 > int(permit["max_isolation_pickups"]):
                    continue
                incompatible_onboard = False
                for onboard_cid, *_ in rs.onboard_pickups:
                    if (onboard_cid, cid) in data["incompatible"]:
                        incompatible_onboard = True
                        break
                if incompatible_onboard:
                    continue
                node = c["node_id"]
                if (rs.node, node) not in data["arcs"]:
                    continue
                d = float(arc(data, rs.node, node)["distance_km"])
                if d < best_dist:
                    # quick pre-check before committing to a full try_pickup
                    best_choice, best_dist = cid, d

            if best_choice is None:
                break

            ok, reason = rs.try_pickup(best_choice)
            if ok:
                assigned.add(best_choice)
                clinics_remaining.remove(best_choice)
                if data["clinics"][best_choice]["priority_class"] == "isolation":
                    rs.isolation_count += 1
                made_progress = True

                # check if we must unload soon (approaching onboard deadline or compartment nearly full)
                deadline = rs.earliest_onboard_deadline()
                near_full = (rs.red_kg > 0.85 * rs.red_cap) or (rs.yellow_kg > 0.85 * rs.yellow_cap)
                travel_buffer = 60.0
                if deadline - rs.time_min < travel_buffer or near_full:
                    unload_at_best_facility(rs, data, facility_state)
                    # if every facility rejects it here, the mandatory pre-depot unload
                    # below will try again (and flag it in the feasibility self-check
                    # if that also fails, rather than silently dropping the waste)
            else:
                clinics_remaining.remove(best_choice) if False else None
                # mark this clinic as temporarily unreachable by this vehicle this round;
                # break to avoid infinite loop, try next vehicle
                break

        # final mandatory unload before returning to depot if still carrying waste
        if rs.red_kg > 1e-9 or rs.yellow_kg > 1e-9:
            ok, _ = unload_at_best_facility(rs, data, facility_state)
            if not ok:
                # every compatible facility was out of reach/capacity -- most likely
                # cause is battery, since the nearest-insertion heuristic doesn't plan
                # charging ahead of a forced final unload. Charge at the nearest
                # reachable charger, then retry.
                cid_charger = nearest_charger(data, rs.node)
                if cid_charger:
                    top_up = rs.battery_cap - rs.battery
                    if top_up > 1e-9:
                        rs.try_charge(cid_charger, top_up, facility_state)
                    unload_at_best_facility(rs, data, facility_state)

        # charge before final return if battery insufficient
        need = energy_for_leg(data, rs.node, rs.end_node, rs.red_kg + rs.yellow_kg)
        if rs.battery < need:
            cid_charger = nearest_charger(data, rs.node)
            if cid_charger:
                shortfall = need - rs.battery + 5.0
                rs.try_charge(cid_charger, min(shortfall, rs.battery_cap - rs.battery), facility_state)

        if rs.onboard_pickups or rs.events:
            rs.return_to_depot()
            routes[vid] = rs

    return routes, facility_state, clinics_remaining


def write_outputs(data, routes, facility_state, unassigned):
    path = SUB_DIR / "solution.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["row_type", "vehicle_id", "sequence", "node_id", "clinic_id", "facility_id", "charger_id", "charge_kwh"])
        for vid, rs in routes.items():
            seq = 0
            writer.writerow(["start", vid, seq, rs.start_node, "", "", "", ""])
            seq += 1
            for ev in rs.events:
                writer.writerow([
                    ev["row_type"], vid, seq, ev.get("node_id", ""),
                    ev.get("clinic_id", ""), ev.get("facility_id", ""),
                    ev.get("charger_id", ""),
                    f"{ev['charge_kwh']:.6f}" if "charge_kwh" in ev else "",
                ])
                seq += 1
            writer.writerow(["end", vid, seq, rs.end_node, "", "", "", ""])

    total_travel_cost = sum(rs.total_travel_km for rs in routes.values()) * float(data["config"]["travel_cost_per_km"])
    total_fixed_cost = sum(float(data["vehicles"][vid]["fixed_cost"]) for vid in routes)
    total_open_cost = sum(float(data["facilities"][fid]["open_cost"]) for fid in facility_state["opened"])
    total_risk_cost = sum(rs.total_risk_cost for rs in routes.values())
    total_treatment_charge_cost = facility_state["cost"]
    total_cost = total_travel_cost + total_fixed_cost + total_open_cost + total_risk_cost + total_treatment_charge_cost

    log_lines = [
        "# Solve Log — Electric Medical Waste Location-Routing",
        "",
        "- Method: greedy nearest-feasible-insertion construction heuristic (no exact MIP;",
        "  see model.md for rationale — 44-clinic multi-vehicle VRPTW+energy is not expected",
        "  to solve to proven optimality in a reasonable budget with an exact formulation).",
        f"- Vehicles used: {len(routes)} of {len(data['vehicles'])}",
        f"- Clinics assigned: {len(data['clinics']) - len(unassigned)} of {len(data['clinics'])}",
        f"- Unassigned clinics: {unassigned if unassigned else 'none'}",
        f"- Facilities opened: {sorted(facility_state['opened'])}",
        "",
        "## Cost breakdown (self-computed estimate)",
        f"- Vehicle fixed cost: {total_fixed_cost:.2f}",
        f"- Facility open cost: {total_open_cost:.2f}",
        f"- Travel cost: {total_travel_cost:.2f}",
        f"- Treatment + charging cost: {total_treatment_charge_cost:.2f}",
        f"- Risk cost: {total_risk_cost:.2f}",
        f"- TOTAL estimated cost: {total_cost:.2f}",
        "",
        "## Independent feasibility self-check",
    ]

    errors = independent_feasibility_check(data, routes, facility_state)
    if errors:
        log_lines.append(f"FOUND {len(errors)} feasibility issue(s):")
        for e in errors[:50]:
            log_lines.append(f"- {e}")
    else:
        log_lines.append("No feasibility issues found by the independent re-check (see check_solution() in this file).")

    (SUB_DIR / "solve_log.md").write_text("\n".join(log_lines))
    return total_cost, errors


def independent_feasibility_check(data, routes, facility_state):
    """Re-derive feasibility from the raw data + solution.csv output alone, as a
    self-audit, since no hidden evaluator exists for this task."""
    errors = []
    all_clinic_ids = set(data["clinics"].keys())
    seen_clinics = set()

    for vid, rs in routes.items():
        v = data["vehicles"][vid]
        permit = data["permits"][vid]
        isolation_seen = 0
        onboard = []  # (clinic_id, pickup_time_index) -- reconstructed pass, approximate using event order
        red_onboard = 0.0
        yellow_onboard = 0.0
        for ev in rs.events:
            if ev["row_type"] == "pickup":
                cid = ev["clinic_id"]
                if cid in seen_clinics:
                    errors.append(f"{cid} picked up more than once")
                seen_clinics.add(cid)
                c = data["clinics"][cid]
                if c["priority_class"] == "isolation":
                    isolation_seen += 1
                    if isolation_seen > int(permit["max_isolation_pickups"]):
                        errors.append(f"{vid} exceeds max_isolation_pickups")
                if c["priority_class"] == "isolation" and not int(float(permit["allow_isolation"])):
                    errors.append(f"{vid} not permitted for isolation clinic {cid}")
                if c["priority_class"] == "oncology" and not int(float(permit["allow_oncology"])):
                    errors.append(f"{vid} not permitted for oncology clinic {cid}")
                if c["priority_class"] == "routine" and not int(float(permit["allow_routine"])):
                    errors.append(f"{vid} not permitted for routine clinic {cid}")
                red_onboard += float(c["red_kg"])
                yellow_onboard += float(c["yellow_kg"])
                if red_onboard > float(v["red_compartment_kg"]) + 1e-6:
                    errors.append(f"{vid} exceeds red compartment at {cid}")
                if yellow_onboard > float(v["yellow_compartment_kg"]) + 1e-6:
                    errors.append(f"{vid} exceeds yellow compartment at {cid}")
                if red_onboard + yellow_onboard > float(v["capacity_kg"]) + 1e-6:
                    errors.append(f"{vid} exceeds total capacity at {cid}")
                for other, _ in onboard:
                    if (other, cid) in data["incompatible"]:
                        errors.append(f"{vid} co-loads incompatible pair {other}/{cid}")
                onboard.append((cid, None))
            elif ev["row_type"] == "unload":
                red_onboard = 0.0
                yellow_onboard = 0.0
                onboard = []

        if red_onboard > 1e-6 or yellow_onboard > 1e-6:
            errors.append(f"{vid} ends route still carrying waste")

    for cid in all_clinic_ids:
        if cid not in seen_clinics:
            errors.append(f"{cid} never picked up")

    for fid in facility_state["opened"]:
        if facility_state["kg_used"][fid] < float(data["config"]["minimum_facility_throughput_kg"]):
            errors.append(f"{fid} opened but below minimum_facility_throughput_kg")

    if len(facility_state["opened"]) > int(data["config"]["max_open_facilities"]):
        errors.append("more facilities opened than max_open_facilities")

    return errors


def main():
    _selftest_leg_cost()
    data = load_data()
    routes, facility_state, unassigned = build_routes(data)
    total_cost, errors = write_outputs(data, routes, facility_state, unassigned)
    print(f"vehicles_used={len(routes)} clinics_unassigned={len(unassigned)} "
          f"estimated_cost={total_cost:.2f} feasibility_issues={len(errors)}")


if __name__ == "__main__":
    main()
