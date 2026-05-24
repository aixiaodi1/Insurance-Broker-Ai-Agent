import type { AgentTraceEvent } from "@/lib/types/agent";

interface TraceTimelineProps {
  events: AgentTraceEvent[];
  selectedEventId?: string;
  onSelectEvent: (event: AgentTraceEvent) => void;
}

export function TraceTimeline({
  events,
  selectedEventId,
  onSelectEvent
}: TraceTimelineProps) {
  const eventTypeLabels: Record<AgentTraceEvent["type"], string> = {
    node_start: "节点开始",
    node_end: "节点结束",
    state_update: "状态更新",
    tool_call: "工具调用",
    retrieval: "向量检索",
    token_stream: "生成中",
    final_answer: "最终回答"
  };

  return (
    <section className="trace-panel">
      <div className="panel-title">运行轨迹</div>
      <div className="event-list">
        {events.map((event) => (
          <button
            className={event.id === selectedEventId ? "event-row active" : "event-row"}
            key={event.id}
            type="button"
            onClick={() => onSelectEvent(event)}
          >
            <span>{eventTypeLabels[event.type]}</span>
            <strong>{event.title}</strong>
            <small>{event.detail}</small>
          </button>
        ))}
      </div>
    </section>
  );
}
