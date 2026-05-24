import { NextResponse } from "next/server";

export async function POST(request: Request) {
  const apiBaseUrl = process.env.AGENT_API_BASE_URL;

  if (!apiBaseUrl) {
    return NextResponse.json(
      {
        message: "还没有配置 AGENT_API_BASE_URL，无法连接 FastAPI 后端",
        statusCode: 503
      },
      { status: 503 }
    );
  }

  const body = await request.json();
  const upstreamUrl = new URL("/agent/run", apiBaseUrl);

  try {
    const upstream = await fetch(upstreamUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    const payload = await upstream.json().catch(() => null);

    if (!upstream.ok) {
      return NextResponse.json(
        {
          message: "FastAPI 运行 Agent 失败",
          statusCode: upstream.status,
          payload
        },
        { status: upstream.status }
      );
    }

    return NextResponse.json({
      ...(typeof payload === "object" && payload !== null ? payload : {}),
      mode: "real",
      requestJson: body,
      responseJson: payload ?? {}
    });
  } catch (error) {
    return NextResponse.json(
      {
        message: error instanceof Error ? error.message : "FastAPI 运行 Agent 失败",
        statusCode: 502
      },
      { status: 502 }
    );
  }
}
