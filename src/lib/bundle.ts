// Shape of the JSON written by finalops' build_debug_bundle() (python).
// Keep in sync with finalops/src/finalops/debug_bundle.py.

export const SUPPORTED_SCHEMA_VERSION = 1;

export type Kind = "decision_variable" | "objective" | "constraint" | "data";

export const KIND_ORDER: Kind[] = ["decision_variable", "objective", "constraint", "data"];

export const KIND_LABEL: Record<Kind, string> = {
  decision_variable: "Decision variables",
  objective: "Objective",
  constraint: "Constraints",
  data: "Data",
};

export interface LinkedObject {
  name: string;
  expression: string;
}

export interface Requirement {
  id: string;
  kind: Kind;
  description: string;
  source: string;
  units: string | null;
  linked: LinkedObject[];
}

export interface Variable {
  name: string;
  value: number | null;
  lower: number | null;
  upper: number | null;
  category: string;
  requirement_id: string | null;
  units: string | null;
}

export interface WhatIf {
  status: string;
  objective: number | null;
}

export interface Constraint {
  name: string;
  requirement_id: string | null;
  expression: string;
  sense: "<=" | ">=" | "==";
  rhs: number;
  terms: Record<string, number>;
  slack: number | null;
  binding: boolean | null;
  shadow_price: number | null;
  shadow_basis: string | null;
  violation: number | null;
  in_conflict?: boolean | null;
  what_if_dropped: WhatIf | null;
}

export interface Summary {
  status: string;
  termination: string | null;
  sense: "min" | "max";
  objective: number | null;
  bound: number | null;
  proven_optimal: boolean | null;
  quality_gap: number | null;
  feasible: boolean;
  problems: string[];
  unlinked_requirements: string[];
}

export interface Violation {
  constraint_name: string;
  requirement_id: string | null;
  description: string | null;
  magnitude: number;
}

export interface ConflictMember {
  kind: "constraint" | "bound";
  name: string;
  expression: string;
  requirement_id: string | null;
  description: string | null;
  bound: "lower" | "upper" | null;
}

/** A set of rules that can't all hold; when `minimal`, dropping any one member frees the rest. */
export interface Conflict {
  members: ConflictMember[];
  minimal: boolean;
  solves: number;
  requirement_ids: string[];
}

export interface Bundle {
  schema_version: number;
  model: string;
  summary: Summary;
  requirements: Requirement[];
  variables: Variable[];
  constraints: Constraint[];
  objective: {
    requirement_id: string | null;
    expression: string | null;
    terms: Record<string, number>;
  };
  infeasibility: { violations: Violation[]; conflict?: Conflict | null } | null;
}

export function parseBundle(input: unknown): Bundle {
  if (typeof input !== "object" || input === null) {
    throw new Error("expected a JSON object");
  }
  const bundle = input as Record<string, unknown>;
  if (bundle.schema_version !== SUPPORTED_SCHEMA_VERSION) {
    throw new Error(
      `unsupported schema_version ${JSON.stringify(bundle.schema_version)} (expected ${SUPPORTED_SCHEMA_VERSION}) - is this a finalops debug bundle?`,
    );
  }
  for (const key of ["summary", "requirements", "variables", "constraints", "objective"]) {
    if (!(key in bundle)) throw new Error(`missing "${key}" - is this a finalops debug bundle?`);
  }
  for (const key of ["requirements", "variables", "constraints"]) {
    if (!Array.isArray(bundle[key])) throw new Error(`"${key}" should be a list`);
  }
  return input as Bundle;
}

export function fmt(n: number | null | undefined, digits = 6): string {
  if (n === null || n === undefined) return "—";
  if (n === 0) return "0"; // also normalizes -0
  if (Number.isInteger(n)) return String(n);
  return String(parseFloat(n.toPrecision(digits)));
}

export function fmtBounds(v: Variable): string {
  const lower = v.lower === null ? "-∞" : fmt(v.lower);
  const upper = v.upper === null ? "∞" : fmt(v.upper);
  return `[${lower}, ${upper}]`;
}

export function fmtPercent(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return `${parseFloat((n * 100).toPrecision(3))}%`;
}

export type Tone = "good" | "bad" | "warn" | "neutral";

export function statusTone(status: string): Tone {
  if (status === "Optimal") return "good";
  if (status === "Infeasible" || status === "Unbounded") return "bad";
  return "warn";
}
