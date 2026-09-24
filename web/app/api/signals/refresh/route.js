// Signals lazy refresh: first visitor of the day triggers the daily engine
// (refresh prices -> compute signals -> manage paper option positions with
// real chains -> equity snapshot -> sync Supabase + re-export local JSON).
// Idempotent within a day (engine guards on last_mark_date); the lock file
// guarantees a single concurrent run.
//
//   GET  /api/signals/refresh  -> { running, run_at }
//   POST /api/signals/refresh  -> { status: "started" | "running" | "fresh" }
import { NextResponse } from "next/server";
import { handleGet, handlePost } from "../../../../lib/refreshJobs";

export const dynamic = "force-dynamic";

export async function GET() {
  const r = handleGet("signals");
  return NextResponse.json(r.body, { status: r.status });
}

export async function POST() {
  const r = handlePost("signals");
  return NextResponse.json(r.body, { status: r.status });
}
