import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { Debugger, type Sample } from "@/components/debugger";
import { parseBundle } from "@/lib/bundle";

// Bundles in public/samples are produced by finalops/examples/generate_debug_samples.py.
async function loadSamples(): Promise<Sample[]> {
  const dir = path.join(process.cwd(), "public", "samples");
  let files: string[];
  try {
    files = (await readdir(dir)).filter((name) => name.endsWith(".json")).sort();
  } catch {
    return [];
  }
  return Promise.all(
    files.map(async (file) => ({
      name: file.replace(/\.json$/, ""),
      bundle: parseBundle(JSON.parse(await readFile(path.join(dir, file), "utf8"))),
    })),
  );
}

export default async function Page() {
  const samples = await loadSamples();
  return (
    <main className="min-h-screen bg-zinc-50 dark:bg-black">
      <Debugger samples={samples} />
    </main>
  );
}
