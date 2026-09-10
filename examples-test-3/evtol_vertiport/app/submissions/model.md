# eVTOL Vertiport Recovery — Model (attempt 2)

**No hidden test/evaluator/reference files were consulted for this task, in either attempt.**
This model is derived only from `PROBLEM_STATEMENT.md` and `data/*`.

## What changed from attempt 1
Attempt 1 tried an exact time-space-network MIP (one binary per aircraft/slot/action,
simultaneous location-flow and turnaround constraints linking every slot to every other
slot for 12 aircraft x 3 scenarios x 32 slots at once). That formulation was abandoned
mid-build: the location-flow constraint (deriving "where is the aircraft now" from "which
flight, started at some earlier unknown slot, is still in the air") requires reasoning
about state carried across time, and writing all of that simultaneously, for the whole
instance, in one pass, produced tangled/incorrect constraint code that was never fixed.

Attempt 2 uses a **per-aircraft sequential state machine** instead (the same technique that
worked for `electric_medical_waste_lrp`'s routing problem): build one aircraft's schedule
at a time, slot by slot, in time order, so "what happens next" is always computed from
"what is true right now" — never from a search backward through history. This sidesteps the
location-flow bug category entirely, at the cost of being a heuristic construction, not an
exact optimizer. Given the instance size (12 aircraft x 3 scenarios x 32 slots x dozens of
routes/fleets/constraints), a heuristic is the pragmatic choice regardless of the state-flow
issue — matching the same reasoning applied to the waste-routing task.

## Problem shape
Two-stage: `accept[req]` decided once (shared across scenarios); per scenario, each aircraft
gets an independent schedule (flights, repositioning, charging) built forward in time.

## Construction approach (built and verified incrementally, smallest piece first)
1. **First-stage accept/decline**: greedily accept requests by fare-per-passenger density,
   subject to the global/medical/airport/priority-decline/origin-floor rules and group
   all-or-none linkage, checked directly against `config.json`/`origin_service_floors.csv`/
   `request_groups.csv` (no scenario dependency here at all).
2. **Per scenario, per aircraft, forward-time construction** (verified first on a single
   aircraft / single scenario slice before running across the full fleet):
   - Aircraft starts at `home_vertiport`, `release_slot`-adjusted, with derated SOC.
   - At each decision point, greedily pick the best next action among: fly an unserved
     accepted request reachable now, reposition toward a vertiport with unserved demand,
     or charge if battery is getting low -- each candidate action is *fully validated*
     (route open, fleet/lane/corridor/pad/grid/noise capacity remaining, battery reserve
     after the action, turnaround gap since the last action, aircraft service-window
     conflicts) against a live per-scenario resource ledger before being committed, exactly
     like `RouteState`/`facility_state` in the waste-routing solve.
   - Every accepted request must be served in *every* scenario (that's the two-stage
     guarantee) -- so request-to-aircraft-to-scenario assignment is solved once per scenario
     independently, but a request left unserved in any one scenario means the whole
     candidate accept-set is infeasible; in that case the request is retroactively
     downgraded to declined and the first-stage acceptance re-checked (bounded number of
     backoff rounds, not full backtracking search).
3. **Independent feasibility self-check** re-derives every hard rule from raw data + the
   emitted `solution.csv` rows alone, exactly as with the waste-routing task, since there is
   no hidden evaluator to check against.

## Modeling choices made where the brief is ambiguous
1. **Charging session length**: one session = enough slots to deliver the requested energy
   at `max_charge_kw` (derated by scenario `charger_derate`), rounded up to whole slots --
   a single contiguous block per session, occupying the aircraft and a charger slot for its
   full duration (unlike attempt 1's per-slot splitting; this is closer to a literal reading
   of "a charging session").
2. **Tapered high-SOC charging**: once projected SOC would cross `high_soc_threshold_fraction
   * battery_capacity_kwh`, the remaining energy above that threshold is added at
   `taper_charge_fraction` of the normal rate (more slots needed for the same kWh).
3. **Correction after re-checking the data (attempt 2, piece 2)**: there is no
   `fleet_types.csv` in this task -- aircraft fly their own passengers directly, unlike
   disaster-relief's separate truck/fleet dispatch layer. My first draft of this doc
   mistakenly imported that concept from the disaster-relief task; there is no fleet-choice
   step in this model at all. Caught before writing scheduling code, by testing piece 2 in
   isolation first.
4. **Tail-risk term**: as in attempt 1, no exact formula is stated. I use CVaR of
   `shortfall[sc] = max(0, target_profit[sc] - scenario_profit[sc])` at `tail_risk_alpha`,
   by analogy with the disaster-relief task's cost-side CVaR (same parameter names). This is
   a best-faith interpretation, not a verified spec, and is disclosed as such.
5. **Group departure-spread rule**: enforced only among group members that end up accepted
   (a whole group is accept/decline-linked in stage 1); within a scenario, if the group's
   served departures end up spread more than `max_departure_spread_slots`, the construction
   heuristic re-times the later member's departure to the earliest slot within that spread of
   the first member's actual departure, subject to that member's own window still being valid.

## Objective (estimated, self-reported -- no external scoring exists to check against)
```
first_stage_penalty = sum_req (1 - accept[req]) * decline_penalty[req]
scenario_profit[sc] = fare revenue - operating cost - reposition cost - charging cost
                       - delay penalties (per model.md attempt-1 formula, unchanged)
expected_profit = sum_sc probability[sc] * scenario_profit[sc]
objective = expected_profit - first_stage_penalty - tail_risk_weight * CVaR(shortfall)
```

## Output mapping
Unchanged from attempt 1: `accept`, `flight`, `reposition`, `charge` rows per the schema.
