"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { createAgentRun } from "@/lib/api/agent-client";
import type { AgentApiMode, AgentRun, AgentTraceEvent, CitationInfo } from "@/lib/types/agent";
import { InspectorPanel } from "./inspector-panel";
import { LeftRail } from "./left-rail";
import { NodeTimeline } from "./node-timeline";
import { PromptComposer } from "./prompt-composer";
import { TraceTimeline } from "./trace-timeline";

function CitationLink({ idx, info }: { idx: string; info: CitationInfo }) {
  const [show, setShow] = useState(false);
  return (
    <span
      className="citation-marker"
      onClick={() => setShow(!show)}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
      style={{ cursor: "pointer", color: "var(--color-accent, #2563eb)", fontWeight: 600 }}
    >
      [{idx}]
      {show ? (
        <span
          className="citation-tooltip"
          style={{
            position: "absolute",
            background: "var(--color-surface, #1e293b)",
            color: "var(--color-text, #e2e8f0)",
            padding: "6px 10px",
            borderRadius: 6,
            fontSize: 13,
            whiteSpace: "nowrap",
            zIndex: 100,
            boxShadow: "0 2px 8px rgba(0,0,0,0.3)",
            transform: "translateY(-100%)",
          }}
        >
          {info.sectionTitle || info.title}
          {info.sourceFile ? ` — ${info.sourceFile}` : ""}
        </span>
      ) : null}
    </span>
  );
}

function renderAnswer(text: string, citations?: Record<string, CitationInfo>): React.ReactNode {
  if (!citations) {
    return <p>{text}</p>;
  }
  const parts = text.split(/(\[\d+\])/g);
  return (
    <p>
      {parts.map((part, i) => {
        const match = part.match(/^\[(\d+)\]$/);
        if (match && citations[match[1]]) {
          return <CitationLink key={i} idx={match[1]} info={citations[match[1]]} />;
        }
        return <span key={i}>{part}</span>;
      })}
    </p>
  );
}

interface AgentWorkbenchProps {
  initialRun: AgentRun;
}

export function AgentWorkbench({ initialRun }: AgentWorkbenchProps) {
  const initialSelectedNodeId =
    initialRun.vectorMatches[0]?.nodeId ?? initialRun.nodes[0]?.id ?? "";
  const [apiMode, setApiMode] = useState<AgentApiMode>(
    process.env.NEXT_PUBLIC_AGENT_API_MODE === "real" ? "real" : "mock"
  );
  const [run, setRun] = useState(initialRun);
  const [prompt, setPrompt] = useState(initialRun.prompt);
  const [selectedNodeId, setSelectedNodeId] = useState(initialSelectedNodeId);
  const [selectedEventId, setSelectedEventId] = useState<string | undefined>(
    initialRun.events[0]?.id
  );
  const [isRunning, setIsRunning] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | undefined>();

  const selectedNode =
    run.nodes.find((node) => node.id === selectedNodeId) ?? run.nodes[0];
  const selectedEvent =
    run.events.find((event) => event.id === selectedEventId) ?? run.events[0];

  async function handleRun() {
    const trimmedPrompt = prompt.trim();

    if (!trimmedPrompt) {
      return;
    }

    setIsRunning(true);
    setErrorMessage(undefined);

    try {
      const nextRun = await createAgentRun(
        {
          prompt: trimmedPrompt,
          agentId: "research-agent",
          threadId: String(run.requestJson.threadId ?? "thread_debug"),
          vectorProvider: "chroma",
          debug: true
        },
        { mode: apiMode }
      );

      setRun(nextRun);
      setSelectedNodeId(
        nextRun.vectorMatches[0]?.nodeId ?? nextRun.nodes[0]?.id ?? ""
      );
      setSelectedEventId(nextRun.events[0]?.id);
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "Agent 运行请求失败"
      );
    } finally {
      setIsRunning(false);
    }
  }

  function handleSelectEvent(event: AgentTraceEvent) {
    setSelectedEventId(event.id);
    setSelectedNodeId(event.nodeId);
  }

  return (
    <main className="workbench-shell">
      <LeftRail apiMode={apiMode} run={run} onModeChange={setApiMode} />

      <section className="workbench-main">
        <PromptComposer
          apiMode={apiMode}
          isRunning={isRunning}
          prompt={prompt}
          onPromptChange={setPrompt}
          onRun={handleRun}
        />

        {errorMessage ? (
          <div className="error-banner" role="alert">
            <AlertTriangle aria-hidden="true" size={18} />
            {errorMessage}
          </div>
        ) : null}

        <NodeTimeline
          nodes={run.nodes}
          selectedNodeId={selectedNode?.id ?? ""}
          onSelectNode={setSelectedNodeId}
        />

        <TraceTimeline
          events={run.events}
          selectedEventId={selectedEvent?.id}
          onSelectEvent={handleSelectEvent}
        />

        <section className="answer-panel">
          <div className="panel-title">最终回答</div>
          {renderAnswer(run.finalAnswer, run.citations)}
        </section>
      </section>

      <InspectorPanel
        event={selectedEvent}
        node={selectedNode}
        requestJson={run.requestJson}
        responseJson={run.responseJson}
        toolCalls={run.toolCalls}
        vectorMatches={run.vectorMatches}
      />
    </main>
  );
}
