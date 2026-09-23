"use client";

import { useState } from "react";
import { parseBundle, type Bundle } from "@/lib/bundle";
import { Viewer } from "./viewer";

export interface Sample {
  name: string;
  bundle: Bundle;
}

type Loaded = { source: "sample" | "file"; name: string; bundle: Bundle; key: number };

const FILE_OPTION = "__file__";

export function Debugger({ samples }: { samples: Sample[] }) {
  const [current, setCurrent] = useState<Loaded | null>(
    samples[0] ? { source: "sample", name: samples[0].name, bundle: samples[0].bundle, key: 0 } : null,
  );
  const [error, setError] = useState<string | null>(null);

  function load(source: Loaded["source"], name: string, bundle: Bundle) {
    setError(null);
    setCurrent((prev) => ({ source, name, bundle, key: (prev?.key ?? 0) + 1 }));
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    try {
      load("file", file.name, parseBundle(JSON.parse(await file.text())));
    } catch (err) {
      setError(`Couldn't load ${file.name}: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-4 px-4 py-6 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">finalops · LP debugger</h1>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-sm">
          {samples.length > 0 && (
            <label className="flex items-center gap-2">
              <span className="text-zinc-600 dark:text-zinc-400">Sample</span>
              <select
                className="rounded-md border border-zinc-300 bg-white px-2 py-1 dark:border-zinc-700 dark:bg-zinc-950"
                value={current?.source === "file" ? FILE_OPTION : (current?.name ?? "")}
                onChange={(event) => {
                  const sample = samples.find((s) => s.name === event.target.value);
                  if (sample) load("sample", sample.name, sample.bundle);
                }}
              >
                {current?.source === "file" && <option value={FILE_OPTION}>Uploaded: {current.name}</option>}
                {samples.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="cursor-pointer rounded-md border border-zinc-300 px-3 py-1 hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-900">
            Load bundle…
            <input
              type="file"
              accept="application/json,.json"
              className="sr-only"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                void onFile(file);
              }}
            />
          </label>
        </div>
      </header>

      {error && (
        <p role="alert" className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900 dark:border-red-900 dark:bg-red-950 dark:text-red-200">
          {error}
        </p>
      )}

      {current ? (
        <Viewer key={current.key} bundle={current.bundle} />
      ) : (
        <div className="rounded-lg border border-dashed border-zinc-300 p-10 text-center text-sm text-zinc-600 dark:border-zinc-700 dark:text-zinc-400">
          <p>No bundle loaded.</p>
          <p className="mt-1">
            Generate one with <code className="font-mono">build_debug_bundle(model, out=&quot;bundle.json&quot;)</code> and load
            it above.
          </p>
        </div>
      )}
    </div>
  );
}
