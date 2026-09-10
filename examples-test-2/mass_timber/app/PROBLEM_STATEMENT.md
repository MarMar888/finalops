# Mass Timber Panel Cutting Plan
You are helping a modular-construction shop choose cutting patterns for mass-timber panels. Read `/app/PROBLEM_STATEMENT.md` and every file under `/app/data/`, build an optimization model, and submit all required files under `/app/submissions`.

A modular-construction shop has a set of engineered mass-timber components due for the next production wave. The shop has grade-specific panel lots and a library of approved cutting patterns. At this procurement-planning stage, pattern use is measured in panel-equivalent batches. Each batch consumes one panel-equivalent from one lot and produces pieces for one or two components.

The shop wants to meet every component demand at minimum total production cost. Cost includes panel cost, cutting labor, trim disposal, pattern adjustment, and holding cost for extra pieces produced above demand. Panel availability by lot cannot be exceeded.

## Data

- `config.json`: tolerance and trim disposal cost.
- `components.csv`: component grade, dimensions, required pieces, and holding cost for extra pieces.
- `stock_lots.csv`: available panel lots, grade, area, panel cost, and labor rate.
- `cut_patterns.csv`: approved patterns, the lot each pattern uses, produced component pieces, trim area, cut time, and pattern-specific cost adjustment.

## Rules

Use only listed cutting patterns. Each panel-equivalent assigned to a pattern consumes one panel-equivalent from that pattern's lot. The total panel-equivalents drawn from any lot cannot exceed its available panels. Every component's demand must be met or exceeded. Extra pieces are allowed but incur the component's holding cost.

## Submission Schema

Write `/app/submissions/solution.csv` with columns:

`pattern_id,panels_used`

Include only patterns used with a positive number of panel-equivalent batches. Decimal values are allowed.
