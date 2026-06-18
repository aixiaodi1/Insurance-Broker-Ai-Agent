import { NextResponse } from "next/server";

import type { CreateAgentRunInput } from "@/lib/types/agent";

export async function POST(request: Request) {
  const apiBaseUrl = process.env.AGENT_API_BASE_URL ?? "http://127.0.0.1:8000";
  const body = (await request.json()) as CreateAgentRunInput;
  const upstreamUrl = new URL("/agent/research", apiBaseUrl);

  try {
    const upstream = await fetch(upstreamUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        user_id: "default",
        thread_id: body.threadId,
        message: body.prompt
      })
    });
    const payload = await upstream.json().catch(() => null);

    if (!upstream.ok) {
      return NextResponse.json(
        {
          message: "后端运行失败",
          statusCode: upstream.status,
          payload
        },
        { status: upstream.status }
      );
    }

    const record = typeof payload === "object" && payload !== null ? payload as Record<string, unknown> : {};
    return NextResponse.json({
      ...record,
      id: record.run_id ?? record.id,
      mode: "real",
      prompt: body.prompt,
      status: Array.isArray(record.stop_reasons) && record.stop_reasons.length ? "failed" : "succeeded",
      nodes: [],
      events: [],
      toolCalls: [],
      vectorMatches: [],
      finalAnswer: record.final_summary ?? record.finalAnswer ?? "",
      requestJson: body,
      responseJson: payload ?? {}
    });
  } catch (error) {
    return NextResponse.json(
      {
        message: error instanceof Error ? error.message : "后端运行失败",
        statusCode: 502
      },
      { status: 502 }
    );
  }
}
