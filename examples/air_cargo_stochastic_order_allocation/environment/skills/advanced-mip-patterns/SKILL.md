---
name: advanced-mip-patterns
description: Use when a task involves fixed charges, logical implications, min/max choices, sequencing, no-overlap, piecewise costs, routing-state logic, or other advanced MIP modeling patterns.
metadata:
  short-description: Advanced MIP formulation patterns
---

# Advanced MIP Patterns

## Use when

- The formulation needs logical implications, fixed charges, activation decisions, ordering, no-overlap, disjunctions, min/max, absolute values, tiers, route state, or resource calendars.
- A simple LP/MIP is producing unrealistic behavior because decisions are not linked tightly enough.
- The model is slow or infeasible and the likely cause is weak big-M logic, excessive pairwise variables, or missing state transitions.

## Do not use when

- A continuous LP is sufficient and adding binaries would not represent a real decision.
- The task is better handled by a specialized CP-SAT, constraint programming, nonlinear, or simulation method and the user did not require MIP.
- The user only needs a high-level explanation; do not introduce advanced constructs unless they clarify the actual model.

## General boundary rules

- Add binaries only for real yes/no choices, disjunctions, or nonconvex structure.
- Prefer the tightest formulation that matches the business rule; avoid decorative binaries.
- Use solver-native constructs when they improve clarity and are supported by the target environment.
- If a construct makes the model much slower, compare it with a simpler valid alternative before keeping it.

## Fixed charge and activation

- Use a binary `y` for whether an activity/resource is active.
- Link activity with a tight bound: `x <= U * y`.
- Add lower activation only when the business requires minimum use: `x >= L * y`.
- Charge fixed cost once through `fixed_cost * y`, not per unit.
- Do not force `y = 1` whenever `x = 0` unless the activity is mandatory.
- If there are startup/shutdown costs over time, separate active state from transition state.

## Logical rules

- Prefer solver-native indicator constraints for simple if-then rules when they keep the model clearer.
- If using big-M, derive M from data bounds and keep one M per rule family when possible.
- For either-or choices, use binaries whose sum is exactly one or at most one, matching the business rule.
- Distinguish implication (`A -> B`) from equivalence (`A <-> B`); the reverse direction often needs a separate constraint.
- For conditional capacity, link both activity and resource use to the condition.

## Min, max, absolute value

- For `z = max(a, b)`, add `z >= a`, `z >= b`, and objective pressure if minimizing z. Use binaries only when equality is needed without objective pressure.
- For absolute deviation `d = |x - target|`, add `d >= x - target` and `d >= target - x`.
- For service-level penalties, separate hard feasibility from soft penalty variables.
- For `min`, either transform with signs or add binaries when equality is not enforced by the objective.
- For ratio constraints, cross-multiply only when denominators are constant or safely bounded away from zero.

## Sequencing and no-overlap

- For jobs sharing a resource, use order binary `before[i,j]`.
- Typical pattern:
  - `start[j] >= end[i] - M * (1 - before[i,j])`
  - `start[i] >= end[j] - M * before[i,j]`
- Compute M from the scheduling horizon, not from an arbitrary large number.
- Include setup, cleanup, travel, rest, or turnover time in the correct side of the ordering constraint.
- Create pairwise order variables only for pairs that can share a resource or conflict.
- If time is discrete and the horizon is small, a time-indexed model may be cleaner than pairwise disjunctions.

## Piecewise and tiers

- Use solver-native piecewise-linear features for convex piecewise costs when suitable.
- For nonconvex tiers, use explicit segment variables and segment activation binaries.
- Ensure tier quantities sum to the original activity and each tier has its own upper bound.
- Distinguish incremental tiers from all-units tiers; their formulations and costs differ.
- Check whether discount tiers create nonconvex incentives that require binary selection.

## State and inventory logic

- State variables need initial conditions, transition equations, and terminal requirements if the business specifies them.
- Route or schedule state should be advanced in event order, not checked only row by row.
- Recovery, restock, cleaning, cooldown, maintenance, and rest rules often require cumulative state or last-event logic.
- If state can reset, model the reset trigger and its resource/time cost.

## Debugging advanced models

- First solve a relaxed or smaller instance and inspect whether the intended binaries activate.
- Add named constraints so IIS output points to business rules.
- If the reference solution is infeasible, replay the relevant state transitions manually before changing the evaluator.
- If the LP relaxation is very weak, inspect big-M values, missing lower/upper links, and symmetry.
- If the model is unexpectedly infeasible, test each advanced rule family on a tiny instance with a known feasible solution.
