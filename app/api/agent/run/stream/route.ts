import { NextResponse } from "next/server";

import type { CreateAgentRunInput } from "@/lib/types/agent";

export async function POST(request: Request) {
  const apiBaseUrl = process.env.AGENT_API_BASE_URL ?? "http://127.0.0.1:8000";
  const body = (await request.json()) as CreateAgentRunInput;
  const upstreamUrl = new URL("/agent/run_v2/stream", apiBaseUrl);

  try {
    const upstream = await fetch(upstreamUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });

    if (!upstream.ok || !upstream.body) {
      const payload = await upstream.json().catch(() => null);
      return NextResponse.json(
        {
          message: "后端流式运行失败",
          statusCode: upstream.status,
          payload
        },
        { status: upstream.status }
      );
    }

    return new Response(upstream.body, {
      status: 200,
      headers: {
        "Content-Type": "application/x-ndjson; charset=utf-8",
        "Cache-Control": "no-cache, no-transform"
      }
    });
  } catch (error) {
    return NextResponse.json(
      {
        message: error instanceof Error ? error.message : "后端流式运行失败",
        statusCode: 502
      },
      { status: 502 }
    );
  }
}
