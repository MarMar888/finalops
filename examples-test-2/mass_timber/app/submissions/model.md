# Mass Timber Panel Cutting Plan — Model

## Sets
- `C`: components (from `components.csv`), indexed by `component_id`.
- `L`: stock lots (from `stock_lots.csv`), indexed by `lot_id`.
- `P`: approved cutting patterns (from `cut_patterns.csv`), indexed by `pattern_id`.

## Parameters (per pattern `p`)
- `lot(p)`: the lot `p` draws panel-equivalents from.
- `primary_comp(p)`, `primary_pieces(p)`: primary component and pieces produced per panel-equivalent.
- `secondary_comp(p)`, `secondary_pieces(p)`: optional secondary component/pieces (blank if none).
- `trim_area(p)`: trim area (m²) produced per panel-equivalent.
- `cut_time(p)`: cut time (minutes) per panel-equivalent.
- `cost_adj(p)`: pattern-specific cost adjustment ($) per panel-equivalent.

Per lot `l`: `available_panels(l)`, `panel_cost(l)`, `labor_cost_per_min(l)`.
Per component `c`: `demand_pieces(c)`, `overage_holding_cost(c)`.
Global: `trim_disposal_cost_per_m2` (from `config.json`).

## Decision variables
- `x[p] >= 0` (continuous): panel-equivalent batches assigned to pattern `p`. Decimal values allowed per the submission schema.
- `overage[c] >= 0` (continuous, derived): pieces of component `c` produced above demand.

## Objective (minimize total cost)
For each pattern `p`, one panel-equivalent batch costs:

`unit_cost(p) = panel_cost(lot(p)) + labor_cost_per_min(lot(p)) * cut_time(p) + trim_disposal_cost_per_m2 * trim_area(p) + cost_adj(p)`

Total cost:

`minimize  sum_p unit_cost(p) * x[p]  +  sum_c overage_holding_cost(c) * overage[c]`

## Constraints
1. **Lot capacity**: for each lot `l`,
   `sum_{p : lot(p) = l} x[p] <= available_panels(l)`

2. **Component demand + overage linkage**: for each component `c`, let `produced(c) = sum_{p : primary_comp(p)=c} primary_pieces(p) * x[p] + sum_{p : secondary_comp(p)=c} secondary_pieces(p) * x[p]`.
   `produced(c) - overage[c] = demand_pieces(c)`  (equivalently `produced(c) >= demand_pieces(c)` with `overage[c] = produced(c) - demand_pieces(c)`, since overage is charged and never beneficial to inflate — the solver drives it to the minimum consistent with meeting demand).

3. Nonnegativity: `x[p] >= 0` for all `p`, `overage[c] >= 0` for all `c`.

## Notes
- This is a pure LP (no integrality on `x[p]` — panel-equivalents are explicitly fractional/decimal per the problem statement), so no MIP gap applies; SCIP solves it to LP optimality directly.
- No pattern uses a lot/grade mismatch by construction (each pattern already pins one lot, and each lot has one grade), so no explicit grade-matching constraint is needed beyond using `lot(p)` as given.
- `overage[c]` is a free modeling variable (not in the output schema) used only to linearize the holding-cost term; only `pattern_id,panels_used` for patterns with `x[p] > 0` go into `solution.csv`.
