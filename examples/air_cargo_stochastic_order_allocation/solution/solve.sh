#!/usr/bin/env bash
set -euo pipefail

mkdir -p /app/submissions

suffix=".csv"
if [[ -f /app/submissions/solution_template.json ]]; then
  suffix=".json"
fi
output="/app/submissions/solution${suffix}"

if [[ ! -f /solution/solve_reference.py ]]; then
  echo "No reference solver is bundled for this task." >&2
  exit 1
fi

args=(python /solution/solve_reference.py --env-dir /app)
if grep -q -- "--time-limit" /solution/solve_reference.py; then
  args+=(--time-limit "${ORCLAW_SOLVE_TIME_LIMIT_SECONDS:-300}")
fi
if grep -q -- "--mip-gap" /solution/solve_reference.py; then
  args+=(--mip-gap "${ORCLAW_SCIP_GAP:-0.0005}")
fi
if grep -q -- "--quiet" /solution/solve_reference.py; then
  args+=(--quiet)
fi
if grep -q -- "--output" /solution/solve_reference.py; then
  args+=(--output "${output}")
elif grep -q -- "--write" /solution/solve_reference.py; then
  args+=(--write "${output}")
elif grep -q -- "--solution" /solution/solve_reference.py; then
  args+=(--solution "${output}")
fi

"${args[@]}"
