// Futu sim account refresh: runs engine.futu_export against the local OpenD
// gateway. Fast (~3s), so we run it synchronously per request with a guard
// against concurrent runs. Only useful on the machine hosting OpenD; on any
// other host the export writes available:false and this returns that state.
//
//   POST /api/futu/refresh  -> futu_sim.json payload (fresh)
//   GET  /api/futu/refresh  -> current futu_sim.json payload (no refresh)
import { spawn } from "child_process";
import fs from "fs";
import path from "path";
import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const ROOT = path.resolve(process.cwd(), "..");
const PYTHON =
  process.env.PYTHON_BIN ||
  "/Users/ttwong/Library/Application Support/kimi-desktop/daimon-share/daimon/runtime/python/.venv/bin/python";
const DATA_FILE = path.join(ROOT, "web", "public", "data", "futu_sim.json");
let running = false;

function readPayload() {
  try {
    return JSON.parse(fs.readFileSync(DATA_FILE, "utf8"));
  } catch {
    return { available: false, error: "尚无数据，点击刷新" };
  }
}

export async function GET() {
  return NextResponse.json(readPayload());
}

export async function POST() {
  if (running) {
    return NextResponse.json({ ...readPayload(), refreshing: true });
  }
  running = true;
  try {
    await new Promise((resolve) => {
      const child = spawn(PYTHON, ["-m", "engine.futu_export"], { cwd: ROOT });
      const timer = setTimeout(() => { try { child.kill(); } catch {} }, 30000);
      child.on("error", () => { clearTimeout(timer); resolve(); });
      child.on("exit", () => { clearTimeout(timer); resolve(); });
    });
  } finally {
    running = false;
  }
  return NextResponse.json(readPayload());
}
