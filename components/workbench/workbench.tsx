"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle } from "lucide-react";
import {
  deleteRunGuidance,
  interruptAgentRun,
  streamAgentRun,
  upsertRunGuidance
} from "@/lib/api/agent-client";
import type { AgentApprovalRequest, AgentRun, AgentSession, AgentStreamEvent, CitationInfo } from "@/lib/types/agent";
import {
  appendRunToSession,
  createAgentSession,
  getActiveRun,
  loadSessionsFromStorage,
  saveSessionsToStorage,
  sessionFromRun
} from "@/lib/workbench/sessions";
import { InspectorPanel } from "./inspector-panel";
import { LeftRail } from "./left-rail";
import { PromptComposer } from "./prompt-composer";

function CitationLink({ idx, info }: { idx: string; info: CitationInfo }) {
  const [show, setShow] = useState(false);

  return (
    <span
      className="citation-marker"
      onClick={() => setShow(!show)}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      [{idx}]
      {show ? <span className="citation-tooltip">{info.sectionTitle || info.title}</span> : null}
    </span>
  );
}

function renderAnswer(text: string, citations?: Record<string, CitationInfo>): React.ReactNode {
  if (!citations) {
    return <div className="answer-block">{text}</div>;
  }

  const parts = text.split(/(\[\d+\])/g);

  return (
    <div className="answer-block">
      {parts.map((part, index) => {
        const match = part.match(/^\[(\d+)\]$/);
        if (match && citations[match[1]]) {
          return <CitationLink key={index} idx={match[1]} info={citations[match[1]]} />;
        }

        return <span key={index}>{part}</span>;
      })}
    </div>
  );
}

function formatLatency(run: AgentRun): string {
  if (typeof run.latencyMs !== "number") {
    return "未记录";
  }

  return `${run.latencyMs} 毫秒`;
}

function streamEvents(run: AgentRun): AgentStreamEvent[] {
  const events = run.responseJson.streamEvents;
  return Array.isArray(events) ? (events as AgentStreamEvent[]) : [];
}

function createRunningRun(prompt: string, threadId: string): AgentRun {
  const now = new Date().toISOString();
  return {
    id: `run_pending_${Date.now()}`,
    mode: "real",
    prompt,
    status: "running",
    startedAt: now,
    nodes: [],
    events: [],
    toolCalls: [],
    vectorMatches: [],
    requestJson: { prompt, threadId },
    responseJson: { streamEvents: [] },
    finalAnswer: ""
  };
}

function replaceRun(session: AgentSession, previousRunId: string, run: AgentRun): AgentSession {
  return {
    ...session,
    status: run.status,
    updatedAt: run.finishedAt ?? new Date().toISOString(),
    runs: session.runs.map((item) => (item.id === previousRunId ? run : item)),
    activeRunId: run.id
  };
}

function updateRunEvents(session: AgentSession, runId: string, event: AgentStreamEvent): AgentSession {
  return {
    ...session,
    status: "running",
    runs: session.runs.map((run) => {
      if (run.id !== runId) {
        return run;
      }
      const events = [...streamEvents(run), event];
      return {
        ...run,
        status: "running",
        responseJson: { ...run.responseJson, streamEvents: events },
        finalAnswer: event.finalAnswer ?? run.finalAnswer
      };
    }),
    activeRunId: runId
  };
}

function AgentProcessBlock({ run }: { run: AgentRun }) {
  const events = streamEvents(run);
  if (!events.length && run.status !== "running") {
    return null;
  }
  const latest = events[events.length - 1];
  const latestSummary = eventSummary(latest) ?? "Analyzing request...";
  const label = run.status === "running" ? "正在处理" : `已处理 ${formatLatency(run)}`;

  return (
    <details className="agent-process-block" data-testid="agent-process-block" open={run.status === "running"}>
      <summary>
        <span className="process-pulse" aria-hidden="true" />
        <span>{label}</span>
        <span>{latestSummary}</span>
      </summary>
      <ol>
        {events.map((event, index) => (
          <li key={`${event.type}-${index}`}>
            <strong>{eventLabel(event)}</strong>
            <span>{eventSummary(event) ?? ""}</span>
          </li>
        ))}
      </ol>
    </details>
  );
}

function eventSummary(event?: AgentStreamEvent): string | undefined {
  if (!event) {
    return undefined;
  }
  if (event.type === "intent_anchor") {
    return asDisplayString(event.intent?.["user_goal"] ?? event.summary);
  }
  if (event.type === "goal_anchored") {
    const goal = (event as AgentStreamEvent & { goal?: Record<string, unknown> }).goal;
    return asDisplayString(goal?.["goal"] ?? event.summary);
  }
  if (event.type === "plan_updated") {
    return event.summary ?? "已更新计划";
  }
  if (event.type === "task_decomposition") {
    const tasks = event.taskDecomposition?.["ordered_tasks"];
    if (Array.isArray(tasks)) {
      return `${tasks.length} steps planned`;
    }
  }
  if (event.type === "observation") {
    return asDisplayString(event.observation?.["resultPreview"] ?? event.summary);
  }
  if (event.type === "final_answer") {
    return "已生成回答";
  }
  if (event.type === "run_finished") {
    return "本轮完成";
  }
  return event.summary;
}

function asDisplayString(value: unknown): string | undefined {
  if (typeof value === "string") {
    return value;
  }
  if (value === undefined || value === null) {
    return undefined;
  }
  return String(value);
}

function eventLabel(event: AgentStreamEvent): string {
  const labels: Record<AgentStreamEvent["type"], string> = {
    run_started: "开始",
    goal_anchored: "目标",
    plan_updated: "计划",
    action_started: "行动",
    action_completed: "结果",
    recovery_started: "恢复",
    guidance_queued: "补充",
    guidance_applied: "已纠偏",
    interrupt_requested: "停止",
    run_interrupted: "已终止",
    context_loaded: "上下文",
    intent_anchor: "意图",
    task_decomposition: "拆解",
    thinking: "分析",
    react_decision: "决策",
    tool_started: "工具",
    tool_finished: "结果",
    observation: "观察",
    approval_required: "确认",
    workflow_started: "流程",
    workflow_finished: "完成",
    final_answer: "回答",
    run_finished: "结束",
    error: "错误"
  };
  return labels[event.type] ?? event.type;
}

interface AgentWorkbenchProps {
  initialRun: AgentRun;
}

export function AgentWorkbench({ initialRun }: AgentWorkbenchProps) {
  const initialSession = useMemo(() => sessionFromRun(initialRun), [initialRun]);
  const [sessions, setSessions] = useState<AgentSession[]>([initialSession]);
  const [activeSessionId, setActiveSessionId] = useState(initialSession.id);
  const [prompt, setPrompt] = useState("");
  const [commandMode, setCommandMode] = useState<"plan" | "build">("plan");
  const [isRunning, setIsRunning] = useState(false);
  const [isStopping, setIsStopping] = useState(false);
  const [activeBackendRunId, setActiveBackendRunId] = useState<string | undefined>();
  const [queuedGuidance, setQueuedGuidance] = useState<string | undefined>();
  const [hasLoadedSessions, setHasLoadedSessions] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | undefined>();
  const [isRightPanelOpen, setIsRightPanelOpen] = useState(false);
  const [pendingApproval, setPendingApproval] = useState<
    { run: AgentRun; request: AgentApprovalRequest; sessionId: string; threadId: string } | undefined
  >();
  const chatHistoryRef = useRef<HTMLElement | null>(null);

  const visibleSessions = useMemo(
    () =>
      sessions
        .filter((session) => !session.archived)
        .sort((left, right) => Number(Boolean(right.pinned)) - Number(Boolean(left.pinned))),
    [sessions]
  );

  useEffect(() => {
    let isMounted = true;

    queueMicrotask(() => {
      if (!isMounted) {
        return;
      }

      const stored = loadSessionsFromStorage(window.localStorage);
      if (stored.length) {
        setSessions(stored);
        setActiveSessionId(stored[0].id);
      }
      setHasLoadedSessions(true);
    });

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (!hasLoadedSessions) {
      return;
    }

    saveSessionsToStorage(window.localStorage, sessions);
  }, [hasLoadedSessions, sessions]);

  useEffect(() => {
    if (!chatHistoryRef.current) {
      return;
    }
    if (typeof chatHistoryRef.current.scrollTo === "function") {
      chatHistoryRef.current.scrollTo({
        top: chatHistoryRef.current.scrollHeight,
        behavior: "smooth"
      });
      return;
    }
    chatHistoryRef.current.scrollTop = chatHistoryRef.current.scrollHeight;
  }, [sessions, activeSessionId]);

  const activeSession =
    visibleSessions.find((session) => session.id === activeSessionId) ??
    visibleSessions[0] ??
    initialSession;
  const activeRun = getActiveRun(activeSession);
  const hasConversation = activeSession.runs.length > 0;

  async function handleRun() {
    const trimmedPrompt = prompt.trim();

    if (!trimmedPrompt) {
      return;
    }

    setIsRunning(true);
    setErrorMessage(undefined);
    setPendingApproval(undefined);
    setPrompt("");
    const pendingRun = createRunningRun(trimmedPrompt, activeSession.threadId);
    setSessions((current) =>
      current.map((session) =>
        session.id === activeSession.id ? appendRunToSession(session, pendingRun) : session
      )
    );

    try {
      const nextRun = await streamAgentRun(
        {
          prompt: trimmedPrompt,
          agentId: "research-agent",
          threadId: activeSession.threadId,
          vectorProvider: "chroma",
          collectedVars: { commandMode }
        },
        {
          mode: "real",
          onEvent: (event) => {
            if (event.runId) {
              setActiveBackendRunId(event.runId);
            }
            if (event.type === "guidance_applied") {
              setQueuedGuidance(undefined);
            }
            setSessions((current) =>
              current.map((session) =>
                session.id === activeSession.id ? updateRunEvents(session, pendingRun.id, event) : session
              )
            );
          }
        }
      );

      setSessions((current) =>
        current.map((session) =>
          session.id === activeSession.id ? replaceRun(session, pendingRun.id, nextRun) : session
        )
      );
      if (nextRun.approvalRequest) {
        setPendingApproval({
          run: nextRun,
          request: nextRun.approvalRequest,
          sessionId: activeSession.id,
          threadId: activeSession.threadId
        });
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "请求失败");
    } finally {
      setIsRunning(false);
      setIsStopping(false);
      setActiveBackendRunId(undefined);
    }
  }

  async function handleQueueGuidance() {
    const content = prompt.trim();
    if (!content || !activeBackendRunId) {
      return;
    }
    await upsertRunGuidance(activeBackendRunId, content, "normal");
    setQueuedGuidance(content);
    setPrompt("");
  }

  async function handleImmediateGuidance() {
    const content = queuedGuidance?.trim();
    if (!content || !activeBackendRunId) {
      return;
    }
    await upsertRunGuidance(activeBackendRunId, content, "immediate");
  }

  async function handleGuidanceBlur() {
    const content = queuedGuidance?.trim();
    if (content && activeBackendRunId) {
      await upsertRunGuidance(activeBackendRunId, content, "normal");
    }
  }

  async function handleDeleteGuidance() {
    if (!activeBackendRunId) {
      return;
    }
    await deleteRunGuidance(activeBackendRunId);
    setQueuedGuidance(undefined);
  }

  async function handleStop() {
    if (!activeBackendRunId || isStopping) {
      return;
    }
    setIsStopping(true);
    await interruptAgentRun(activeBackendRunId);
  }

  async function handleApproveCommand() {
    if (!pendingApproval || isRunning) {
      return;
    }

    const { request, run, sessionId, threadId } = pendingApproval;
    setIsRunning(true);
    setErrorMessage(undefined);

    try {
      const approvedRun = await streamAgentRun(
        {
          prompt: run.prompt,
          agentId: "research-agent",
          threadId,
          vectorProvider: "chroma",
          collectedVars: {
            approvalId: request.id,
            approvedCommand: request.command,
            commandApproved: true,
            commandMode: request.mode
          }
        },
        { mode: "real" }
      );

      setSessions((current) =>
        current.map((session) =>
          session.id === sessionId ? appendRunToSession(session, approvedRun) : session
        )
      );
      setPendingApproval(undefined);
      setActiveSessionId(sessionId);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "请求失败");
    } finally {
      setIsRunning(false);
    }
  }

  function handleRejectCommand() {
    setPendingApproval(undefined);
  }

  function handleNewSession() {
    const nextSession = createAgentSession("");
    setSessions((current) => [nextSession, ...current]);
    setActiveSessionId(nextSession.id);
    setPrompt("");
  }

  function handleSelectSession(sessionId: string) {
    setActiveSessionId(sessionId);
    setPrompt("");
  }

  function activateFallbackSession(nextSessions: AgentSession[], removedSessionId: string) {
    const nextVisible = nextSessions.filter(
      (session) => !session.archived && session.id !== removedSessionId
    );

    if (activeSessionId === removedSessionId) {
      setActiveSessionId(
        nextVisible[0]?.id ?? nextSessions.find((session) => !session.archived)?.id ?? initialSession.id
      );
    }
  }

  function handleRenameSession(sessionId: string) {
    const session = sessions.find((item) => item.id === sessionId);
    if (!session) {
      return;
    }

    const nextTitle = window.prompt("重命名会话", session.title)?.trim();
    if (!nextTitle) {
      return;
    }

    setSessions((current) =>
      current.map((item) =>
        item.id === sessionId ? { ...item, title: nextTitle, updatedAt: new Date().toISOString() } : item
      )
    );
  }

  function handlePinSession(sessionId: string) {
    setSessions((current) =>
      current.map((item) =>
        item.id === sessionId ? { ...item, pinned: true, updatedAt: new Date().toISOString() } : item
      )
    );
  }

  function handleArchiveSession(sessionId: string) {
    const nextSessions = sessions.map((item) =>
      item.id === sessionId ? { ...item, archived: true, updatedAt: new Date().toISOString() } : item
    );
    const hasVisible = nextSessions.some((session) => !session.archived);
    const finalSessions = hasVisible ? nextSessions : [createAgentSession(""), ...nextSessions];

    activateFallbackSession(finalSessions, sessionId);
    setSessions(finalSessions);
  }

  function handleDeleteSession(sessionId: string) {
    if (!window.confirm("删除这个会话？")) {
      return;
    }

    const nextSessions = sessions.filter((item) => item.id !== sessionId);
    const hasVisible = nextSessions.some((session) => !session.archived);
    const finalSessions = hasVisible ? nextSessions : [createAgentSession(""), ...nextSessions];

    activateFallbackSession(finalSessions, sessionId);
    setSessions(finalSessions);
  }

  return (
    <main className="workbench-shell">
      <LeftRail
        activeSessionId={activeSession.id}
        sessions={visibleSessions}
        onNewSession={handleNewSession}
        onArchiveSession={handleArchiveSession}
        onDeleteSession={handleDeleteSession}
        onPinSession={handlePinSession}
        onRenameSession={handleRenameSession}
        onSelectSession={handleSelectSession}
        onToggleRightPanel={() => setIsRightPanelOpen((current) => !current)}
      />

      <section
        className={hasConversation ? "workbench-main conversation-active" : "workbench-main conversation-empty"}
        data-testid="conversation-area"
      >
        {errorMessage ? (
          <div className="error-banner" role="alert">
            <AlertTriangle aria-hidden="true" size={18} />
            {errorMessage}
          </div>
        ) : null}

        {hasConversation ? (
          <section className="chat-history" aria-label="会话内容" ref={chatHistoryRef}>
            {activeSession.runs.map((item) => (
              <article
                className={item.id === activeRun?.id ? "chat-turn active" : "chat-turn"}
                data-testid="chat-turn"
                key={item.id}
              >
                <div className="chat-message user-message">
                  <div className="message-label">你</div>
                  <p>{item.prompt}</p>
                </div>
                <div className="chat-message assistant-message">
                  <div className="message-label">智能助理</div>
                  <AgentProcessBlock run={item} />
                  {item.finalAnswer ? renderAnswer(item.finalAnswer, item.citations) : null}
                  {item.status !== "running" ? <div className="run-footer">用时 {formatLatency(item)}</div> : null}
                </div>
              </article>
            ))}
          </section>
        ) : (
          <section className="empty-start" aria-label="空会话">
            <h2>今天需要我做什么？</h2>
            <p>输入命令或提出问题</p>
          </section>
        )}

        {isRunning && queuedGuidance !== undefined ? (
          <section className="queued-guidance" aria-label="待应用的补充">
            <div>
              <strong>待应用的补充</strong>
              <span>下一次 ReAct 决策前自动加入</span>
            </div>
            <textarea
              aria-label="编辑预提交内容"
              value={queuedGuidance}
              onBlur={handleGuidanceBlur}
              onChange={(event) => setQueuedGuidance(event.target.value)}
            />
            <div className="queued-guidance-actions">
              <button type="button" onClick={handleDeleteGuidance}>撤回</button>
              <button type="button" onClick={handleImmediateGuidance}>立即提交</button>
            </div>
          </section>
        ) : null}

        <PromptComposer
          commandMode={commandMode}
          isAnchored={hasConversation}
          isRunning={isRunning}
          prompt={prompt}
          onCommandModeChange={setCommandMode}
          onPromptChange={setPrompt}
          onRun={handleRun}
          onQueueGuidance={handleQueueGuidance}
          onStop={handleStop}
          isStopping={isStopping}
        />
      </section>

      {pendingApproval ? (
        <div className="approval-backdrop">
          <section
            aria-label="命令确认"
            aria-modal="true"
            className="approval-dialog"
            data-testid="command-approval-dialog"
            role="dialog"
          >
            <div className="approval-header">
              <AlertTriangle aria-hidden="true" size={20} />
              <h2>命令确认</h2>
            </div>
            <p>这个命令需要你确认后才会执行。</p>
            <code>{pendingApproval.request.command}</code>
            <dl>
              <div>
                <dt>模式</dt>
                <dd>{pendingApproval.request.mode === "build" ? "构建" : "计划"}</dd>
              </div>
              <div>
                <dt>风险</dt>
                <dd>{pendingApproval.request.risk}</dd>
              </div>
              <div>
                <dt>原因</dt>
                <dd>{pendingApproval.request.reason}</dd>
              </div>
            </dl>
            <div className="approval-actions">
              <button
                data-testid="reject-command"
                type="button"
                onClick={handleRejectCommand}
              >
                拒绝
              </button>
              <button
                data-testid="approve-command"
                disabled={isRunning}
                type="button"
                onClick={handleApproveCommand}
              >
                {isRunning ? "执行中" : "允许执行"}
              </button>
            </div>
          </section>
        </div>
      ) : null}

      <InspectorPanel
        isOpen={isRightPanelOpen}
        run={activeRun}
        onToggle={() => setIsRightPanelOpen((current) => !current)}
      />
    </main>
  );
}
