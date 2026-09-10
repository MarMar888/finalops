"""eVTOL vertiport recovery: two-stage heuristic (attempt 2).

Built blind from PROBLEM_STATEMENT.md and data/ only. See model.md for why attempt 1
(exact time-space MIP) was abandoned and what changed here.
"""
import csv
import json
import math
from collections import defaultdict
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

    vertiports = {r["vertiport_id"]: r for r in read_csv(DATA_DIR / "vertiports.csv")}
    aircraft = {r["aircraft_id"]: r for r in read_csv(DATA_DIR / "aircraft.csv")}
    routes = {(r["origin"], r["destination"]): r for r in read_csv(DATA_DIR / "routes.csv")}
    requests = {r["request_id"]: r for r in read_csv(DATA_DIR / "requests.csv")}
    scenarios = {r["scenario_id"]: r for r in read_csv(DATA_DIR / "scenarios.csv")}
    time_slots = {int(r["slot"]): r for r in read_csv(DATA_DIR / "time_slots.csv")}
    fleets = {r["fleet_type"]: r for r in read_csv(DATA_DIR / "fleet_types.csv")} if (DATA_DIR / "fleet_types.csv").exists() else {}

    scen_route = {(r["scenario_id"], r["origin"], r["destination"]): r
                  for r in read_csv(DATA_DIR / "scenario_route_availability.csv")}
    scen_aircraft = {(r["scenario_id"], r["aircraft_id"]): r
                      for r in read_csv(DATA_DIR / "scenario_aircraft_availability.csv")}
    grid_prices = {(r["vertiport_id"], int(r["slot"])): r for r in read_csv(DATA_DIR / "grid_prices.csv")}
    origin_floors = {r["origin"]: float(r["minimum_accepted_passengers"])
                      for r in read_csv(DATA_DIR / "origin_service_floors.csv")}

    groups = defaultdict(list)
    group_spread = {}
    for r in read_csv(DATA_DIR / "request_groups.csv"):
        groups[r["group_id"]].append(r["request_id"])
        group_spread[r["group_id"]] = int(r["max_departure_spread_slots"])

    service_windows = read_csv(DATA_DIR / "aircraft_service_windows.csv")
    reserve_reqs = read_csv(DATA_DIR / "emergency_reserve_requirements.csv")
    corridor_controls = read_csv(DATA_DIR / "corridor_slot_controls.csv")

    return {
        "config": config, "vertiports": vertiports, "aircraft": aircraft, "routes": routes,
        "requests": requests, "scenarios": scenarios, "time_slots": time_slots, "fleets": fleets,
        "scen_route": scen_route, "scen_aircraft": scen_aircraft, "grid_prices": grid_prices,
        "origin_floors": origin_floors, "groups": groups, "group_spread": group_spread,
        "service_windows": service_windows, "reserve_reqs": reserve_reqs,
        "corridor_controls": corridor_controls,
    }


# ---------- Piece 1: first-stage accept/decline (no scheduling, no scenarios) ----------
def choose_accepted_requests(data):
    """Greedy accept by fare density, enforcing all first-stage floors/caps.
    Verified in isolation (piece 1) before any scheduling logic is written."""
    config = data["config"]
    reqs = data["requests"]
    groups = data["groups"]

    req_to_group = {}
    for gid, members in groups.items():
        for rid in members:
            req_to_group[rid] = gid

    # score standalone requests and groups (as a unit) by total fare density
    def request_value(rid):
        r = reqs[rid]
        return float(r["fare_per_passenger"]) * float(r["passengers"])

    units = []  # list of (value, list_of_request_ids)
    seen = set()
    for rid in reqs:
        if rid in seen:
            continue
        gid = req_to_group.get(rid)
        if gid:
            members = groups[gid]
            units.append((sum(request_value(m) for m in members), members))
            seen.update(members)
        else:
            units.append((request_value(rid), [rid]))
            seen.add(rid)
    units.sort(key=lambda u: -u[0])

    accept = {rid: False for rid in reqs}
    total_passengers = sum(float(r["passengers"]) for r in reqs.values())
    medical_passengers = sum(float(r["passengers"]) for r in reqs.values() if r["priority_class"] == "medical")

    def accepted_passengers(priority=None, market=None, origin=None):
        total = 0.0
        for rid, ok in accept.items():
            if not ok:
                continue
            r = reqs[rid]
            if priority and r["priority_class"] != priority:
                continue
            if market and r["market"] != market:
                continue
            if origin and r["origin"] != origin:
                continue
            total += float(r["passengers"])
        return total

    def declined_priority_count():
        return sum(
            1 for rid, ok in accept.items()
            if not ok and reqs[rid]["priority_class"] in ("airport", "medical")
        )

    # Pass 1: accept everything (greedy by value) that doesn't need special floor protection,
    # then verify floors afterward and backfill if short.
    for value, members in units:
        for rid in members:
            accept[rid] = True

    # Enforce maximum_declined_priority_requests: with everything accepted, this is trivially
    # satisfied (0 declines). It only becomes a binding constraint if we later decline requests
    # for capacity reasons -- this heuristic doesn't model vehicle capacity in stage 1 (that's
    # scenario-schedule feasibility, checked in piece 2/3), so stage 1 always starts from
    # "accept everything the floors/caps allow" and only declines when schedule construction
    # later proves a request can't be served in some scenario (see downgrade_request()).

    # Verify floors (accepting everything should satisfy all "minimum" floors trivially since
    # they're all <= 100% of the accept-everything totals by construction of the data, but
    # check explicitly rather than assume):
    assert accepted_passengers() >= float(config["minimum_accepted_passenger_fraction"]) * total_passengers
    if medical_passengers > 0:
        assert accepted_passengers(priority="medical") >= float(config["minimum_medical_accepted_fraction"]) * medical_passengers
    assert accepted_passengers(market="airport") >= float(config["minimum_airport_accepted_passengers"])
    assert declined_priority_count() <= int(config["maximum_declined_priority_requests"])
    for origin, floor in data["origin_floors"].items():
        assert accepted_passengers(origin=origin) >= floor, f"origin floor violated for {origin}"

    return accept


def downgrade_request(accept, data, rid):
    """Decline a request (and its whole group, if any) after schedule construction proves
    it cannot be served in some scenario. Re-checks floors; raises if that breaks a hard
    minimum (in which case the heuristic has no valid accept-set for this instance size --
    disclosed honestly rather than silently forcing an infeasible schedule)."""
    config = data["config"]
    reqs = data["requests"]
    gid = None
    for g, members in data["groups"].items():
        if rid in members:
            gid = g
            break
    to_decline = data["groups"][gid] if gid else [rid]
    for r in to_decline:
        accept[r] = False

    total_passengers = sum(float(r["passengers"]) for r in reqs.values())
    medical_passengers = sum(float(r["passengers"]) for r in reqs.values() if r["priority_class"] == "medical")
    accepted_pax = sum(float(reqs[r]["passengers"]) for r, ok in accept.items() if ok)
    accepted_medical = sum(float(reqs[r]["passengers"]) for r, ok in accept.items() if ok and reqs[r]["priority_class"] == "medical")
    accepted_airport = sum(float(reqs[r]["passengers"]) for r, ok in accept.items() if ok and reqs[r]["market"] == "airport")
    declined_priority = sum(1 for r, ok in accept.items() if not ok and reqs[r]["priority_class"] in ("airport", "medical"))

    if accepted_pax < float(config["minimum_accepted_passenger_fraction"]) * total_passengers:
        return False, "would breach minimum_accepted_passenger_fraction"
    if medical_passengers > 0 and accepted_medical < float(config["minimum_medical_accepted_fraction"]) * medical_passengers:
        return False, "would breach minimum_medical_accepted_fraction"
    if accepted_airport < float(config["minimum_airport_accepted_passengers"]):
        return False, "would breach minimum_airport_accepted_passengers"
    if declined_priority > int(config["maximum_declined_priority_requests"]):
        return False, "would breach maximum_declined_priority_requests"
    for origin, floor in data["origin_floors"].items():
        accepted_origin = sum(float(reqs[r]["passengers"]) for r, ok in accept.items() if ok and reqs[r]["origin"] == origin)
        if accepted_origin < floor:
            return False, f"would breach origin_floor for {origin}"
    return True, "ok"


def route_lookup(data, o, d):
    return data["routes"].get((o, d))


def scen_route_lookup(data, sc, o, d):
    return data["scen_route"].get((sc, o, d))


def route_duration_slots(data, sc, o, d):
    route = route_lookup(data, o, d)
    sr = scen_route_lookup(data, sc, o, d)
    if route is None or sr is None or int(float(sr["open"])) != 1:
        return None
    return max(1, math.ceil(float(route["flight_slots"]) * float(sr["flight_slot_multiplier"])))


def route_energy(data, sc, o, d):
    route = route_lookup(data, o, d)
    sr = scen_route_lookup(data, sc, o, d)
    return float(route["energy_kwh"]) * float(sr["energy_multiplier"])


class AircraftSchedule:
    """Per-(scenario, aircraft) forward-time state machine. Every mutation goes through
    one of the try_* methods, which validate against the live resource ledger before
    committing -- mirroring the RouteState design from the waste-routing task, since that
    is the technique that worked there for carryover state (time, battery, location)."""

    def __init__(self, data, sc, aid):
        self.data = data
        self.sc = sc
        self.aid = aid
        ac = data["aircraft"][aid]
        sa = data["scen_aircraft"].get((sc, aid))
        self.home = ac["home_vertiport"]
        self.node = self.home
        self.battery_cap = float(ac["battery_capacity_kwh"])
        derate = float(sa["soc_derate"]) if sa else 1.0
        self.battery = float(ac["initial_soc_kwh"]) * derate
        self.slot = int(sa["release_slot"]) if sa else 0
        self.seat_capacity = int(ac["seat_capacity"])
        self.max_charge_kw = float(ac["max_charge_kw"])
        self.noise_class = float(ac["noise_class"])
        self.turnaround = int(ac["turnaround_slots"])
        self.next_available_slot = self.slot  # >= this before starting any new action
        self.events = []  # dicts matching solution.csv row shape (minus scenario/aircraft)

    def slot_minutes(self):
        return float(self.data["config"]["slot_minutes"])

    def can_fly(self, req_id, horizon):
        """Earliest-slot-only check (kept for the piece-2/3 self-tests and as the
        aircraft-only feasibility gate before a resource-ledger search)."""
        data = self.data
        r = data["requests"][req_id]
        o, d = r["origin"], r["destination"]
        if o != self.node:
            return False, None, None
        dur = route_duration_slots(data, self.sc, o, d)
        if dur is None:
            return False, None, None
        earliest, latest = int(r["earliest_slot"]), int(r["latest_depart_slot"])
        start = max(self.next_available_slot, earliest)
        if start > latest:
            return False, None, None
        if start + dur > horizon:
            return False, None, None
        energy = route_energy(data, self.sc, o, d)
        reserve = float(data["config"]["reserve_soc_kwh"])
        if self.battery - energy < reserve - 1e-6:
            return False, None, None
        return True, start, dur

    def feasible_fly_slots(self, req_id, horizon):
        """All aircraft-feasible departure slots for req_id within its window (not just
        the earliest) -- needed because a shared corridor/pad may be full at the
        earliest slot but open a few slots later, still within the request's window."""
        data = self.data
        r = data["requests"][req_id]
        o, d = r["origin"], r["destination"]
        if o != self.node:
            return []
        dur = route_duration_slots(data, self.sc, o, d)
        if dur is None:
            return []
        earliest, latest = int(r["earliest_slot"]), int(r["latest_depart_slot"])
        energy = route_energy(data, self.sc, o, d)
        reserve = float(data["config"]["reserve_soc_kwh"])
        if self.battery - energy < reserve - 1e-6:
            return []
        lo = max(self.next_available_slot, earliest)
        return [t for t in range(lo, latest + 1) if t + dur <= horizon]

    def can_reposition(self, dest, horizon):
        data = self.data
        o = self.node
        if o == dest:
            return False, None, None
        dur = route_duration_slots(data, self.sc, o, dest)
        if dur is None:
            return False, None, None
        start = self.next_available_slot
        if start + dur > horizon:
            return False, None, None
        energy = route_energy(data, self.sc, o, dest)
        reserve = float(data["config"]["reserve_soc_kwh"])
        if self.battery - energy < reserve - 1e-6:
            return False, None, None
        return True, start, dur

    def do_reposition(self, dest, start, dur):
        data = self.data
        o = self.node
        energy = route_energy(data, self.sc, o, dest)
        self.battery -= energy
        self.node = dest
        self.slot = start + dur
        self.next_available_slot = self.slot + self.turnaround
        self.events.append({
            "row_type": "reposition", "origin": o, "destination": dest,
            "start_slot": start, "end_slot": start + dur, "energy_kwh": energy,
        })

    def do_fly(self, req_id, start, dur):
        data = self.data
        r = data["requests"][req_id]
        o, d = r["origin"], r["destination"]
        energy = route_energy(data, self.sc, o, d)
        self.battery -= energy
        self.node = d
        self.slot = start + dur
        self.next_available_slot = self.slot + self.turnaround
        self.events.append({
            "row_type": "flight", "request_id": req_id, "origin": o, "destination": d,
            "start_slot": start, "end_slot": start + dur, "energy_kwh": energy,
            "quantity": float(r["passengers"]),
        })

    def can_charge(self, horizon):
        data = self.data
        cfg = data["config"]
        if self.battery >= self.battery_cap - 1e-6:
            return False, 0, 0.0
        threshold = float(cfg["high_soc_threshold_fraction"]) * self.battery_cap
        needed = self.battery_cap - self.battery
        rate = self.max_charge_kw * self.slot_minutes() / 60.0
        # simple duration estimate; tapering reduces effective rate above threshold
        if self.battery >= threshold:
            eff_rate = rate * float(cfg["taper_charge_fraction"])
        else:
            below = threshold - self.battery
            slots_below = math.ceil(below / rate) if rate > 0 else 0
            above = needed - below
            slots_above = math.ceil(above / (rate * float(cfg["taper_charge_fraction"]))) if above > 0 and rate > 0 else 0
            total_slots = max(1, slots_below + slots_above)
            start = self.next_available_slot
            if start + total_slots > horizon:
                return False, 0, 0.0
            return True, total_slots, needed
        slots = max(1, math.ceil(needed / eff_rate)) if eff_rate > 0 else 1
        start = self.next_available_slot
        if start + slots > horizon:
            return False, 0, 0.0
        return True, slots, needed

    def do_charge(self, slots, energy_kwh):
        start = self.next_available_slot
        self.battery = min(self.battery_cap, self.battery + energy_kwh)
        self.slot = start + slots
        self.next_available_slot = self.slot
        self.events.append({
            "row_type": "charge", "start_slot": start, "end_slot": start + slots,
            "energy_kwh": energy_kwh,
        })


def _piece2_selftest():
    """Build one aircraft's schedule in one scenario, with zero accepted requests routed
    to it yet -- just verifying the state machine's fly/charge mechanics are internally
    consistent before wiring in the full multi-aircraft assignment loop."""
    data = load_data()
    sc = "S_CLEAR"
    aid = "A01"
    horizon = int(data["config"]["planning_horizon_slots"])
    sched = AircraftSchedule(data, sc, aid)

    start_battery = sched.battery
    start_node = sched.node
    assert start_node == "V_DOWNTOWN", f"expected A01 home V_DOWNTOWN, got {start_node}"

    # try a real request from the data: pick one whose origin matches A01's home
    candidate = None
    for rid, r in data["requests"].items():
        if r["origin"] == start_node:
            candidate = rid
            break
    assert candidate is not None, "no candidate request found from A01's home vertiport"

    ok, start, dur = sched.can_fly(candidate, horizon)
    assert ok, f"expected {candidate} to be flyable from {start_node} at slot {sched.next_available_slot}"
    sched.do_fly(candidate, start, dur)
    assert sched.node == data["requests"][candidate]["destination"]
    assert sched.battery < start_battery, "battery should have decreased after a flight"
    assert sched.next_available_slot == start + dur + sched.turnaround

    print(f"[piece 2] selftest OK: flew {candidate} from {start_node} to {sched.node}, "
          f"battery {start_battery:.1f} -> {sched.battery:.1f}, "
          f"next_available_slot={sched.next_available_slot}")
    return sched, data, horizon


class ResourceLedger:
    """Tracks shared per-scenario, per-slot resource usage (pad, charger, corridor, grid,
    noise) across all aircraft, so each aircraft's action can be checked against what
    everyone else has already committed. One ledger per scenario."""

    def __init__(self, data, sc):
        self.data = data
        self.sc = sc
        self.pad_departures = defaultdict(int)    # (vertiport, slot) -> count
        self.pad_arrivals = defaultdict(int)      # (vertiport, slot) -> count
        self.corridor_flights = defaultdict(int)  # (corridor, slot) -> count
        self.charging_sessions = defaultdict(int)  # (vertiport, slot) -> count
        self.grid_kwh = defaultdict(float)        # (vertiport, slot) -> kwh added this slot
        self.noise_day = defaultdict(float)       # vertiport -> cumulative points
        self.noise_evening = defaultdict(float)

    def corridor_capacity(self, corridor, start, dur):
        """Minimum per-slot capacity across the flight's occupied slots, applying any
        active corridor_slot_controls override for this scenario."""
        route_caps = [float(r["corridor_capacity_per_slot"]) for r in self.data["routes"].values()
                      if r["corridor_id"] == corridor]
        base_cap = min(route_caps) if route_caps else math.inf
        min_cap = base_cap
        for ctrl in self.data["corridor_controls"]:
            if ctrl["scenario_id"] != self.sc or ctrl["corridor_id"] != corridor:
                continue
            cstart, cend = int(ctrl["start_slot"]), int(ctrl["end_slot"])
            for t in range(start, start + dur):
                if cstart <= t < cend:
                    min_cap = min(min_cap, int(ctrl["max_flights_per_slot"]))
        return min_cap

    def can_fly_resources(self, o, d, start, dur, load_points, noise_points, period_for_slot):
        vps = self.data["vertiports"]
        pad_o, pad_d = int(vps[o]["pad_count"]), int(vps[d]["pad_count"])
        if self.pad_departures[(o, start)] + 1 > pad_o:
            return False, "pad departure capacity"
        if self.pad_arrivals[(d, start + dur)] + 1 > pad_d:
            return False, "pad arrival capacity"

        route = self.data["routes"][(o, d)]
        corridor = route["corridor_id"]
        cap = self.corridor_capacity(corridor, start, dur)
        for t in range(start, start + dur):
            if self.corridor_flights[(corridor, t)] + 1 > cap:
                return False, "corridor capacity"

        period = period_for_slot(start)
        quota_key = "departure_noise_quota_day" if period == "day" else "departure_noise_quota_evening"
        current = self.noise_day[o] if period == "day" else self.noise_evening[o]
        if current + noise_points > float(vps[o][quota_key]) + 1e-6:
            return False, "noise quota"

        return True, "ok"

    def commit_fly(self, o, d, start, dur, noise_points, period_for_slot):
        self.pad_departures[(o, start)] += 1
        self.pad_arrivals[(d, start + dur)] += 1
        route = self.data["routes"][(o, d)]
        corridor = route["corridor_id"]
        for t in range(start, start + dur):
            self.corridor_flights[(corridor, t)] += 1
        period = period_for_slot(start)
        if period == "day":
            self.noise_day[o] += noise_points
        else:
            self.noise_evening[o] += noise_points

    def can_charge_resources(self, v, start, slots, charger_count, energy_kwh, grid_limit_kw, grid_multiplier):
        slot_minutes = float(self.data["config"]["slot_minutes"])
        for t in range(start, start + slots):
            if self.charging_sessions[(v, t)] + 1 > charger_count:
                return False, "charger capacity"
        per_slot_kwh = energy_kwh / max(1, slots)
        grid_cap_per_slot = grid_limit_kw * grid_multiplier * (slot_minutes / 60.0)
        for t in range(start, start + slots):
            if self.grid_kwh[(v, t)] + per_slot_kwh > grid_cap_per_slot + 1e-6:
                return False, "grid headroom"
        return True, "ok"

    def commit_charge(self, v, start, slots, energy_kwh):
        per_slot_kwh = energy_kwh / max(1, slots)
        for t in range(start, start + slots):
            self.charging_sessions[(v, t)] += 1
            self.grid_kwh[(v, t)] += per_slot_kwh


def period_for_slot(data, slot):
    return data["time_slots"][slot]["period"]


def _piece4_selftest():
    """Verify the resource ledger actually blocks a double-booked pad/corridor before
    wiring it into the multi-aircraft loop -- test can_fly_resources/commit_fly directly,
    including a deliberately-forced conflict, not just the happy path."""
    data = load_data()
    o, d = "V_DOWNTOWN", "V_AIRPORT"
    pad_count = int(data["vertiports"][o]["pad_count"])
    route = data["routes"][(o, d)]
    corridor = route["corridor_id"]
    corridor_cap = min(
        float(r["corridor_capacity_per_slot"]) for r in data["routes"].values() if r["corridor_id"] == corridor
    )
    dur = route_duration_slots(data, "S_CLEAR", o, d)
    noise_points = float(route["noise_points"]) * 1.0

    ledger = ResourceLedger(data, "S_CLEAR")
    pf = lambda slot: period_for_slot(data, slot)

    # fill the pad to capacity with distinct flights departing at the same slot
    for i in range(pad_count):
        ok, reason = ledger.can_fly_resources(o, d, 0, dur, noise_points, noise_points, pf)
        assert ok, f"expected departure {i} to fit within pad_count={pad_count}, got: {reason}"
        ledger.commit_fly(o, d, 0, dur, noise_points, pf)

    # one more departure at the same vertiport/slot should now be rejected
    ok, reason = ledger.can_fly_resources(o, d, 0, dur, noise_points, noise_points, pf)
    assert not ok and reason == "pad departure capacity", (
        f"expected pad capacity to reject the {pad_count + 1}th simultaneous departure, got ok={ok} reason={reason}"
    )

    # a departure at a different slot should still be fine (pad capacity is per-slot)
    ok, reason = ledger.can_fly_resources(o, d, 20, dur, noise_points, noise_points, pf)
    assert ok, f"expected a departure at a different slot to be unaffected, got: {reason}"

    print(f"[piece 4] selftest OK: pad capacity ({pad_count}) correctly blocks the "
          f"{pad_count + 1}th simultaneous departure from {o}; a later slot is unaffected. "
          f"corridor '{corridor}' per-slot capacity={corridor_cap}")


def _piece3_selftest(sched, data, horizon):
    """Charge the same aircraft (now at reduced battery after piece 2's flight) back up,
    verified in isolation before wiring charging into the full construction loop."""
    battery_before = sched.battery
    ok, slots, energy = sched.can_charge(horizon)
    assert ok, "expected charging to be possible with battery below capacity"
    assert energy > 0, "expected positive charge energy"
    assert slots >= 1
    sched.do_charge(slots, energy)
    assert sched.battery > battery_before, "battery should have increased after charging"
    assert sched.battery <= sched.battery_cap + 1e-6, "battery must not exceed capacity"
    print(f"[piece 3] selftest OK: charged {energy:.1f} kWh over {slots} slot(s), "
          f"battery {battery_before:.1f} -> {sched.battery:.1f} (cap {sched.battery_cap:.1f})")


def try_fly(sched, ledger, req_id, horizon, period_for_slot_fn):
    """Combined aircraft-state + shared-resource check for one flight. Searches every
    aircraft-feasible departure slot in the request's window (not just the earliest),
    since a shared corridor/pad can be full at the earliest slot but free later --
    the single-earliest-slot version stalled well below full coverage on this
    instance because ~76% of requests share one corridor with capacity 2/slot.
    Returns (ok, start, dur) without mutating anything."""
    data = sched.data
    r = data["requests"][req_id]
    o, d = r["origin"], r["destination"]
    route = data["routes"].get((o, d))
    if route is None:
        return False, None, None
    for start in sched.feasible_fly_slots(req_id, horizon):
        dur = route_duration_slots(data, sched.sc, o, d)
        noise_points = float(route["noise_points"]) * sched.noise_class
        ok2, reason = ledger.can_fly_resources(o, d, start, dur, noise_points, noise_points, period_for_slot_fn)
        if ok2:
            return True, start, dur
    return False, None, None


def commit_fly_action(sched, ledger, req_id, start, dur, period_for_slot_fn):
    data = sched.data
    r = data["requests"][req_id]
    o, d = r["origin"], r["destination"]
    route = data["routes"][(o, d)]
    noise_points = float(route["noise_points"]) * sched.noise_class
    sched.do_fly(req_id, start, dur)
    ledger.commit_fly(o, d, start, dur, noise_points, period_for_slot_fn)


def try_reposition(sched, ledger, dest, horizon, period_for_slot_fn):
    ok, start, dur = sched.can_reposition(dest, horizon)
    if not ok:
        return False, None, None
    data = sched.data
    o = sched.node
    route = data["routes"][(o, dest)]
    noise_points = float(route["noise_points"]) * sched.noise_class
    ok2, reason = ledger.can_fly_resources(o, dest, start, dur, noise_points, noise_points, period_for_slot_fn)
    if not ok2:
        return False, None, None
    return True, start, dur


def commit_reposition_action(sched, ledger, dest, start, dur, period_for_slot_fn):
    data = sched.data
    o = sched.node
    route = data["routes"][(o, dest)]
    noise_points = float(route["noise_points"]) * sched.noise_class
    sched.do_reposition(dest, start, dur)
    ledger.commit_fly(o, dest, start, dur, noise_points, period_for_slot_fn)


def try_charge(sched, ledger, horizon):
    ok, slots, energy = sched.can_charge(horizon)
    if not ok:
        return False, None, None
    data = sched.data
    vp = data["vertiports"][sched.node]
    charger_count = int(vp["charger_count"])
    grid_limit_kw = float(vp["grid_kw_limit"])
    start = sched.next_available_slot
    grid_key = (sched.node, start)
    grid_row = data["grid_prices"].get(grid_key)
    grid_multiplier = float(grid_row["grid_limit_multiplier"]) if grid_row else 1.0
    ok2, reason = ledger.can_charge_resources(sched.node, start, slots, charger_count, energy, grid_limit_kw, grid_multiplier)
    if not ok2:
        return False, None, None
    return True, slots, energy


def commit_charge_action(sched, ledger, slots, energy):
    ledger.commit_charge(sched.node, sched.next_available_slot, slots, energy)
    sched.do_charge(slots, energy)


def build_scenario_schedule(data, sc, accepted_ids):
    """Greedy construction for one scenario: repeatedly pick, across all aircraft, the
    best (aircraft, request) pairing among still-unserved accepted requests, until no
    more progress can be made. Charges an aircraft opportunistically when it cannot
    reach any remaining assignable request without doing so first."""
    horizon = int(data["config"]["planning_horizon_slots"])
    pf = lambda slot: period_for_slot(data, slot)
    ledger = ResourceLedger(data, sc)
    schedules = {aid: AircraftSchedule(data, sc, aid) for aid in data["aircraft"]}
    unserved = set(accepted_ids)
    served = set()

    progress = True
    while progress and unserved:
        progress = False

        # Process the most time-urgent unserved request first (soonest
        # latest_depart_slot). For that request, prefer whichever capable aircraft can
        # depart SOONEST (smallest actual start slot), not whichever is cheapest --
        # cost-based selection stalled at ~20/49 because it kept picking a cheap-but-
        # already-busy-later aircraft over one that was idle right now, so aircraft got
        # tied up on low-priority work while urgent requests ran out of eligible planes.
        urgent_order = sorted(unserved, key=lambda rid: int(data["requests"][rid]["latest_depart_slot"]))
        assigned_rid = None
        for rid in urgent_order:
            best = None  # (start, aid, dur)
            for aid, sched in schedules.items():
                ok, start, dur = try_fly(sched, ledger, rid, horizon, pf)
                if ok and (best is None or start < best[0]):
                    best = (start, aid, dur)
            if best is not None:
                start, aid, dur = best
                commit_fly_action(schedules[aid], ledger, rid, start, dur, pf)
                unserved.discard(rid)
                served.add(rid)
                assigned_rid = rid
                progress = True
                break  # re-sort by urgency after every single commit, state has changed

        if assigned_rid is not None:
            continue

        # No aircraft can directly serve any remaining request right now. Try
        # repositioning the aircraft with the shortest reachable hop toward an
        # unserved request's origin.
        reposition_best = None  # (dur, aid, dest, start)
        unserved_origins = {data["requests"][rid]["origin"] for rid in unserved}
        for aid, sched in schedules.items():
            for dest in unserved_origins:
                ok, start, dur = try_reposition(sched, ledger, dest, horizon, pf)
                if ok and (reposition_best is None or dur < reposition_best[0]):
                    reposition_best = (dur, aid, dest, start)
        if reposition_best is not None:
            dur, aid, dest, start = reposition_best
            commit_reposition_action(schedules[aid], ledger, dest, start, dur, pf)
            progress = True
            continue

        # Still stuck -- try charging the lowest-battery aircraft to unstick things.
        candidates = sorted(schedules.values(), key=lambda s: s.battery / s.battery_cap)
        for sched in candidates:
            ok, slots, energy = try_charge(sched, ledger, horizon)
            if ok:
                commit_charge_action(sched, ledger, slots, energy)
                progress = True
                break
        # if nothing progressed this round (no fly/reposition/charge worked for anyone),
        # the while-loop condition (progress False) ends the construction naturally.

    return schedules, unserved


if __name__ == "__main__":
    # Piece 1 self-test
    data = load_data()
    accept = choose_accepted_requests(data)
    n_accept = sum(accept.values())
    n_total = len(accept)
    print(f"[piece 1] accepted {n_accept}/{n_total} requests; all first-stage floors verified OK")

    # Piece 2 self-test (single aircraft, single scenario, single flight)
    sched, _data, horizon = _piece2_selftest()

    # Piece 3 self-test (charge the same aircraft back up)
    _piece3_selftest(sched, _data, horizon)

    # Piece 4 self-test (shared resource ledger: pad/corridor capacity)
    _piece4_selftest()

    # Piece 5 smoke test: build one scenario's schedule for just the FIRST 5 accepted
    # requests (not all 49), to check the integrated loop terminates and behaves
    # sensibly before running it on the full accepted set across all 3 scenarios.
    accepted_ids = [rid for rid, ok in accept.items() if ok]
    small_slice = accepted_ids[:5]
    schedules, unserved = build_scenario_schedule(data, "S_CLEAR", small_slice)
    n_served = len(small_slice) - len(unserved)
    print(f"[piece 5] smoke test OK: scenario S_CLEAR, {n_served}/{len(small_slice)} of a "
          f"5-request slice served, {len(unserved)} unserved: {unserved}")

    # Piece 6: run the FULL accepted set against one scenario, to see real-scale behavior
    # before wiring in the two-stage downgrade loop across all 3 scenarios.
    schedules_full, unserved_full = build_scenario_schedule(data, "S_CLEAR", accepted_ids)
    n_served_full = len(accepted_ids) - len(unserved_full)
    print(f"[piece 6] full-scale single-scenario test: S_CLEAR, {n_served_full}/{len(accepted_ids)} "
          f"accepted requests served, {len(unserved_full)} unserved: {sorted(unserved_full)}")
