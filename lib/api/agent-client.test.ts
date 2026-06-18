import { describe, expect, it, vi } from "vitest";
import {
  createAgentRun,
  deleteRunGuidance,
  interruptAgentRun,
  streamAgentRun,
  upsertRunGuidance
} from "./agent-client";

const input = {
  prompt: "为什么先检索资料？",
  agentId: "research-agent",
  threadId: "thread_test",
  vectorProvider: "chroma" as const
};

describe("createAgentRun", () => {
  it("returns a fresh mock run for mock mode", async () => {
    const run = await createAgentRun(input, { mode: "mock" });

    expect(run.id).toMatch(/^run_mock_/);
    expect(run.mode).toBe("mock");
    expect(run.prompt).toBe(input.prompt);
    expect(run.status).toBe("succeeded");
    expect(run.nodes.length).toBeGreaterThan(0);
    expect(run.vectorMatches.length).toBeGreaterThan(0);
    expect(run.requestJson).toMatchObject(input);
  });

  it("posts real runs through the Next.js proxy", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: "run_real_001",
        mode: "real",
        prompt: input.prompt,
        status: "succeeded",
        requestJson: input,
        responseJson: { ok: true },
        finalAnswer: "真实回答"
      })
    });

    vi.stubGlobal("fetch", fetchMock);

    const run = await createAgentRun(input, { mode: "real" });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/agent/run",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input)
      })
    );
    expect(run.mode).toBe("real");
    expect(run.prompt).toBe(input.prompt);

    vi.unstubAllGlobals();
  });

  it("normalizes command approval requests from real runs", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: "run_real_approval",
        mode: "real",
        prompt: input.prompt,
        status: "awaiting_approval",
        requestJson: input,
        responseJson: { ok: true },
        finalAnswer: "需要确认",
        approvalRequest: {
          id: "cmd:1",
          type: "command",
          command: "rm notes.md",
          normalizedCommand: "rm notes.md",
          mode: "build",
          risk: "file_delete",
          reason: "dangerous_pattern"
        }
      })
    });

    vi.stubGlobal("fetch", fetchMock);

    const run = await createAgentRun(input, { mode: "real" });

    expect(run.status).toBe("awaiting_approval");
    expect(run.approvalRequest?.command).toBe("rm notes.md");

    vi.unstubAllGlobals();
  });

  it("streams real runs through the Next.js stream proxy", async () => {
    const encoder = new TextEncoder();
    const finalRun = {
      id: "run_stream",
      mode: "real",
      prompt: input.prompt,
      status: "succeeded",
      requestJson: input,
      responseJson: { ok: true },
      finalAnswer: "stream answer"
    };
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(`${JSON.stringify({ type: "run_started", summary: "started" })}\n`));
        controller.enqueue(encoder.encode(`${JSON.stringify({ type: "thinking", summary: "thinking" })}\n`));
        controller.enqueue(encoder.encode(`${JSON.stringify({ type: "run_finished", run: finalRun })}\n`));
        controller.close();
      }
    });
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      body: stream
    });
    const events: string[] = [];

    vi.stubGlobal("fetch", fetchMock);

    const run = await streamAgentRun(input, {
      mode: "real",
      onEvent: (event) => events.push(event.type)
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/agent/run/stream",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(input)
      })
    );
    expect(events).toEqual(["run_started", "thinking", "run_finished"]);
    expect(run.finalAnswer).toBe("stream answer");

    vi.unstubAllGlobals();
  });

  it("sends interrupt and editable guidance through run control proxies", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", fetchMock);

    await upsertRunGuidance("run-1", "补充内容", "normal");
    await upsertRunGuidance("run-1", "立即纠偏", "immediate");
    await deleteRunGuidance("run-1");
    await interruptAgentRun("run-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/agent/runs/run-1/guidance",
      expect.objectContaining({ method: "PUT", body: JSON.stringify({ content: "补充内容", priority: "normal" }) })
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      4,
      "/api/agent/runs/run-1/control",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ action: "interrupt" }) })
    );
    vi.unstubAllGlobals();
  });
});
