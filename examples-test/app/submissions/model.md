# Model: Air Cargo Stochastic Order Allocation

## 1. Decision

Each booking request is either accepted and committed to exactly one eligible
aircraft, or not accepted. This is a here-and-now (first-stage) decision made
before demand/capacity uncertainty resolves; the same acceptance/assignment
plan is evaluated against every scenario.

## 2. Sets and indices

- `O` — orders (booking requests), index `o`. |O| = 42.
- `K` — aircraft, index `k`. |K| = 7.
- `S` — scenarios, index `s`. |S| = 12.
- `G` — customer segments, index `g` (pharma, express, perishables, ecommerce,
  industrial, automotive, aerospace).
- `T` — ramp teams, index `t` (RAMP_ASIA, RAMP_EU, RAMP_AMER).
- `K(o) ⊆ K` — aircraft eligible for order `o`: same route, and if required,
  cold-chain-capable / hazmat-allowed / widebody, as applicable.

## 3. Parameters (from data files, units as given)

- `revenue_o`, `handling_o`, `weight_o` (kg), `volume_o` (cbm)
- `due_o` (hours), `late_pen_o` ($/hour), `lost_pen_o` ($), `prio_o` (weight)
- `cold_o, haz_o, wide_o ∈ {0,1}`, `segment_o ∈ G`
- `route_k`, `wcap_k` (kg), `vcap_k` (cbm), `cost_k` ($/kg), `carbon_k`
  (kg CO2/kg), `cold_cap_k, haz_ok_k, wide_k ∈ {0,1}`, `maxcold_k`,
  `allow_k` (carbon allowance, kg)
- `transit_k` (hours) — used with `due_o` to compute a **fixed** delay hours
  `delay_{o,k} = max(0, transit_k − due_o)`, independent of scenario.
- `prob_s`, `show_{s,o} ∈ {0,1}`
- `wfac_{s,k}`, `vfac_{s,k}` — scenario capacity multipliers
- `floor_g` — minimum expected service rate for segment `g`
- `team_k ∈ T`, `uld_k` (min/cbm), `coldslot_k` (slots/order),
  `hazmin_k` (min/order)
- `uld_cap_{s,t}`, `coldslot_cap_{s,t}`, `hazmin_cap_{s,t}`
- `carbon_pen` ($/kg CO2 over allowance), `tail_pen` ($/unit priority weight)
- `tol` — feasibility tolerance

Net per-order value if order `o` is accepted on aircraft `k` **and** it
materializes in a scenario (matches the evaluator's `net_order_value`
exactly — delay uses aircraft transit time vs. the order's due time, not a
scenario-dependent quantity):

```
value_{o,k} = revenue_o − handling_o − weight_o * cost_k − delay_{o,k} * late_pen_o
```

## 4. Decision variables

- `x_{o,k} ∈ {0,1}` for `k ∈ K(o)` — 1 if order `o` is accepted and assigned
  to aircraft `k`. (No variable is created for ineligible pairs — this is the
  eligibility filter.)
- `carbon_{s,k} ≥ 0` — carbon overage penalty ($) charged against aircraft
  `k` in scenario `s` (linearizes `max(0, ...)`).
- `shortfall_s ≥ 0` — total priority weight of materialized-but-unaccepted
  orders in scenario `s` (bookkeeping expression, defined by a constraint so
  it can be reused in the tail-risk epigraph).
- `T ≥ 0` — worst-case (max over scenarios) priority shortfall (epigraph
  variable for the tail-risk term).

Derived (not stored as variables, expressed inline): accepted flag for order
`o` is `sum_{k in K(o)} x_{o,k}` (≤ 1, i.e. at most one aircraft).

## 5. Objective

Maximize expected profit net of expected carbon penalty and the worst-case
priority-shortfall tail penalty — exactly mirroring the evaluator's
`profit = expected_profit − tail_penalty` where
`expected_profit = Σ_s prob_s * (scenario_profit_s − carbon_penalty_s)`:

```
maximize
  Σ_s prob_s * [
      Σ_o Σ_{k∈K(o)} show_{s,o} * x_{o,k} * value_{o,k}
      − Σ_o show_{s,o} * (1 − Σ_{k∈K(o)} x_{o,k}) * lost_pen_o
      − Σ_k carbon_{s,k}
  ]
  − tail_pen * T
```

The first bracketed sum is revenue-side profit for accepted orders that
materialize; the second is the goodwill penalty for materialized orders that
were never accepted (an order not accepted anywhere still incurs this
penalty when it shows, per the evaluator's `else` branch); the third is the
per-aircraft carbon overage cost in that scenario.

## 6. Constraints

**(a) At most one aircraft per order**
```
Σ_{k∈K(o)} x_{o,k} ≤ 1          ∀ o ∈ O
```

**(b) Eligibility** is enforced structurally: `x_{o,k}` only exists for
`k ∈ K(o)`, i.e. `route_k = route_o`, and (`cold_o=0` or `cold_cap_k=1`),
and (`haz_o=0` or `haz_ok_k=1`), and (`wide_o=0` or `wide_k=1`).

**(c) Scenario realized weight capacity** (only materialized+accepted orders
load the aircraft)
```
Σ_o show_{s,o} * weight_o * x_{o,k} ≤ wcap_k * wfac_{s,k}     ∀ s,k
```

**(d) Scenario realized volume capacity**
```
Σ_o show_{s,o} * volume_o * x_{o,k} ≤ vcap_k * vfac_{s,k}     ∀ s,k
```

**(e) Cold-chain handling limit** (count of materialized cold-chain orders
carried by aircraft `k` in scenario `s`)
```
Σ_{o: cold_o=1} show_{s,o} * x_{o,k} ≤ maxcold_k              ∀ s,k
```

**(f) Ramp team ULD build-minute capacity** (sum over aircraft assigned to
team `t`)
```
Σ_{k: team_k=t} Σ_o show_{s,o} * volume_o * uld_k * x_{o,k} ≤ uld_cap_{s,t}   ∀ s,t
```

**(g) Ramp team cold-chain staging-slot capacity**
```
Σ_{k: team_k=t} Σ_{o: cold_o=1} show_{s,o} * coldslot_k * x_{o,k} ≤ coldslot_cap_{s,t}   ∀ s,t
```

**(h) Ramp team hazmat screening-minute capacity**
```
Σ_{k: team_k=t} Σ_{o: haz_o=1} show_{s,o} * hazmin_k * x_{o,k} ≤ hazmin_cap_{s,t}   ∀ s,t
```

**(i) Carbon overage linearization** (`carbon_{s,k}` = value of
`max(0, loaded_weight*carbon_k − allow_k) * carbon_pen`; only the `≥` side is
needed because the objective maximizes and the term is subtracted, so the
solver will drive `carbon_{s,k}` down to its lower bound of `max(0, ...)`)
```
carbon_{s,k} ≥ carbon_pen * ( carbon_k * Σ_o show_{s,o}*weight_o*x_{o,k} − allow_k )   ∀ s,k
carbon_{s,k} ≥ 0
```

**(j) Segment expected service-rate floor** (evaluator compares expected
*materialized and accepted* weight against expected *materialized* weight;
denominator is a fixed number computable from data, not a decision
variable, so this is linear)
```
Σ_o Σ_{k∈K(o)} [segment_o=g] * (Σ_s prob_s*show_{s,o}) * weight_o * x_{o,k}
  ≥ floor_g * Σ_o [segment_o=g] * (Σ_s prob_s*show_{s,o}) * weight_o     ∀ g : floor_g>0, denom_g>tol
```
(Skip segments with `floor_g = 0` or with zero expected materialized weight,
matching the evaluator's own skip condition.)

**(k) Priority shortfall bookkeeping per scenario**
```
shortfall_s = Σ_o show_{s,o} * prio_o * (1 − Σ_{k∈K(o)} x_{o,k})     ∀ s
```

**(l) Tail-risk epigraph**
```
T ≥ shortfall_s      ∀ s
T ≥ 0
```

## 7. Notes on fidelity to the evaluator

- `delay_{o,k}` uses aircraft `transit_hours` vs. order `due_hours` — this is
  **not** scenario-dependent, matching `net_order_value` in
  `evaluate_solution.py`, which takes only `order` and `aircraft`.
- The lost-booking penalty is charged whenever a materialized order has **no
  assignment at all**, regardless of the reason (ineligibility or
  deliberate rejection) — captured correctly since `Σ_{k∈K(o)} x_{o,k}` is 0
  for both cases.
- Carbon penalty depends only on realized weight in the scenario, computed
  per-aircraft, then summed and subtracted from that scenario's profit
  before multiplying by probability — matches evaluator's
  `scenario_profit -= carbon_penalty; expected_profit += probability *
  scenario_profit`.
- The tail penalty uses the single worst-scenario shortfall (`max` over
  scenarios), applied once (not probability-weighted) — matches
  `worst_priority_shortfall = max(...)`, `tail_penalty = priority_tail_penalty
  * worst_priority_shortfall`.
- This is a two-stage-flavored but effectively single-stage MIP: all
  randomness is resolved by parameters (`show_{s,o}`, `wfac_{s,k}`,
  `vfac_{s,k}`), and the only decision variables are first-stage
  acceptance/assignment `x_{o,k}` plus deterministic linear recourse
  expressions (`carbon_{s,k}`, `shortfall_s`, `T`) — no per-scenario
  recourse decision exists in this problem (assignment is fixed before
  scenario realization), so a plain deterministic-equivalent MIP is exact,
  not an approximation.

## 8. Formulation class and solve strategy

This is a **generalized assignment / multi-knapsack model with scenario-wise
side constraints** (order→aircraft assignment, at-most-one per order,
per-scenario multi-dimensional knapsack capacity on each aircraft and ramp
team) plus one epigraph variable for a minimax term and per-scenario linear
carbon terms. Size: 42 orders × ≤7 eligible aircraft each ≈ ~130–200 binary
variables, 12 scenarios × 7 aircraft × (weight+volume+cold) + 12×3 ramp
constraints ≈ ~350 linear constraints. This is small enough for direct SCIP
solve to provable near-optimality within the 5-minute cap — no
decomposition or heuristic warm-start is required, but we:

- Only create `x_{o,k}` for eligible `(o,k)` pairs (eligibility filter as
  presolve, not big-M).
- Precompute `delay_{o,k}` and `value_{o,k}` once.
- Use tight per-scenario/per-aircraft big-M-free capacity rows (natural
  knapsack coefficients, no artificial big-M).
- Use `carbon_{s,k} ≥ ...` (single-sided, tight because objective pressure
  drives it to equality) instead of an indicator/big-M formulation.
- Solve directly with SCIP at relative gap `0.0005`, time limit
  `min(300, ORCLAW_SOLVE_TIME_LIMIT_SECONDS)`.
