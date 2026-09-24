// Parameter optimization refresh: on-demand grid search triggered from the
// /lab/optimize page. Expensive (~68 combos x 50 symbols), so it is never
// auto-triggered by page views — only by an explicit button click.
//
//   GET  /api/param-opt/refresh         -> { running, run_at }
//   POST /api/param-opt/refresh?force=1 -> { status: "started" | "running" | "fresh" }
import { NextResponse } from "next/server";
import { handleGet, handlePost } from "../../../../lib/refreshJobs";

export const dynamic = "force-dynamic";

export async function GET() {
  const r = handleGet("param-opt");
  return NextResponse.json(r.body, { status: r.status });
}

export async function POST(req) {
  const force = new URL(req.url).searchParams.get("force") === "1";
  const r = handlePost("param-opt", { force });
  return NextResponse.json(r.body, { status: r.status });
}
