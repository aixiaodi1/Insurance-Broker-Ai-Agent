export type AgentApiMode = "mock" | "real";

export type AgentRunStatus = "idle" | "running" | "succeeded" | "failed";

export type AgentNodeStatus = "pending" | "running" | "succeeded" | "failed";

export type AgentTraceEventType =
  | "node_start"
  | "node_end"
  | "state_update"
  | "tool_call"
  | "retrieval"
  | "token_stream"
  | "final_answer";

export interface AgentNode {
  id: string;
  label: string;
  status: AgentNodeStatus;
  startedAt?: string;
  finishedAt?: string;
  durationMs?: number;
  stateSummary: string;
  error?: string;
}

export interface AgentTraceEvent {
  id: string;
  nodeId: string;
  type: AgentTraceEventType;
  timestamp: string;
  title: string;
  detail: string;
  payload: Record<string, unknown>;
}

export interface AgentToolCall {
  id: string;
  nodeId: string;
  name: string;
  status: AgentNodeStatus;
  arguments: Record<string, unknown>;
  durationMs: number;
  resultPreview: string;
}

export interface AgentVectorMatch {
  id: string;
  nodeId: string;
  provider: "tencent-vectordb" | "chroma";
  collection: string;
  score?: number;
  title: string;
  contentPreview: string;
  metadata: Record<string, unknown>;
}

export interface AgentTokenUsage {
  prompt: number;
  completion: number;
  total: number;
}

export interface AgentRun {
  id: string;
  mode: AgentApiMode;
  prompt: string;
  status: AgentRunStatus;
  startedAt?: string;
  finishedAt?: string;
  latencyMs?: number;
  tokens?: AgentTokenUsage;
  nodes: AgentNode[];
  events: AgentTraceEvent[];
  toolCalls: AgentToolCall[];
  vectorMatches: AgentVectorMatch[];
  requestJson: Record<string, unknown>;
  responseJson: Record<string, unknown>;
  finalAnswer: string;
}

export interface CreateAgentRunInput {
  prompt: string;
  agentId: string;
  threadId?: string;
  vectorProvider: "tencent-vectordb" | "chroma";
  debug: boolean;
}

export class AgentRunError extends Error {
  readonly statusCode?: number;
  readonly payload?: unknown;

  constructor(message: string, statusCode?: number, payload?: unknown) {
    super(message);
    this.name = "AgentRunError";
    this.statusCode = statusCode;
    this.payload = payload;
  }
}
