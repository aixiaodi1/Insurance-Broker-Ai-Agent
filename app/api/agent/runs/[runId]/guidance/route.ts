import { NextResponse } from "next/server";

async function proxy(request: Request, method: "PUT" | "DELETE", runId: string) {
  const apiBaseUrl = process.env.AGENT_API_BASE_URL ?? "http://127.0.0.1:8000";
  const upstream = await fetch(new URL(`/agent/runs/${runId}/guidance`, apiBaseUrl), {
    method,
    headers: { "Content-Type": "application/json" },
    body: method === "PUT" ? JSON.stringify(await request.json()) : undefined
  });
  const payload = await upstream.json().catch(() => null);
  return NextResponse.json(payload, { status: upstream.status });
}

export async function PUT(request: Request, context: { params: Promise<{ runId: string }> }) {
  return proxy(request, "PUT", (await context.params).runId);
}

export async function DELETE(request: Request, context: { params: Promise<{ runId: string }> }) {
  return proxy(request, "DELETE", (await context.params).runId);
}
