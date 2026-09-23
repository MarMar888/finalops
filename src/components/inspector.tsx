import { KIND_LABEL, fmt, fmtBounds, type Bundle, type Constraint, type Requirement, type Variable } from "@/lib/bundle";
import { Badge, Card, Chip } from "./ui";

function Fields({ rows }: { rows: [string, string | null][] }) {
  return (
    <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
      {rows
        .filter(([, value]) => value !== null)
        .map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-zinc-500 dark:text-zinc-400">{label}</dt>
            <dd className="font-mono text-xs leading-5">{value}</dd>
          </div>
        ))}
    </dl>
  );
}

function ConstraintDetail({ c, objective }: { c: Constraint; objective: number | null }) {
  const w = c.what_if_dropped;
  let dropped: string | null = null;
  if (w) {
    if (w.status !== "Optimal" || w.objective === null) dropped = w.status;
    else if (objective === null) dropped = fmt(w.objective);
    else dropped = `${fmt(w.objective)} (${w.objective - objective > 0 ? "+" : ""}${fmt(w.objective - objective)})`;
  }
  return (
    <div className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="font-mono text-xs">{c.expression}</div>
      <Fields
        rows={[
          ["Slack", c.slack === null ? null : fmt(c.slack)],
          ["Binding", c.binding === null ? null : c.binding ? "yes" : "no"],
          [
            "Shadow price",
            c.shadow_price === null ? null : `${fmt(c.shadow_price)}${c.shadow_basis === "lp_relaxation" ? " (LP relaxation)" : ""}`,
          ],
          ["In the conflict", c.in_conflict == null ? null : c.in_conflict ? "yes" : "no"],
          ["Must relax by", c.violation === null ? null : fmt(c.violation)],
          ["If dropped", dropped],
        ]}
      />
    </div>
  );
}

function VariableDetail({ v }: { v: Variable }) {
  return (
    <div className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
      <div className="font-mono text-xs">{v.name}</div>
      <Fields
        rows={[
          ["Value", v.value === null ? null : `${fmt(v.value)}${v.units ? ` ${v.units}` : ""}`],
          ["Bounds", fmtBounds(v)],
          ["Type", v.category],
        ]}
      />
    </div>
  );
}

function LinkedDetail({ bundle, req }: { bundle: Bundle; req: Requirement }) {
  return (
    <div className="mt-3 space-y-2">
      {req.linked.map((lc, i) => {
        if (req.kind === "constraint") {
          const c = bundle.constraints.find((k) => k.name === lc.name);
          return c ? (
            <ConstraintDetail key={`${lc.name}-${i}`} c={c} objective={bundle.summary.objective} />
          ) : (
            <p key={`${lc.name}-${i}`} className="font-mono text-xs">{lc.expression}</p>
          );
        }
        if (req.kind === "decision_variable") {
          const v = bundle.variables.find((k) => k.name === lc.name);
          return v ? (
            <VariableDetail key={`${lc.name}-${i}`} v={v} />
          ) : (
            <div key={`${lc.name}-${i}`} className="rounded-md border border-amber-300 bg-amber-50 p-3 text-amber-900 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-200">
              <span className="font-mono text-xs">{lc.name}</span> is declared but doesn&apos;t appear in any constraint or the
              objective, so it has no effect on the solution.
            </div>
          );
        }
        return (
          <div key={`${lc.name}-${i}`} className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800">
            <div className="font-mono text-xs">{lc.expression}</div>
          </div>
        );
      })}
    </div>
  );
}

export function Inspector({ bundle, selectedId }: { bundle: Bundle; selectedId: string | null }) {
  const req = bundle.requirements.find((r) => r.id === selectedId);

  if (!req) {
    return (
      <Card title="Inspector">
        <p className="text-zinc-500 dark:text-zinc-400">
          Select a requirement in the list, or a node in the graph, to see what it links to and what it does to the
          solution.
        </p>
      </Card>
    );
  }

  return (
    <Card title="Inspector" right={<Badge>{KIND_LABEL[req.kind]}</Badge>}>
      <div className="font-mono text-sm font-semibold">{req.id}</div>
      <p className="mt-1">{req.description}</p>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
        from {req.source}
        {req.units ? ` · units: ${req.units}` : ""}
      </p>

      {req.linked.length === 0 ? (
        <div className="mt-3 rounded-md border border-red-300 bg-red-50 p-3 text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          Not linked to anything in the model. This rule is in the brief, but nothing enforces it.
        </div>
      ) : (
        <LinkedDetail bundle={bundle} req={req} />
      )}
    </Card>
  );
}

export function VariablesTable({
  bundle,
  selectedId,
  onSelect,
}: {
  bundle: Bundle;
  selectedId: string | null;
  onSelect: (requirementId: string) => void;
}) {
  if (bundle.variables.length === 0) return null;
  return (
    <Card title="Variables">
      <div className="overflow-x-auto">
        <table className="w-full text-left">
          <thead className="text-xs text-zinc-500 dark:text-zinc-400">
            <tr>
              <th className="pb-2 pr-4 font-medium">Name</th>
              <th className="pb-2 pr-4 font-medium">Value</th>
              <th className="pb-2 pr-4 font-medium">Bounds</th>
              <th className="pb-2 pr-4 font-medium">Type</th>
              <th className="pb-2 pr-4 font-medium">Units</th>
              <th className="pb-2 font-medium">Requirement</th>
            </tr>
          </thead>
          <tbody>
            {bundle.variables.map((v) => (
              <tr
                key={v.name}
                className={`border-t border-zinc-100 dark:border-zinc-900 ${
                  v.requirement_id !== null && v.requirement_id === selectedId ? "bg-blue-50 dark:bg-blue-950" : ""
                }`}
              >
                <td className="py-1.5 pr-4 font-mono text-xs">{v.name}</td>
                <td className="py-1.5 pr-4 font-mono text-xs">{fmt(v.value)}</td>
                <td className="py-1.5 pr-4 font-mono text-xs">{fmtBounds(v)}</td>
                <td className="py-1.5 pr-4 text-xs">{v.category}</td>
                <td className="py-1.5 pr-4 text-xs">{v.units ?? "—"}</td>
                <td className="py-1.5">
                  {v.requirement_id ? (
                    <Chip onClick={() => onSelect(v.requirement_id as string)}>{v.requirement_id}</Chip>
                  ) : (
                    <span className="text-xs text-zinc-500">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
