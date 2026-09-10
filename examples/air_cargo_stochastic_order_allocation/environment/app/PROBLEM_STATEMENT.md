# Air Cargo Stochastic Order Allocation

An airline cargo desk is deciding which booking requests to commit to tonight's passenger-belly cargo capacity. Customer orders may or may not materialize, and actual payload capacity varies by scenario because passenger bags, weather, and operational restrictions change the usable weight and volume on each aircraft.

The plan assigns accepted booking requests to aircraft. If an accepted order appears in a scenario, it earns freight revenue and consumes aircraft weight and volume. Orders that appear but were not accepted create customer goodwill penalties. Assignments also incur aircraft-specific transport cost, possible lateness cost, and carbon-overage penalties when realized cargo pushes an aircraft above its carbon allowance. Priority account shortfalls are penalized by the worst scenario shortfall so the plan is not tuned only for average demand.

# Agent Brief

Plan which uncertain air-cargo booking requests to commit to passenger-belly aircraft capacity. Read `/app/data`, write a complete mathematical model, implement a PySCIPOpt solver, and submit `model.md`, `solve.py`, `solve_log.md`, and `solution.csv` under `/app/submissions`.

## Data

- `aircraft.csv`: aircraft route, transit time, weight and volume capacity, cost and carbon factors, cold-chain capability, hazmat permission, widebody flag, cold-chain handling limit, and carbon allowance.
- `orders.csv`: booking request route, customer segment, weight, volume, revenue, handling cost, due time, lateness penalty, lost-booking penalty, cold-chain flag, hazmat flag, widebody requirement, and priority weight.
- `scenarios.csv`: scenario probability and operating condition label.
- `scenario_order_show.csv`: whether each booking request materializes under each scenario.
- `scenario_aircraft_capacity.csv`: scenario-specific usable weight and volume multipliers for each aircraft.
- `segment_rules.csv`: expected service-rate floors for customer segments.
- `aircraft_ramp_team.csv`: ground team assignment and per-order ramp workload coefficients by aircraft.
- `scenario_ramp_team_capacity.csv`: scenario-specific ramp-team limits for ULD build minutes, cold-chain staging slots, and hazmat screening minutes.
- `config.json`: carbon penalty, tail-risk penalty, and numerical tolerances.

## Planning Rules

Each accepted order can be assigned to at most one aircraft. An aircraft can carry only orders for its route. Cold-chain orders require a cold-chain-capable aircraft and count against the aircraft's cold-chain handling limit in every scenario where they appear. Hazmat orders require hazmat permission. Widebody-required orders can only be assigned to widebody aircraft.

For every scenario, realized cargo assigned to each aircraft must fit the scenario-adjusted weight and volume capacity. The realized orders also consume ramp-team ULD build time, cold-chain staging slots, and hazmat screening minutes according to the aircraft team table; each scenario has its own ramp resource availability. Customer segment service floors are measured over expected materialized demand: the accepted materialized weight for that segment must meet the stated share of total materialized weight for that segment.

## Submission Schema

Write `/app/submissions/solution.csv` with columns:

`row_type,order_id,aircraft_id,value`

Use `assign` rows only. Put an order id and aircraft id in each accepted assignment row, with value `1`. Orders not listed are treated as not accepted. Zero-valued rows may be omitted.
