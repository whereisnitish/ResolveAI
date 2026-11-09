// Builds dist/widget.js (single IIFE, no dependencies). `--serve` runs a local
// dev server on :3002 that also serves demo/index.html.
import * as esbuild from "esbuild";

const serve = process.argv.includes("--serve");

const options = {
  entryPoints: ["src/index.ts"],
  bundle: true,
  format: "iife",
  target: ["es2020"],
  minify: !serve,
  sourcemap: serve ? "inline" : false,
  outfile: "dist/widget.js",
  legalComments: "none",
  logLevel: "info",
};

if (serve) {
  const ctx = await esbuild.context({ ...options, outfile: "demo/widget.js" });
  await ctx.watch();
  const { host, port } = await ctx.serve({ servedir: "demo", port: 3002, host: "127.0.0.1" });
  console.log(`Widget demo: http://localhost:${port}/  (served from ${host})`);
} else {
  await esbuild.build(options);
}
