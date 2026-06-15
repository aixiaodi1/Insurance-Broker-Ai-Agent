import { describe, expect, it, vi } from "vitest";
import { POST } from "./route";

describe("POST /api/agent/run", () => {
  it("proxies chat prompts to the backend without frontend debug flags", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        id: "run-1",
        mode: "real",
        prompt: "帮我查众民保官方资料",
        status: "succeeded",
        nodes: [],
        events: [],
        toolCalls: [],
        vectorMatches: [],
        requestJson: {},
        responseJson: {},
        finalAnswer: "done"
      })
    });
    vi.stubGlobal("fetch", fetchMock);

    const request = new Request("http://localhost/api/agent/run", {
      method: "POST",
      body: JSON.stringify({
        prompt: "帮我查众民保官方资料",
        agentId: "website-demo",
        threadId: "thread-1",
        vectorProvider: "chroma"
      })
    });

    const response = await POST(request);
    const body = await response.json();

    expect(fetchMock).toHaveBeenCalledWith(
      new URL("http://127.0.0.1:8000/agent/run_v2"),
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: "帮我查众民保官方资料",
          agentId: "website-demo",
          threadId: "thread-1",
          vectorProvider: "chroma"
        })
      })
    );
    expect(body).toMatchObject({
      id: "run-1",
      mode: "real",
      prompt: "帮我查众民保官方资料",
      finalAnswer: "done"
    });

    vi.unstubAllGlobals();
  });
});
