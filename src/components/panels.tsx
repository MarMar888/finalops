import {
  KIND_LABEL,
  KIND_ORDER,
  fmt,
  fmtPercent,
  statusTone,
  type Bundle,
  type Constraint,
} from "@/lib/bundle";
import { Badge, Card, Chip, SectionLabel, Stat } from "./ui";

export function SummaryBar({ bundle }: { bundle: Bundle }) {
  const s = bundle.summary;
  const linked = bundle.requirements.filter((r) => r.linked.length > 0).length;
  const proven = s.proven_optimal === true;

  return (
    <section className="rounded-lg border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-950">
      <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
        <div>
          <h2 className="text-lg font-semibold">{bundle.model}</h2>
          <div className="mt-1 flex flex-wrap gap-2">
            <Badge tone={statusTone(s.status)}>{s.status}</Badge>
            {s.status === "Optimal" && (
              <Badge tone={proven ? "good" : "warn"}>{proven ? "proven optimal" : "not proven optimal"}</Badge>
            )}
          </div>
        </div>
        <Stat label={s.sense === "max" ? "Objective (maximize)" : "Objective (minimize)"} value={fmt(s.objective)} />
        <Stat label="Solver bound" value={fmt(s.bound)} />
        <Stat label="Gap to bound" value={fmtPercent(s.quality_gap)} />
        <Stat label="Requirements linked" value={`${linked} / ${bundle.requirements.length}`} />
      </div>
      {s.status === "Optimal" && !proven && s.termination && (
        <p className="mt-3 text-sm text-amber-700 dark:text-amber-400">Solver stopped early: {s.termination}</p>
      )}
      {s.problems.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-red-700 dark:text-red-400">
          {s.problems.map((p) => (
            <li key={p}>• {p}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function reqLabel(c: Constraint): string {
  return c.requirement_id ?? c.name;
}

interface DiagnosisProps {
  bundle: Bundle;
  onSelect: (requirementId: string) => void;
}

function InfeasibleWhy({ bundle, onSelect }: DiagnosisProps) {
  const violations = bundle.infeasibility?.violations ?? [];
  const conflict = bundle.infeasibility?.conflict ?? null;
  const analyzed = bundle.constraints.filter((c) => c.what_if_dropped);
  const fixers = analyzed.filter((c) => c.what_if_dropped?.status === "Optimal");
  const others = analyzed.filter((c) => c.what_if_dropped?.status !== "Optimal");

  return (
    <Card title="Why it's infeasible">
      <p>No solution satisfies every rule at the same time.</p>

      {conflict && (
        <div className="mt-4">
          <SectionLabel>These rules cannot all hold together</SectionLabel>
          <ul className="mt-2 space-y-1.5">
            {conflict.members.map((m) => (
              <li key={`${m.kind}:${m.bound ?? ""}:${m.name}`} className="flex flex-wrap items-center gap-2">
                <Chip disabled={!m.requirement_id} onClick={() => m.requirement_id && onSelect(m.requirement_id)}>
                  {m.requirement_id ?? m.name}
                </Chip>
                <span className="font-mono text-xs">{m.expression}</span>
                {m.kind === "bound" && <span className="text-zinc-500 dark:text-zinc-400">variable bound</span>}
                {m.description && <span className="text-zinc-500 dark:text-zinc-400">{m.description}</span>}
              </li>
            ))}
          </ul>
          <p className="mt-2 text-zinc-500 dark:text-zinc-400">
            {conflict.minimal
              ? "Loosen or drop any one of these and the rest can be satisfied."
              : "Not proven minimal: the search hit its solve limit, so some of these may not be needed."}
          </p>
        </div>
      )}

      {violations.length > 0 && (
        <div className="mt-4">
          <SectionLabel>Cheapest relaxation that makes it solvable</SectionLabel>
          <ul className="mt-2 space-y-1.5">
            {violations.map((v) => (
              <li key={v.constraint_name} className="flex flex-wrap items-center gap-2">
                <Chip disabled={!v.requirement_id} onClick={() => v.requirement_id && onSelect(v.requirement_id)}>
                  {v.requirement_id ?? v.constraint_name}
                </Chip>
                <span>
                  relax by <b className="font-mono">{fmt(v.magnitude)}</b>
                </span>
                {v.description && <span className="text-zinc-500 dark:text-zinc-400">{v.description}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {analyzed.length === 0 ? (
        <p className="mt-4 text-zinc-500 dark:text-zinc-400">This bundle was exported without what-if analysis.</p>
      ) : (
        <>
          <div className="mt-4">
            <SectionLabel>Dropping just one of these makes it solvable</SectionLabel>
            {fixers.length > 0 ? (
              <ul className="mt-2 space-y-1.5">
                {fixers.map((c) => (
                  <li key={c.name} className="flex flex-wrap items-center gap-2">
                    <Chip disabled={!c.requirement_id} onClick={() => c.requirement_id && onSelect(c.requirement_id)}>
                      {reqLabel(c)}
                    </Chip>
                    <span className="text-zinc-500 dark:text-zinc-400">
                      then the objective is {fmt(c.what_if_dropped?.objective)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-2 text-zinc-500 dark:text-zinc-400">
                No single rule fixes it on its own, so the conflict involves several rules at once.
              </p>
            )}
          </div>
          {others.length > 0 && (
            <div className="mt-4">
              <SectionLabel>Dropping just one of these does not help</SectionLabel>
              <div className="mt-2 flex flex-wrap gap-2">
                {others.map((c) => (
                  <Chip key={c.name} disabled={!c.requirement_id} onClick={() => c.requirement_id && onSelect(c.requirement_id)}>
                    {reqLabel(c)}
                  </Chip>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

function UnboundedWhy({ bundle, onSelect }: DiagnosisProps) {
  const unlinked = bundle.summary.unlinked_requirements;
  return (
    <Card title="Why it's unbounded">
      <p>The objective can keep improving forever: some direction isn&apos;t capped by any rule in the model.</p>
      {unlinked.length > 0 ? (
        <div className="mt-4">
          <SectionLabel>Rules in the ledger that never made it into the model</SectionLabel>
          <div className="mt-2 flex flex-wrap gap-2">
            {unlinked.map((id) => (
              <Chip key={id} onClick={() => onSelect(id)}>
                {id}
              </Chip>
            ))}
          </div>
          <p className="mt-2 text-zinc-500 dark:text-zinc-400">A missing limit is very likely among these.</p>
        </div>
      ) : (
        <p className="mt-4 text-zinc-500 dark:text-zinc-400">
          Every ledger rule is linked, so the missing cap isn&apos;t in the ledger at all. Check the brief for a limit on
          the variables that drive the objective.
        </p>
      )}
    </Card>
  );
}

function OptimalWhy({ bundle, onSelect }: DiagnosisProps) {
  const objective = bundle.summary.objective;
  const binding = bundle.constraints
    .filter((c) => c.binding)
    .sort((a, b) => Math.abs(b.shadow_price ?? 0) - Math.abs(a.shadow_price ?? 0));
  const loose = bundle.constraints.filter((c) => c.binding === false);
  const approximate = bundle.constraints.some((c) => c.shadow_basis === "lp_relaxation");

  function ifDropped(c: Constraint): string {
    const w = c.what_if_dropped;
    if (!w) return "—";
    if (w.status !== "Optimal" || w.objective === null || objective === null) return w.status;
    const delta = w.objective - objective;
    return `${fmt(w.objective)} (${delta > 0 ? "+" : ""}${fmt(delta)})`;
  }

  return (
    <Card title="What is holding the objective where it is">
      {binding.length === 0 ? (
        <p>Nothing is binding: the objective is limited only by variable bounds.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead className="text-xs text-zinc-500 dark:text-zinc-400">
              <tr>
                <th className="pb-2 pr-4 font-medium">Binding rule</th>
                <th className="pb-2 pr-4 font-medium">Constraint</th>
                <th className="pb-2 pr-4 font-medium">Shadow price</th>
                <th className="pb-2 font-medium">If dropped, objective becomes</th>
              </tr>
            </thead>
            <tbody>
              {binding.map((c) => (
                <tr key={c.name} className="border-t border-zinc-100 dark:border-zinc-900">
                  <td className="py-1.5 pr-4">
                    <Chip disabled={!c.requirement_id} onClick={() => c.requirement_id && onSelect(c.requirement_id)}>
                      {reqLabel(c)}
                    </Chip>
                  </td>
                  <td className="py-1.5 pr-4 font-mono text-xs">{c.expression}</td>
                  <td className="py-1.5 pr-4 font-mono">{fmt(c.shadow_price)}</td>
                  <td className="py-1.5 font-mono">{ifDropped(c)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {loose.length > 0 && (
        <div className="mt-4">
          <SectionLabel>Not binding (room to spare)</SectionLabel>
          <div className="mt-2 flex flex-wrap gap-2">
            {loose.map((c) => (
              <Chip key={c.name} disabled={!c.requirement_id} onClick={() => c.requirement_id && onSelect(c.requirement_id)}>
                {reqLabel(c)} · slack {fmt(c.slack)}
              </Chip>
            ))}
          </div>
        </div>
      )}

      <p className="mt-4 text-xs text-zinc-500 dark:text-zinc-400">
        Shadow price: how much the objective moves per extra unit of room on that rule.
        {approximate && " This model has integer variables, so shadow prices come from the LP relaxation and are approximate."}
      </p>
    </Card>
  );
}

export function Diagnosis({ bundle, onSelect }: DiagnosisProps) {
  switch (bundle.summary.status) {
    case "Infeasible":
      return <InfeasibleWhy bundle={bundle} onSelect={onSelect} />;
    case "Unbounded":
      return <UnboundedWhy bundle={bundle} onSelect={onSelect} />;
    case "Optimal":
      return <OptimalWhy bundle={bundle} onSelect={onSelect} />;
    default:
      return (
        <Card title="Why">
          <p>The solver returned “{bundle.summary.status}”, so there is nothing further to diagnose.</p>
        </Card>
      );
  }
}

export function RequirementList({
  bundle,
  selectedId,
  onSelect,
}: {
  bundle: Bundle;
  selectedId: string | null;
  onSelect: (requirementId: string) => void;
}) {
  const relaxBy = new Map<string, number>();
  for (const v of bundle.infeasibility?.violations ?? []) {
    if (v.requirement_id) relaxBy.set(v.requirement_id, v.magnitude);
  }
  const conflictReqs = new Set(bundle.infeasibility?.conflict?.requirement_ids ?? []);
  const bindingReqs = new Set(bundle.constraints.filter((c) => c.binding).map((c) => c.requirement_id));

  return (
    <Card title="Requirements">
      <div className="space-y-4">
        {KIND_ORDER.map((kind) => {
          const reqs = bundle.requirements.filter((r) => r.kind === kind);
          if (reqs.length === 0) return null;
          return (
            <div key={kind}>
              <SectionLabel>{KIND_LABEL[kind]}</SectionLabel>
              <ul className="mt-1.5 space-y-1">
                {reqs.map((r) => {
                  const active = r.id === selectedId;
                  const unlinked = r.linked.length === 0;
                  const relax = relaxBy.get(r.id);
                  return (
                    <li key={r.id}>
                      <button
                        type="button"
                        onClick={() => onSelect(r.id)}
                        aria-pressed={active}
                        className={`flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-left transition-colors ${
                          active ? "bg-blue-50 dark:bg-blue-950" : "hover:bg-zinc-100 dark:hover:bg-zinc-900"
                        }`}
                      >
                        <span className="truncate font-mono text-xs">{r.id}</span>
                        <span className="flex shrink-0 gap-1">
                          {unlinked && <Badge tone="bad">unlinked</Badge>}
                          {relax !== undefined ? (
                            <Badge tone="bad">relax {fmt(relax)}</Badge>
                          ) : (
                            conflictReqs.has(r.id) && <Badge tone="bad">conflict</Badge>
                          )}
                          {bindingReqs.has(r.id) && <Badge tone="warn">binding</Badge>}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
