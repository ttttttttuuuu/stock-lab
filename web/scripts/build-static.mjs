// Static-export build for Cloudflare Pages.
// Route handlers under app/api are local-only (they spawn the Python engine),
// so they are moved aside for the duration of the export build and restored
// afterwards no matter how the build ends.
import { spawnSync } from "node:child_process";
import { existsSync, renameSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;
const apiDir = join(root, "app", "api");
const stash = join(root, ".api-stash");

let moved = false;
try {
  if (existsSync(apiDir)) {
    renameSync(apiDir, stash);
    moved = true;
  }
  const r = spawnSync("npx", ["next", "build"], {
    cwd: root,
    stdio: "inherit",
    env: {
      ...process.env,
      NEXT_STATIC_EXPORT: "1",
      NEXT_PUBLIC_STATIC_EXPORT: "1",
      // side-by-side with a running dev server; with a custom distDir the
      // static export lands inside it instead of out/, so rename afterwards
      NEXT_DIST_DIR: ".next-static",
    },
  });
  process.exitCode = r.status ?? 1;
  const dist = join(root, ".next-static");
  const out = join(root, "out");
  if (process.exitCode === 0 && existsSync(join(dist, "index.html"))) {
    renameSync(dist, out);
    console.log("static site -> out/");
  }
} finally {
  if (moved) renameSync(stash, apiDir);
}
