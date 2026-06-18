export type AgentApiMode = "mock" | "real";

export type AgentRunStatus = "idle" | "running" | "succeeded" | "failed" | "interrupted" | "awaiting_approval";

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

export interface CitationInfo {
  title: string;
  sectionTitle: string;
  sourceFile: string;
  contentType: string;
}

export interface AgentApprovalRequest {
  id: string;
  type: "command";
  command: string;
  normalizedCommand: string;
  mode: "plan" | "build";
  risk: string;
  reason: string;
}

export type AgentStreamEventType =
  | "run_started"
  | "goal_anchored"
  | "plan_updated"
  | "action_started"
  | "action_completed"
  | "recovery_started"
  | "guidance_queued"
  | "guidance_applied"
  | "interrupt_requested"
  | "run_interrupted"
  | "context_loaded"
  | "intent_anchor"
  | "task_decomposition"
  | "thinking"
  | "react_decision"
  | "tool_started"
  | "tool_finished"
  | "observation"
  | "approval_required"
  | "workflow_started"
  | "workflow_finished"
  | "final_answer"
  | "run_finished"
  | "error";

export interface AgentStreamEvent {
  type: AgentStreamEventType;
  timestamp?: string;
  summary?: string;
  runId?: string;
  run?: AgentRun;
  finalAnswer?: string;
  approvalRequest?: AgentApprovalRequest;
  context?: Record<string, unknown>;
  intent?: Record<string, unknown>;
  taskDecomposition?: Record<string, unknown>;
  observation?: Record<string, unknown>;
  step?: Record<string, unknown>;
  toolCall?: AgentToolCall;
  workflow?: Record<string, unknown>;
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
  citations?: Record<string, CitationInfo>;
  approvalRequest?: AgentApprovalRequest;
}

export interface AgentSession {
  id: string;
  threadId: string;
  title: string;
  status: AgentRunStatus;
  createdAt: string;
  updatedAt: string;
  runs: AgentRun[];
  activeRunId?: string;
  pinned?: boolean;
  archived?: boolean;
}

export interface CreateAgentRunInput {
  prompt: string;
  agentId: string;
  threadId?: string;
  vectorProvider: "tencent-vectordb" | "chroma";
  collectedVars?: Record<string, unknown>;
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
