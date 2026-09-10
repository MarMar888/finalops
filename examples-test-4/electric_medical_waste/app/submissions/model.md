# Electric Medical Waste Location-Routing — Model

**No hidden test/evaluator/reference files exist for this task in the public packet**
(the brief states explicitly: "The hidden evaluator is not available in the public agent
environment"), and none were sought out. This model is derived only from
`PROBLEM_STATEMENT.md` and `data/*`.

## Problem class
This is a multi-vehicle routing problem with time windows, split delivery via unloads
(not classic VRP — unload events reset onboard load, effectively multiple sub-routes per
vehicle per day), compartment capacity by waste class, onboard-time limits per waste class,
vehicle-clinic compatibility (permits + isolation cap), pairwise incompatibility, battery/energy
consumption with optional recharging, facility capacity/window/count limits, and a
loaded-link curfew. This is a genuinely large combinatorial problem (44 clinics, 8 vehicles,
56-node complete graph); an exact arc-based MIP at full scale is unlikely to solve to proven
optimality in the time budget, so the approach below is deliberately a **construction
heuristic with local-search improvement**, not an exact MIP — matching the brief's framing
("low-cost, operationally credible plan") rather than assuming a provably optimal answer is
attainable, and consistent with the general OR guidance that large VRPs are usually solved
by heuristics, not exact solvers, in practice.

## Approach (chosen deliberately, and built incrementally — see solve.py's staged structure)
1. **Nearest-feasible-insertion route construction per vehicle**, one vehicle at a time:
   greedily build each vehicle's route by repeatedly inserting the cheapest feasible
   next clinic (by travel cost) subject to time-window, compartment-capacity,
   onboard-time, permit, isolation-cap, and pairwise-incompatibility constraints, inserting
   an unload event (choosing the best compatible, still-open facility/window) whenever the
   vehicle's load would otherwise breach a limit or an onboard-time deadline is approaching.
2. **Energy tracked explicitly along the route** at each step; a charge stop is inserted
   (at the nearest feasible charger) whenever projected battery would go negative before the
   next unload/depot return, respecting charger daily-energy/session caps.
3. **Curfew handling**: if a loaded arc traversal would start inside
   `[curfew_start_min, curfew_end_min]`, the vehicle waits at its current node until
   `curfew_end_min` before departing (brief: "it may wait until the window clears").
4. **2-opt-style local improvement pass** over each vehicle's finished route (swap
   adjacent clinic visits when doing so does not break any hard constraint and reduces
   total travel distance), run to convergence or a fixed iteration cap.
5. Vehicles are used in the order listed; a vehicle is left completely unused (no `start`/`end`
   rows... actually brief implies every listed vehicle is available, not mandatory to use —
   see Modeling choice 1) if all remaining clinics are already assigned.

This is a heuristic, not an exact optimizer — I am explicitly not claiming global optimality,
and `solve_log.md` records the independent feasibility self-check performed against the raw
data (since no hidden evaluator exists to check against).

## Modeling choices made where the brief is ambiguous
1. **Vehicle usage is optional.** The brief describes "a used vehicle" (implying not all
   8 need be used) and cost includes "vehicle use" as a chargeable item, so unused vehicles
   should not appear in the output at all (no rows), and a solution using fewer vehicles is
   preferred when it doesn't sacrifice feasibility, since fixed cost is charged per vehicle used.
2. **Onboard risk cost.** "Risk is higher when red-bag waste stays on vehicles longer or moves
   through denser urban links" with `red_risk_factor`/`yellow_risk_factor`/`risk_cost_per_unit`
   in config. I model per-arc-traversal risk as:
   `risk_cost_per_unit * population_risk_index[arc] * arc_travel_min *
   (red_kg_onboard * red_risk_factor + yellow_kg_onboard * yellow_risk_factor)`,
   i.e., risk accrues proportional to time-on-arc times onboard mass times class risk factor
   times the arc's population density index — the most direct linear reading of "risk is higher
   when waste stays onboard longer (time) or moves through denser links (population_risk_index)."
   Curfew *waiting* time also accrues this same risk while loaded, per
   `loaded_wait_risk_multiplier` (brief: "the waiting time still counts for shift time and
   onboard-risk exposure") — modeled as `risk_cost_per_unit * loaded_wait_risk_multiplier *
   wait_min * (red_kg_onboard*red_risk_factor + yellow_kg_onboard*yellow_risk_factor)`.
3. **Energy per arc.** "Energy use depends on the listed empty-trip energy plus the current
   onboard load and distance," and config gives `load_energy_kwh_per_kg_km`. Modeled as
   `empty_energy_kwh[arc] + load_energy_kwh_per_kg_km * onboard_kg * distance_km[arc]`.
4. **Minimum facility throughput.** "Any opened facility must receive a meaningful minimum
   amount of waste" + `minimum_facility_throughput_kg` in config: enforced as a post-hoc check
   (if a facility receives less than this across the whole day, either route more waste to it
   or avoid opening it at all) rather than a variable in the greedy construction, since with a
   heuristic builder this is verified after construction, not baked into per-step choices.
5. **Facility "permit class"** (`sterilization_permit`: advanced/standard/yellow_only) has no
   stated linkage to clinic priority class or waste type beyond what `facility_waste_rules.csv`
   already encodes (F4 is yellow_only and indeed shows `red: accepted=0` there) — treated as
   redundant/descriptive metadata already captured by `facility_waste_rules.csv`'s `accepted`
   column, not an additional hard constraint, since the brief never explicitly ties clinic
   priority class to facility permit class (only to *vehicle* permits).
6. **Isolation pickup cap** (`max_isolation_pickups` per vehicle) counted as: number of
   `isolation`-priority-class clinics visited by that vehicle across the whole day (brief:
   "daily cap on isolation pickups").

## Objective (minimize total planning cost)
```
total_cost = sum_used_vehicles fixed_cost[v]
           + sum_opened_facilities open_cost[f]
           + travel_cost_per_km * sum_arcs distance_km[arc]
           + sum_charge_events charge_kwh * energy_price[charger]
           + sum_unload_events sum_class treated_kg[class] * treatment_cost_per_kg[f,class]
           + risk_cost_per_unit * sum_arc_traversals_and_waits (as in choice 2 above)
```

## Output mapping
- `start`/`end` rows: one pair per used vehicle only.
- `pickup` rows: one per clinic visited (every clinic must appear exactly once, across the
  whole solution).
- `unload` rows: one per unload event on a route.
- `charge` rows: one per charging stop, with positive `charge_kwh`.
