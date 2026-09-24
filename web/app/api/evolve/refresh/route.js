// Evolution refresh: on-demand full strategy evolution triggered from the
// /lab/optimize page. Refetches all prices from scratch (full window, never
// just the missing week), reruns both grids, promotes guarded winners,
// reruns the backtest matrix, syncs and re-exports. ~15-20 min.
//
//   GET  /api/evolve/refresh         -> { running, run_at }
//   POST /api/evolve/refresh?force=1 -> { status: "started" | "running" | "fresh" }
import { NextResponse } from "next/server";
import { handleGet, handlePost } from "../../../../lib/refreshJobs";

export const dynamic = "force-dynamic";

export async function GET() {
  const r = handleGet("evolve");
  return NextResponse.json(r.body, { status: r.status });
}

export async function POST(req) {
  const force = new URL(req.url).searchParams.get("force") === "1";
  const r = handlePost("evolve", { force });
  return NextResponse.json(r.body, { status: r.status });
}
