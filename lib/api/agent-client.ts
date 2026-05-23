import { getInitialMockRun } from "@/lib/mock/agent-runs";
import {
  AgentRunError,
  type AgentApiMode,
  type AgentNode,
  type AgentRun,
  type AgentTraceEvent,
  type AgentVectorMatch,
  type CreateAgentRunInput
} from "@/lib/types/agent";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function asString(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function normalizeVectorMatches(value: unknown): AgentVectorMatch[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.map((match, index) => {
    if (typeof match === "string") {
      return {
        id: `vec_${index + 1}`,
        nodeId: "retrieve_context",
        provider: "qdrant",
        collection: "default",
        title: `知识片段 ${index + 1}`,
        contentPreview: match,
        metadata: {}
      };
    }

    if (isRecord(match)) {
      return {
        id: asString(match.id, `vec_${index + 1}`),
        nodeId: asString(match.nodeId, "retrieve_context"),
        provider:
          match.provider === "tencent-vectordb" || match.provider === "qdrant"
            ? match.provider
            : "qdrant",
        collection: asString(match.collection, "default"),
        score: typeof match.score === "number" ? match.score : undefined,
        title: asString(match.title, `知识片段 ${index + 1}`),
        contentPreview: asString(
          match.contentPreview ?? match.content ?? match.document,
          "后端返回了知识片段，但没有提供文本内容。"
        ),
        metadata: isRecord(match.metadata) ? match.metadata : {}
      };
    }

    return {
      id: `vec_${index + 1}`,
      nodeId: "retrieve_context",
      provider: "qdrant",
      collection: "default",
      title: `知识片段 ${index + 1}`,
      contentPreview: String(match),
      metadata: {}
    };
  });
}

function buildFallbackNodes(run: AgentRun): AgentNode[] {
  return [
    {
      id: "receive_question",
      label: "收到问题",
      status: run.status === "failed" ? "failed" : "succeeded",
      startedAt: run.startedAt,
      stateSummary: "网站已经把你的问题发送给 FastAPI 后端。"
    },
    {
      id: "retrieve_context",
      label: "检索知识",
      status: run.status === "failed" ? "failed" : "succeeded",
      stateSummary: run.vectorMatches.length
        ? `后端返回了 ${run.vectorMatches.length} 条知识片段。`
        : "后端没有返回知识片段。"
    },
    {
      id: "generate_answer",
      label: "生成回答",
      status: run.status === "failed" ? "failed" : "succeeded",
      finishedAt: run.finishedAt,
      durationMs: run.latencyMs,
      stateSummary: run.finalAnswer
        ? "后端已经生成最终回答。"
        : "后端没有返回最终回答。"
    }
  ];
}

function buildFallbackEvents(run: AgentRun): AgentTraceEvent[] {
  const timestamp = run.startedAt ?? new Date().toISOString();

  return [
    {
      id: "evt_receive_question",
      nodeId: "receive_question",
      type: "node_start",
      timestamp,
      title: "收到问题",
      detail: run.prompt,
      payload: { prompt: run.prompt }
    },
    {
      id: "evt_retrieve_context",
      nodeId: "retrieve_context",
      type: "retrieval",
      timestamp,
      title: "检索知识片段",
      detail: run.vectorMatches.length
        ? `找到 ${run.vectorMatches.length} 条知识片段。`
        : "后端没有返回知识片段。",
      payload: { vectorMatches: run.vectorMatches }
    },
    {
      id: "evt_generate_answer",
      nodeId: "generate_answer",
      type: "final_answer",
      timestamp: run.finishedAt ?? timestamp,
      title: "生成最终回答",
      detail: run.finalAnswer,
      payload: { finalAnswer: run.finalAnswer }
    }
  ];
}

export function normalizeAgentRun(value: unknown): AgentRun {
  if (!isRecord(value)) {
    throw new Error("Invalid agent run response");
  }

  const { id, mode, prompt, status, finalAnswer } = value;

  if (
    typeof id !== "string" ||
    (mode !== "mock" && mode !== "real") ||
    typeof prompt !== "string" ||
    typeof status !== "string" ||
    typeof finalAnswer !== "string"
  ) {
    throw new Error("Invalid agent run response");
  }

  const run = value as unknown as AgentRun;

  const normalizedRun = {
    ...run,
    vectorMatches: normalizeVectorMatches(value.vectorMatches),
    nodes: Array.isArray(value.nodes) ? value.nodes : [],
    events: Array.isArray(value.events) ? value.events : [],
    toolCalls: Array.isArray(value.toolCalls) ? value.toolCalls : [],
    requestJson: isRecord(value.requestJson) ? value.requestJson : {},
    responseJson: isRecord(value.responseJson) ? value.responseJson : {}
  };

  return {
    ...normalizedRun,
    nodes: normalizedRun.nodes.length
      ? normalizedRun.nodes
      : buildFallbackNodes(normalizedRun),
    events: normalizedRun.events.length
      ? normalizedRun.events
      : buildFallbackEvents(normalizedRun)
  };
}

export interface CreateAgentRunOptions {
  mode?: AgentApiMode;
}

export async function createAgentRun(
  input: CreateAgentRunInput,
  options: CreateAgentRunOptions = {}
): Promise<AgentRun> {
  const mode = options.mode ?? "mock";

  if (mode === "mock") {
    const now = new Date().toISOString();
    const mockRun = getInitialMockRun();

    return normalizeAgentRun({
      ...mockRun,
      id: `run_mock_${Date.now()}`,
      mode: "mock",
      prompt: input.prompt,
      startedAt: now,
      finishedAt: now,
      requestJson: input,
      responseJson: {
        ...mockRun.responseJson,
        mode: "mock",
        prompt: input.prompt
      }
    });
  }

  const response = await fetch("/api/agent/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input)
  });

  const payload = await response.json().catch(() => null);

  if (!response.ok) {
    const message =
      isRecord(payload) && typeof payload.message === "string"
        ? payload.message
        : "Agent 运行请求失败";

    throw new AgentRunError(message, response.status, payload);
  }

  return normalizeAgentRun(payload);
}
