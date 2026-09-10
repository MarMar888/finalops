# Solve Log — Electric Medical Waste Location-Routing

- Method: greedy nearest-feasible-insertion construction heuristic (no exact MIP;
  see model.md for rationale — 44-clinic multi-vehicle VRPTW+energy is not expected
  to solve to proven optimality in a reasonable budget with an exact formulation).
- Vehicles used: 7 of 8
- Clinics assigned: 44 of 44
- Unassigned clinics: none
- Facilities opened: ['F1', 'F2', 'F3', 'F5']

## Cost breakdown (self-computed estimate)
- Vehicle fixed cost: 1587.60
- Facility open cost: 2511.00
- Travel cost: 2815.43
- Treatment + charging cost: 3243.22
- Risk cost: 6521.08
- TOTAL estimated cost: 16678.33

## Independent feasibility self-check
No feasibility issues found by the independent re-check (see check_solution() in this file).