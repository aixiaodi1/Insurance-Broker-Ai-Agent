"use client";

import { useState } from "react";
import { AlertTriangle } from "lucide-react";
import { createAgentRun } from "@/lib/api/agent-client";
import type { AgentApiMode, AgentRun, AgentTraceEvent } from "@/lib/types/agent";
import { InspectorPanel } from "./inspector-panel";
import { LeftRail } from "./left-rail";
import { NodeTimeline } from "./node-timeline";
import { PromptComposer } from "./prompt-composer";
import { TraceTimeline } from "./trace-timeline";

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
          vectorProvider: "qdrant",
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
          <p>{run.finalAnswer}</p>
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
