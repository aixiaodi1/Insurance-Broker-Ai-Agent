import { describe, expect, it, vi } from "vitest";
import { createAgentRun } from "./agent-client";

const input = {
  prompt: "Why did this graph retrieve first?",
  agentId: "research-agent",
  threadId: "thread_test",
  vectorProvider: "chroma" as const,
  debug: true
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
        finalAnswer: "Real answer"
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
});
