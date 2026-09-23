"use client";

import { useState } from "react";
import type { Bundle } from "@/lib/bundle";
import { Inspector, VariablesTable } from "./inspector";
import { Diagnosis, RequirementList, SummaryBar } from "./panels";
import { Structure } from "./structure";

// Selection is the only state here. The parent keys this component by bundle, so
// loading a different bundle remounts it and the selection resets on its own.
export function Viewer({ bundle }: { bundle: Bundle }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const select = (id: string) => setSelectedId((current) => (current === id ? null : id));

  return (
    <div className="flex flex-col gap-4">
      <SummaryBar bundle={bundle} />
      <div className="grid gap-4 lg:grid-cols-[17rem_minmax(0,1fr)]">
        <aside>
          <RequirementList bundle={bundle} selectedId={selectedId} onSelect={select} />
        </aside>
        <div className="flex min-w-0 flex-col gap-4">
          <Diagnosis bundle={bundle} onSelect={select} />
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_21rem]">
            <Structure bundle={bundle} selectedId={selectedId} onSelect={select} />
            <Inspector bundle={bundle} selectedId={selectedId} />
          </div>
          <VariablesTable bundle={bundle} selectedId={selectedId} onSelect={select} />
        </div>
      </div>
    </div>
  );
}
