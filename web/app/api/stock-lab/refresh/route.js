// Stock Lab lazy refresh: the first visitor of the day triggers a refresh
// (fetch latest prices -> rerun the 50x6 stock backtest -> sync Supabase +
// re-export local JSON). A lock file guarantees only one run at a time;
// everyone else just reads the DB.
//
//   GET  /api/stock-lab/refresh  -> { running, run_at }
//   POST /api/stock-lab/refresh  -> { status: "started" | "running" | "fresh" }
import { NextResponse } from "next/server";
import { handleGet, handlePost } from "../../../../lib/refreshJobs";

export const dynamic = "force-dynamic";

export async function GET() {
  const r = handleGet("stock-lab");
  return NextResponse.json(r.body, { status: r.status });
}

export async function POST() {
  const r = handlePost("stock-lab");
  return NextResponse.json(r.body, { status: r.status });
}
