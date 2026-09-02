import fs from "node:fs";
import path from "node:path";
import { build } from "esbuild";

const root = import.meta.dirname;
const outdir = path.join(root, "dist");
fs.mkdirSync(outdir, { recursive: true });
for (const name of fs.readdirSync(outdir)) {
  const candidate = path.join(outdir, name);
  if (fs.statSync(candidate).isFile() && (name.endsWith(".js") || name.endsWith(".map"))) {
    fs.unlinkSync(candidate);
  }
}
const entryPoints = fs
  .readdirSync(path.join(root, "src"))
  .filter((name) => name.endsWith(".mjs"))
  .map((name) => path.join(root, "src", name));

await build({
  entryPoints,
  bundle: true,
  platform: "node",
  target: "node22",
  format: "esm",
  splitting: true,
  outdir,
  banner: {
    js: 'import { createRequire as __createRequire } from "node:module"; const require = __createRequire(import.meta.url);',
  },
});
