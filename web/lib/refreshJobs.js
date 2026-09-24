// Shared lazy-refresh job machinery for the web API routes.
// First visitor of the day triggers a refresh; a lock file guarantees a
// single run; everyone else reads the DB. Each job declares its engine
// command chain and the marker file that records the last successful run.
import { spawn } from "child_process";
import fs from "fs";
import path from "path";

const ROOT = path.resolve(process.cwd(), "..");
const LOCK_TTL_MS = 20 * 60 * 1000;
const EVOLVE_LOCK_TTL_MS = 45 * 60 * 1000; // full evolution can take ~20 min

const PYTHON =
  process.env.PYTHON_BIN ||
  "/Users/ttwong/Library/Application Support/kimi-desktop/daimon-share/daimon/runtime/python/.venv/bin/python";

export const JOBS = {
  "stock-lab": {
    marker: "data/stock_summary.json",
    lock: "data/stock_lab_refresh.lock",
    log: "data/stock_lab_refresh.log",
    commands: [["engine.run_stock_backtest"], ["engine.capital_sim", "--timeframes", "1d"], ["engine.export_web"]],
  },
  signals: {
    marker: "data/signals_summary.json",
    lock: "data/signals_refresh.lock",
    log: "data/signals_refresh.log",
    // single sync at the end — intermediate steps run with --no-sync
    commands: [
      ["engine.daily_signals", "--no-sync"],
      ["engine.stock_paper", "--no-sync", "--top", "20"],
      ["engine.intraday_paper"],
      ["engine.sync"],
      ["engine.export_web"],
    ],
  },
  "param-opt": {
    marker: "data/param_opt_summary.json",
    lock: "data/param_opt_refresh.lock",
    log: "data/param_opt_refresh.log",
    // on-demand grid search (strategy params + exit structures); single sync at end
    commands: [
      ["engine.param_optimize", "--no-sync"],
      ["engine.exit_optimize", "--no-sync"],
      ["engine.sync"],
      ["engine.export_web"],
    ],
  },
  evolve: {
    marker: "data/weekly_evolve_summary.json",
    lock: "data/evolve_refresh.lock",
    log: "data/evolve_refresh.log",
    lockTtl: EVOLVE_LOCK_TTL_MS,
    // full evolution: refetch ALL prices from scratch (full 2y window, never
    // just a week), rerun both grids, promote guarded winners, rerun the
    // backtest matrix, sync Supabase and re-export — all inside the module
    commands: [["engine.weekly_evolve"]],
  },
};

export function readRunAt(job) {
  try {
    return JSON.parse(fs.readFileSync(path.join(ROOT, job.marker), "utf8")).run_at ?? null;
  } catch {
    return null;
  }
}

function lockRunning(job) {
  const p = path.join(ROOT, job.lock);
  const ttl = job.lockTtl || LOCK_TTL_MS;
  try {
    const age = Date.now() - Number(fs.readFileSync(p, "utf8"));
    if (age > ttl) {
      fs.unlinkSync(p); // stale lock from a crashed/killed run
      return false;
    }
    return true;
  } catch {
    return false;
  }
}

export function isFresh(runAt) {
  // fresh if the last run happened on the same local calendar day
  if (!runAt) return false;
  const d = new Date(runAt);
  const now = new Date();
  return d.getFullYear() === now.getFullYear()
    && d.getMonth() === now.getMonth()
    && d.getDate() === now.getDate();
}

export function handleGet(jobName) {
  const job = JOBS[jobName];
  if (!job) return { status: 404, body: { error: "unknown job" } };
  return { status: 200, body: { running: lockRunning(job), run_at: readRunAt(job) } };
}

export function handlePost(jobName, { force = false } = {}) {
  const job = JOBS[jobName];
  if (!job) return { status: 404, body: { error: "unknown job" } };
  const runAt = readRunAt(job);
  if (lockRunning(job)) return { status: 200, body: { status: "running", run_at: runAt } };
  if (!force && isFresh(runAt)) return { status: 200, body: { status: "fresh", run_at: runAt } };

  fs.writeFileSync(path.join(ROOT, job.lock), String(Date.now()));
  const out = fs.openSync(path.join(ROOT, job.log), "a");
  const code = "import subprocess,sys;"
    + "codes=["
    + job.commands.map((cmd) =>
        `subprocess.run([sys.executable,'-m',${cmd.map((a) => `'${a}'`).join(",")}]).returncode`).join(",")
    + "];sys.exit(max(codes))";
  const child = spawn(PYTHON, ["-c", code],
    { cwd: ROOT, detached: true, stdio: ["ignore", out, out] });
  const lockPath = path.join(ROOT, job.lock);
  child.on("exit", () => { try { fs.unlinkSync(lockPath); } catch {} });
  child.unref();
  return { status: 200, body: { status: "started", run_at: runAt } };
}
