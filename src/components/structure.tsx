"use client";

import { useState } from "react";
import { fmt, fmtBounds, type Bundle } from "@/lib/bundle";
import { Card } from "./ui";

type NodeState = "variable" | "objective" | "binding" | "violated" | "normal";

interface GraphNode {
  id: string;
  reqId: string | null;
  title: string;
  sub: string;
  state: NodeState;
  x: number;
  y: number;
}

interface GraphEdge {
  key: string;
  from: GraphNode;
  to: GraphNode;
  coef: number;
  toObjective: boolean;
}

const NODE_W = 184;
const NODE_H = 42;
const GAP = 14;
const PAD = 16;
const WIDTH = 680;

const NODE_CLASSES: Record<NodeState, string> = {
  variable: "fill-sky-50 stroke-sky-300 dark:fill-sky-950 dark:stroke-sky-700",
  objective: "fill-indigo-50 stroke-indigo-400 dark:fill-indigo-950 dark:stroke-indigo-500",
  binding: "fill-amber-50 stroke-amber-500 dark:fill-amber-950 dark:stroke-amber-500",
  violated: "fill-red-50 stroke-red-500 dark:fill-red-950 dark:stroke-red-500",
  normal: "fill-white stroke-zinc-300 dark:fill-zinc-900 dark:stroke-zinc-600",
};

function truncate(text: string, max: number): string {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function buildGraph(bundle: Bundle) {
  type Draft = Omit<GraphNode, "x" | "y">;

  const left: Draft[] = bundle.variables.map((v) => ({
    id: `var:${v.name}`,
    reqId: v.requirement_id,
    title: v.name,
    sub: v.value === null ? `${v.category} ${fmtBounds(v)}` : `= ${fmt(v.value)}${v.units ? ` ${v.units}` : ""}`,
    state: "variable",
  }));

  const right: Draft[] = [];
  const hasObjective = Object.keys(bundle.objective.terms).length > 0;
  if (hasObjective) {
    const value = bundle.summary.objective;
    right.push({
      id: "objective",
      reqId: bundle.objective.requirement_id,
      title: bundle.objective.requirement_id ?? "objective",
      sub: `${bundle.summary.sense === "max" ? "maximize" : "minimize"}${value === null ? "" : ` · ${fmt(value)}`}`,
      state: "objective",
    });
  }
  for (const c of bundle.constraints) {
    const inConflict = c.in_conflict === true;
    const note = c.violation !== null ? ` · relax ${fmt(c.violation)}` : inConflict ? " · in conflict" : c.binding ? " · binding" : "";
    right.push({
      id: `con:${c.name}`,
      reqId: c.requirement_id,
      title: c.requirement_id ?? c.name,
      sub: `${c.sense} ${fmt(c.rhs)}${note}`,
      state: c.violation !== null || inConflict ? "violated" : c.binding ? "binding" : "normal",
    });
  }

  const columnHeight = (n: number) => (n === 0 ? 0 : n * NODE_H + (n - 1) * GAP);
  const inner = Math.max(columnHeight(left.length), columnHeight(right.length));
  const place = (drafts: Draft[], x: number): GraphNode[] => {
    const top = PAD + (inner - columnHeight(drafts.length)) / 2;
    return drafts.map((d, i) => ({ ...d, x, y: top + i * (NODE_H + GAP) }));
  };
  const leftNodes = place(left, PAD);
  const rightNodes = place(right, WIDTH - PAD - NODE_W);

  const byVariable = new Map(leftNodes.map((n) => [n.id, n]));
  const edges: GraphEdge[] = [];
  const connect = (row: GraphNode, terms: Record<string, number>, toObjective: boolean) => {
    for (const [name, coef] of Object.entries(terms)) {
      const from = byVariable.get(`var:${name}`);
      if (from && coef !== 0) edges.push({ key: `${from.id}->${row.id}`, from, to: row, coef, toObjective });
    }
  };
  for (const row of rightNodes) {
    if (row.id === "objective") connect(row, bundle.objective.terms, true);
    else {
      const c = bundle.constraints.find((k) => `con:${k.name}` === row.id);
      if (c) connect(row, c.terms, false);
    }
  }

  return { nodes: [...leftNodes, ...rightNodes], edges, height: inner + PAD * 2 };
}

function Legend() {
  const items: [string, string][] = [
    ["Variable", "bg-sky-200 dark:bg-sky-900"],
    ["Objective", "bg-indigo-200 dark:bg-indigo-900"],
    ["Binding constraint", "bg-amber-200 dark:bg-amber-900"],
    ["In the conflict", "bg-red-200 dark:bg-red-900"],
    ["Constraint with room", "bg-zinc-200 dark:bg-zinc-700"],
  ];
  return (
    <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500 dark:text-zinc-400">
      {items.map(([label, swatch]) => (
        <li key={label} className="flex items-center gap-1.5">
          <span className={`inline-block h-2.5 w-2.5 rounded-sm ${swatch}`} />
          {label}
        </li>
      ))}
      <li>Edge labels are coefficients.</li>
    </ul>
  );
}

function GraphView({
  bundle,
  selectedId,
  onSelect,
}: {
  bundle: Bundle;
  selectedId: string | null;
  onSelect: (requirementId: string) => void;
}) {
  const [hovered, setHovered] = useState<string | null>(null);
  const { nodes, edges, height } = buildGraph(bundle);

  const isActive = (n: GraphNode) => hovered === n.id || (selectedId !== null && n.reqId === selectedId);
  const anyActive = nodes.some(isActive);
  const labelAll = edges.length <= 14;

  return (
    <div>
      <svg viewBox={`0 0 ${WIDTH} ${height}`} className="w-full" role="group" aria-label="Graph of variables and constraints">
        {edges.map((e) => {
          const active = isActive(e.from) || isActive(e.to);
          const x1 = e.from.x + NODE_W;
          const y1 = e.from.y + NODE_H / 2;
          const x2 = e.to.x;
          const y2 = e.to.y + NODE_H / 2;
          const stroke = active
            ? "stroke-blue-600 dark:stroke-blue-400"
            : e.toObjective
              ? "stroke-indigo-400 dark:stroke-indigo-500"
              : "stroke-zinc-400 dark:stroke-zinc-500";
          return (
            <g key={e.key} opacity={anyActive && !active ? 0.15 : 0.9}>
              <line x1={x1} y1={y1} x2={x2} y2={y2} className={stroke} strokeWidth={active ? 2.5 : 1.25} strokeDasharray={e.toObjective ? "5 3" : undefined} />
              {(labelAll || active) && (
                <text
                  x={x1 + (x2 - x1) * 0.72}
                  y={y1 + (y2 - y1) * 0.72 - 3}
                  textAnchor="middle"
                  className="fill-zinc-800 stroke-white font-mono text-[11px] dark:fill-zinc-100 dark:stroke-zinc-950"
                  strokeWidth={3}
                  paintOrder="stroke"
                >
                  {fmt(e.coef)}
                </text>
              )}
            </g>
          );
        })}

        {nodes.map((n) => {
          const active = isActive(n);
          const selectable = n.reqId !== null;
          return (
            <g
              key={n.id}
              role={selectable ? "button" : undefined}
              tabIndex={selectable ? 0 : undefined}
              aria-label={`${n.title}: ${n.sub}`}
              opacity={anyActive && !active ? 0.55 : 1}
              className={selectable ? "cursor-pointer" : undefined}
              onMouseEnter={() => setHovered(n.id)}
              onMouseLeave={() => setHovered(null)}
              onClick={() => n.reqId && onSelect(n.reqId)}
              onKeyDown={(event) => {
                if (n.reqId && (event.key === "Enter" || event.key === " ")) {
                  event.preventDefault();
                  onSelect(n.reqId);
                }
              }}
            >
              <rect x={n.x} y={n.y} width={NODE_W} height={NODE_H} rx={n.state === "objective" ? 21 : 8} strokeWidth={1.5} className={NODE_CLASSES[n.state]} />
              {active && (
                <rect x={n.x} y={n.y} width={NODE_W} height={NODE_H} rx={n.state === "objective" ? 21 : 8} fill="none" strokeWidth={3} className="stroke-blue-500" />
              )}
              <text x={n.x + 12} y={n.y + 17} className="fill-zinc-900 font-mono text-[12px] font-semibold dark:fill-zinc-100">
                {truncate(n.title, 24)}
              </text>
              <text x={n.x + 12} y={n.y + 32} className="fill-zinc-500 font-mono text-[10px] dark:fill-zinc-400">
                {truncate(n.sub, 30)}
              </text>
            </g>
          );
        })}
      </svg>
      <Legend />
    </div>
  );
}

function MatrixView({
  bundle,
  selectedId,
  onSelect,
}: {
  bundle: Bundle;
  selectedId: string | null;
  onSelect: (requirementId: string) => void;
}) {
  const rows = [
    ...(Object.keys(bundle.objective.terms).length > 0
      ? [
          {
            key: "objective",
            label: bundle.objective.requirement_id ?? "objective",
            reqId: bundle.objective.requirement_id,
            terms: bundle.objective.terms,
            rhs: bundle.summary.sense === "max" ? "maximize" : "minimize",
          },
        ]
      : []),
    ...bundle.constraints.map((c) => ({
      key: c.name,
      label: c.requirement_id ?? c.name,
      reqId: c.requirement_id,
      terms: c.terms,
      rhs: `${c.sense} ${fmt(c.rhs)}`,
    })),
  ];

  return (
    <div className="overflow-x-auto">
      <table className="border-collapse text-xs">
        <thead>
          <tr>
            <th className="p-1.5 text-left font-medium text-zinc-500">Row</th>
            {bundle.variables.map((v) => {
              const hot = v.requirement_id !== null && v.requirement_id === selectedId;
              return (
                <th key={v.name} className={`p-1.5 font-mono font-semibold ${hot ? "bg-blue-50 dark:bg-blue-950" : ""}`}>
                  {v.name}
                </th>
              );
            })}
            <th className="p-1.5 text-left font-medium text-zinc-500">Limit</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const hotRow = row.reqId !== null && row.reqId === selectedId;
            return (
              <tr key={row.key} className={`border-t border-zinc-100 dark:border-zinc-900 ${hotRow ? "bg-blue-50 dark:bg-blue-950" : ""}`}>
                <td className="p-1.5 font-mono">
                  {row.reqId ? (
                    <button type="button" className="underline-offset-2 hover:underline" onClick={() => onSelect(row.reqId as string)}>
                      {row.label}
                    </button>
                  ) : (
                    row.label
                  )}
                </td>
                {bundle.variables.map((v) => (
                  <td key={v.name} className="p-1.5 text-center font-mono">
                    {row.terms[v.name] !== undefined ? fmt(row.terms[v.name]) : ""}
                  </td>
                ))}
                <td className="p-1.5 font-mono text-zinc-500">{row.rhs}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function Structure({
  bundle,
  selectedId,
  onSelect,
}: {
  bundle: Bundle;
  selectedId: string | null;
  onSelect: (requirementId: string) => void;
}) {
  const [view, setView] = useState<"graph" | "matrix">("graph");

  const toggle = (
    <div role="group" aria-label="Structure view" className="inline-flex overflow-hidden rounded-md border border-zinc-200 text-xs dark:border-zinc-700">
      {(["graph", "matrix"] as const).map((v) => (
        <button
          key={v}
          type="button"
          aria-pressed={view === v}
          onClick={() => setView(v)}
          className={`px-2.5 py-1 capitalize ${view === v ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900" : "hover:bg-zinc-100 dark:hover:bg-zinc-800"}`}
        >
          {v}
        </button>
      ))}
    </div>
  );

  const empty = bundle.variables.length === 0;

  return (
    <Card title="Structure" right={toggle}>
      {empty ? (
        <p className="text-zinc-500 dark:text-zinc-400">No variables appear in this model.</p>
      ) : view === "graph" ? (
        <GraphView bundle={bundle} selectedId={selectedId} onSelect={onSelect} />
      ) : (
        <MatrixView bundle={bundle} selectedId={selectedId} onSelect={onSelect} />
      )}
    </Card>
  );
}
