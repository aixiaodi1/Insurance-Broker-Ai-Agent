import type { AgentRun } from "@/lib/types/agent";

const startedAt = "2026-05-23T06:10:00.000Z";
const finishedAt = "2026-05-23T06:10:02.420Z";

export const mockAgentRun: AgentRun = {
  id: "run_mock_001",
  mode: "mock",
  prompt: "帮我检查 LangGraph Agent 为什么先检索再调用工具。",
  status: "succeeded",
  startedAt,
  finishedAt,
  latencyMs: 2420,
  tokens: {
    prompt: 812,
    completion: 468,
    total: 1280
  },
  nodes: [
    {
      id: "start",
      label: "开始",
      status: "succeeded",
      startedAt,
      finishedAt: "2026-05-23T06:10:00.120Z",
      durationMs: 120,
      stateSummary: "接收调试指令，并初始化本次运行的调试状态。"
    },
    {
      id: "retrieve_context",
      label: "检索上下文",
      status: "succeeded",
      startedAt: "2026-05-23T06:10:00.130Z",
      finishedAt: "2026-05-23T06:10:00.740Z",
      durationMs: 610,
      stateSummary: "从 qdrant 的 knowledge_base 集合读取到 3 条相关片段。"
    },
    {
      id: "call_tool",
      label: "调用工具",
      status: "succeeded",
      startedAt: "2026-05-23T06:10:00.760Z",
      finishedAt: "2026-05-23T06:10:01.360Z",
      durationMs: 600,
      stateSummary: "把当前图状态传给 inspect_trace 工具进行分析。"
    },
    {
      id: "generate_answer",
      label: "生成回答",
      status: "succeeded",
      startedAt: "2026-05-23T06:10:01.390Z",
      finishedAt: "2026-05-23T06:10:02.310Z",
      durationMs: 920,
      stateSummary: "结合检索片段和工具输出生成最终回答。"
    },
    {
      id: "end",
      label: "结束",
      status: "succeeded",
      startedAt: "2026-05-23T06:10:02.320Z",
      finishedAt,
      durationMs: 100,
      stateSummary: "整理运行轨迹并结束本次调试。"
    }
  ],
  events: [
    {
      id: "evt_start",
      nodeId: "start",
      type: "node_start",
      timestamp: startedAt,
      title: "运行开始",
      detail: "LangGraph 状态已经初始化。",
      payload: { threadId: "thread_mock_001", debug: true }
    },
    {
      id: "evt_retrieval",
      nodeId: "retrieve_context",
      type: "retrieval",
      timestamp: "2026-05-23T06:10:00.720Z",
      title: "向量检索返回 3 条结果",
      detail: "最高分片段解释了为什么先检索再调用工具。",
      payload: { provider: "qdrant", collection: "knowledge_base", matches: 3 }
    },
    {
      id: "evt_tool",
      nodeId: "call_tool",
      type: "tool_call",
      timestamp: "2026-05-23T06:10:01.220Z",
      title: "inspect_trace 工具完成",
      detail: "工具返回了状态流转分析。",
      payload: { tool: "inspect_trace", status: "succeeded" }
    },
    {
      id: "evt_generate",
      nodeId: "generate_answer",
      type: "token_stream",
      timestamp: "2026-05-23T06:10:01.900Z",
      title: "正在生成最终回答",
      detail: "模型输出正在流式返回。",
      payload: { tokens: 468 }
    },
    {
      id: "evt_final",
      nodeId: "end",
      type: "final_answer",
      timestamp: finishedAt,
      title: "最终回答已生成",
      detail: "本次运行已成功完成。",
      payload: { status: "succeeded" }
    }
  ],
  toolCalls: [
    {
      id: "tool_001",
      nodeId: "call_tool",
      name: "inspect_trace",
      status: "succeeded",
      arguments: {
        runId: "run_mock_001",
        includeStateDiff: true
      },
      durationMs: 418,
      resultPreview: "图先检索上下文，是因为路由器判断这个问题依赖知识库内容。"
    }
  ],
  vectorMatches: [
    {
      id: "vec_001",
      nodeId: "retrieve_context",
      provider: "qdrant",
      collection: "knowledge_base",
      score: 0.92,
      title: "LangGraph 路由策略",
      contentPreview: "依赖知识库的问题应该先检索上下文，再调用诊断工具。",
      metadata: {
        source: "agent_playbook.md",
        chunk: 12
      }
    },
    {
      id: "vec_002",
      nodeId: "retrieve_context",
      provider: "qdrant",
      collection: "knowledge_base",
      score: 0.87,
      title: "轨迹检查工具协议",
      contentPreview: "inspect_trace 工具需要节点 id、状态摘要和耗时信息。",
      metadata: {
        source: "tool_contracts.md",
        chunk: 4
      }
    }
  ],
  requestJson: {
    prompt: "帮我检查 LangGraph Agent 为什么先检索再调用工具。",
    agentId: "research-agent",
    threadId: "thread_mock_001",
    vectorProvider: "qdrant",
    debug: true
  },
  responseJson: {
    id: "run_mock_001",
    status: "succeeded",
    latencyMs: 2420,
    nodes: 5,
    vectorMatches: 2
  },
  finalAnswer:
    "这次 Agent 先进入 retrieve_context，是因为路由器把问题判定为需要知识库上下文。随后 call_tool 节点拿到检索摘要再调用 inspect_trace，因此工具输入更完整。"
};

export function getInitialMockRun(): AgentRun {
  return structuredClone(mockAgentRun);
}
