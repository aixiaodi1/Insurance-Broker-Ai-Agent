import { describe, expect, it, vi } from "vitest";
import { POST } from "./route";

describe("POST /api/agent/run/stream", () => {
  it("maps the workbench request to the transparent research stream without buffering", async () => {
    const upstreamBody = new ReadableStream();
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, body: upstreamBody });
    vi.stubGlobal("fetch", fetchMock);
    const request = new Request("http://localhost/api/agent/run/stream", {
      method: "POST",
      body: JSON.stringify({ prompt: "检查 Agent", threadId: "thread-1", agentId: "research-agent" })
    });

    const response = await POST(request);

    expect(fetchMock).toHaveBeenCalledWith(
      new URL("http://127.0.0.1:8000/agent/research/stream"),
      expect.objectContaining({
        body: JSON.stringify({ user_id: "default", thread_id: "thread-1", message: "检查 Agent" })
      })
    );
    expect(response.body).toBe(upstreamBody);
    expect(response.headers.get("Cache-Control")).toBe("no-cache, no-transform");
    expect(response.headers.get("X-Accel-Buffering")).toBe("no");
    vi.unstubAllGlobals();
  });
});
