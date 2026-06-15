import { describe, expect, it } from "vitest";
import { getInitialMockRun } from "@/lib/mock/agent-runs";
import {
  appendRunToSession,
  createAgentSession,
  createThreadId,
  createTitleFromPrompt
} from "./sessions";

describe("workbench sessions", () => {
  it("creates a stable session around one thread id", () => {
    const session = createAgentSession("帮我查众民保官方资料", {
      now: "2026-06-06T00:00:00.000Z",
      random: () => "abc123"
    });

    expect(session.threadId).toBe("thread_20260606000000_abc123");
    expect(session.title).toBe("帮我查众民保官方资料");
    expect(session.runs).toEqual([]);
  });

  it("keeps thread id when appending runs", () => {
    const session = createAgentSession("first prompt", {
      now: "2026-06-06T00:00:00.000Z",
      random: () => "abc123"
    });
    const run = getInitialMockRun();
    run.requestJson.threadId = session.threadId;

    const next = appendRunToSession(session, run);

    expect(next.threadId).toBe(session.threadId);
    expect(next.activeRunId).toBe(run.id);
    expect(next.runs).toHaveLength(1);
  });

  it("clips long prompt titles", () => {
    expect(createTitleFromPrompt("abcdefghijklmnopqrstuvwxyz0123456789")).toBe(
      "abcdefghijklmnopqrstuvwxyz01..."
    );
    expect(createThreadId("2026-06-06T01:02:03.000Z", () => "xyz")).toBe(
      "thread_20260606010203_xyz"
    );
  });
});
