---
name: optimization-modeling-core
description: Use for natural-language-to-optimization tasks that require translating a business problem into a complete mathematical model before writing solver code.
metadata:
  short-description: Turn business text into a full optimization model
---

# Optimization Modeling Core

## Use when

- The user gives a word problem, business process, paper scenario, or benchmark prompt and expects a formal optimization model.
- Solver code exists but the issue appears to be a missing or incorrect formulation.
- The task asks for a complete model, not only a heuristic, simulation, or data summary.

## Do not use when

- The task is purely about software plumbing, visualization, data cleaning, or report writing.
- The problem is already fully formulated and the user only asks for code translation into a specific solver; use the solver-specific skill as the primary guide.
- The request is exploratory and the user explicitly wants brainstorming without implementation.

## Model-first workflow

1. Restate the business decision in plain language.
2. Identify sets, indices, units, and time granularity.
3. Extract parameters from data files and confirm units.
4. Define decision variables with domains and business meaning.
5. Write the objective with every cost, reward, penalty, and service term.
6. Write constraints grouped by operational rule.
7. Check edge cases: missing eligibility, impossible demand, fixed commitments, and terminal-state requirements.
8. Only then implement code.

## Ambiguity handling

- If the brief is ambiguous but data and examples imply a convention, state the assumption and continue.
- If ambiguity changes feasibility, objective direction, or deliverable schema, ask before coding or implement the least risky interpretation with a clear note.
- If units conflict across files, normalize units explicitly before modeling.
- If a hard requirement conflicts with data, diagnose the conflict before adding slack variables.

## Formulation checklist

- Every row in an input table should either become a parameter, an eligibility rule, or be explicitly irrelevant.
- Every decision variable should appear in at least one binding constraint and usually in the objective.
- Demand balance should use the correct equality or inequality direction; do not weaken equality to `>=` unless surplus is genuinely allowed.
- Capacity constraints should include activation/open/setup binaries when the business says inactive resources cannot produce, ship, or serve.
- Shortage, backlog, overtime, outsourcing, and postponement variables need explicit cost and bounds.
- Multi-period models need state transition equations and initial/terminal states.
- If the user asks for explanation, describe the modeling logic in business terms after solving.

## Constraint boundary rules

- Hard constraints represent physical impossibility, policy mandates, legal requirements, or explicit benchmark feasibility rules.
- Soft constraints need penalty variables or objective terms; do not silently turn hard constraints into penalties.
- Service levels should specify numerator, denominator, eligible population, and time window.
- Fairness constraints should define the comparison group and whether unavailable resources count.
- Logical implications need both directions only when the business rule says equivalence, not merely implication.

## Objective boundary rules

- Confirm whether the problem minimizes cost, maximizes profit, maximizes service, or uses lexicographic priorities.
- Do not mix penalties with primary economics unless their scale is intentional.
- Include fixed costs only once per activated entity.
- Include revenue only for fulfilled demand or accepted jobs, not for unmet or canceled work.
- Keep reporting metrics separate from optimized objective terms unless the prompt explicitly optimizes them.

## Implementation expectations

- Use structured parsing for CSV/JSON instead of manual string manipulation.
- Keep solver code, solution export, and validation code clearly separated.
- For benchmark or task environments, read the provided brief before coding and follow the expected output schema exactly.
- When comparing two answers, diagnose concrete formulation differences and objective consequences, not only feasibility.
- Write exported solutions at the precision expected by the checker; avoid unnecessary rounding.
- Preserve the input schema and output schema unless the user asks to redesign the benchmark.

## Verification boundary

- Verify feasibility independently from solver status when an evaluator or checker exists.
- Recompute objective from exported artifacts, not only from in-memory solver expressions.
- For benchmark tasks, create at least one negative check for each newly added rule when practical.
- For paper or real-world tasks, separate what is directly supported by the source from synthetic or assumed data.

## Red flags

- Objective terms that are counted twice or charged at the wrong marginal rate.
- Binary variables not linked tightly enough to continuous activity.
- Time periods shifted by one index.
- Average or fairness constraints that ignore the denominator or eligibility set.
- Public prompt files that reveal solver-ready variables or formulas when the benchmark is meant to test modeling translation.
- A feasible solution that exploits missing eligibility, free disposal, negative cycles, or unbounded production.
- A model that reports optimality after a time limit, infeasible status, or missing incumbent.
