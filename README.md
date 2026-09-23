# finalops

[![CI](https://github.com/MarMar888/finalops/actions/workflows/ci.yml/badge.svg)](https://github.com/MarMar888/finalops/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](finalops/pyproject.toml)

An AI-native operations-research tool: a Python package that makes an LLM agent write down every requirement from a brief before it writes a model, and a debugger for looking at the linear program afterward. It grew out of reading [ORAgentBench](https://arxiv.org/abs/2606.19787), which found that LLM agents fail at OR modeling mostly by dropping a requirement or misjudging a solution's quality, not by getting the solver syntax wrong.

This repo has two parts:

- **`finalops/`** — the Python package. A requirement ledger, typed constraint classes built on PuLP, infeasibility and sensitivity analysis, and a `run()` that won't let a solve pass without checking it. Start with [`finalops/README.md`](finalops/README.md).
- **This Next.js app** — the LP debugger. `finalops.build_debug_bundle(...)` writes a model's variables, constraints, shadow prices, and (if it's infeasible) its conflict set to one JSON file; this app renders that file as a graph you can click through, instead of a solver log.

## Running the debugger

```bash
pnpm install
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000). It loads with a few sample bundles under `public/samples/` (one healthy, one infeasible, one unbounded, one MIP) — pick one from the dropdown, or load your own with "Load bundle…". Regenerate the samples with:

```bash
cd finalops
python examples/generate_debug_samples.py
```

`pnpm lint` and `npx tsc --noEmit` check the frontend; `cd finalops && pytest` checks the package.

## License

[MIT](LICENSE)
