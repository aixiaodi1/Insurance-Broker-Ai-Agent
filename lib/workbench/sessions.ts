import type { AgentRun, AgentSession } from "@/lib/types/agent";

export const SESSION_STORAGE_KEY = "agent-workbench:sessions:v2";

interface CreateSessionOptions {
  now?: string;
  random?: () => string;
}

export function createThreadId(
  now: string = new Date().toISOString(),
  random: () => string = () => Math.random().toString(36).slice(2, 8)
): string {
  const stamp = now.replace(/\D/g, "").slice(0, 14);
  return `thread_${stamp}_${random()}`;
}

export function createTitleFromPrompt(prompt: string): string {
  const normalized = prompt.trim().replace(/\s+/g, " ");
  if (!normalized) {
    return "新会话";
  }
  if (normalized.length <= 28) {
    return normalized;
  }
  return `${normalized.slice(0, 28)}...`;
}

export function createAgentSession(
  prompt: string,
  options: CreateSessionOptions = {}
): AgentSession {
  const now = options.now ?? new Date().toISOString();
  const threadId = createThreadId(now, options.random);
  return {
    id: threadId,
    threadId,
    title: createTitleFromPrompt(prompt),
    status: "idle",
    createdAt: now,
    updatedAt: now,
    runs: []
  };
}

export function sessionFromRun(run: AgentRun): AgentSession {
  const now = run.startedAt ?? new Date().toISOString();
  const threadId = String(run.requestJson.threadId ?? createThreadId(now));
  return {
    id: threadId,
    threadId,
    title: createTitleFromPrompt(run.prompt),
    status: run.status,
    createdAt: now,
    updatedAt: run.finishedAt ?? now,
    runs: [run],
    activeRunId: run.id
  };
}

export function appendRunToSession(session: AgentSession, run: AgentRun): AgentSession {
  const existingIndex = session.runs.findIndex((item) => item.id === run.id);
  const runs =
    existingIndex >= 0
      ? session.runs.map((item) => (item.id === run.id ? run : item))
      : [...session.runs, run];

  return {
    ...session,
    title: session.title === "新会话" ? createTitleFromPrompt(run.prompt) : session.title,
    status: run.status,
    updatedAt: run.finishedAt ?? new Date().toISOString(),
    runs,
    activeRunId: run.id
  };
}

export function getActiveRun(session: AgentSession): AgentRun | undefined {
  return (
    session.runs.find((run) => run.id === session.activeRunId) ??
    session.runs[session.runs.length - 1]
  );
}

export function loadSessionsFromStorage(storage: Storage): AgentSession[] {
  const raw = storage.getItem(SESSION_STORAGE_KEY);
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter(isAgentSession);
  } catch {
    return [];
  }
}

export function saveSessionsToStorage(storage: Storage, sessions: AgentSession[]): void {
  storage.setItem(SESSION_STORAGE_KEY, JSON.stringify(sessions));
}

function isAgentSession(value: unknown): value is AgentSession {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return false;
  }
  const session = value as Partial<AgentSession>;
  return (
    typeof session.id === "string" &&
    typeof session.threadId === "string" &&
    typeof session.title === "string" &&
    Array.isArray(session.runs)
  );
}
