import { describe, expect, it } from "vitest";
import { normalizeAgentRun } from "./agent-client";

describe("normalizeAgentRun", () => {
  it("fills optional trace fields with a readable fallback trace", () => {
    const run = normalizeAgentRun({
      id: "run_test",
      mode: "real",
      prompt: "Trace this agent",
      status: "succeeded",
      requestJson: { prompt: "Trace this agent" },
      responseJson: { ok: true },
      finalAnswer: "Done"
    });

    expect(run.nodes.map((node) => node.label)).toEqual([
      "收到问题",
      "检索知识",
      "生成回答"
    ]);
    expect(run.events.map((event) => event.title)).toEqual([
      "收到问题",
      "检索知识片段",
      "生成最终回答"
    ]);
    expect(run.toolCalls).toEqual([]);
    expect(run.vectorMatches).toEqual([]);
  });

  it("rejects malformed agent run responses", () => {
    expect(() => normalizeAgentRun({ status: "succeeded" })).toThrow(
      "Invalid agent run response"
    );
  });

  it("builds a simple trace when the backend only returns an answer and text matches", () => {
    const run = normalizeAgentRun({
      id: "run_simple",
      mode: "real",
      prompt: "哆啦A梦用了哪三个秘密道具？",
      status: "succeeded",
      latencyMs: 8874,
      finalAnswer: "三个秘密道具分别是复制斗篷、时间停止手表、精神与时光屋便携版。",
      vectorMatches: [
        "三件秘密道具分别是：复制斗篷、时间停止手表、精神与时光屋便携版。",
        "大雄在精神屋内接受训练。"
      ]
    });

    expect(run.nodes.map((node) => node.id)).toEqual([
      "receive_question",
      "retrieve_context",
      "generate_answer"
    ]);
    expect(run.events.map((event) => event.type)).toEqual([
      "node_start",
      "retrieval",
      "final_answer"
    ]);
    expect(run.vectorMatches[0]).toMatchObject({
      id: "vec_1",
      nodeId: "retrieve_context",
      title: "知识片段 1",
      contentPreview: "三件秘密道具分别是：复制斗篷、时间停止手表、精神与时光屋便携版。"
    });
  });
});
