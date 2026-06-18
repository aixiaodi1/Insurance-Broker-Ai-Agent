import { NextResponse } from "next/server";

export async function POST(request: Request, context: { params: Promise<{ runId: string }> }) {
  const apiBaseUrl = process.env.AGENT_API_BASE_URL ?? "http://127.0.0.1:8000";
  const { runId } = await context.params;
  const upstream = await fetch(new URL(`/agent/runs/${runId}/control`, apiBaseUrl), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(await request.json())
  });
  const payload = await upstream.json().catch(() => null);
  return NextResponse.json(payload, { status: upstream.status });
}
