import { Braces, Database, Wrench } from "lucide-react";
import type {
  AgentNode,
  AgentToolCall,
  AgentTraceEvent,
  AgentVectorMatch
} from "@/lib/types/agent";
import { JsonViewer } from "./json-viewer";
import { StatusPill } from "./status-pill";

interface InspectorPanelProps {
  node?: AgentNode;
  event?: AgentTraceEvent;
  toolCalls: AgentToolCall[];
  vectorMatches: AgentVectorMatch[];
  requestJson: Record<string, unknown>;
  responseJson: Record<string, unknown>;
}

export function InspectorPanel({
  node,
  event,
  toolCalls,
  vectorMatches,
  requestJson,
  responseJson
}: InspectorPanelProps) {
  const relatedTools = node
    ? toolCalls.filter((toolCall) => toolCall.nodeId === node.id)
    : toolCalls;
  const relatedMatches = node
    ? vectorMatches.filter((match) => match.nodeId === node.id)
    : vectorMatches;

  return (
    <aside className="inspector">
      <section className="inspector-section">
        <div className="section-heading">
          <Braces aria-hidden="true" size={16} />
          <span>当前节点</span>
        </div>
        {node ? (
          <div className="node-detail">
            <div>
              <strong>{node.label}</strong>
              <StatusPill status={node.status} />
            </div>
            <p>{node.stateSummary}</p>
            <small>{node.durationMs ?? 0} 毫秒</small>
          </div>
        ) : (
          <p className="empty-state">还没有选择节点。</p>
        )}
      </section>

      <section className="inspector-section">
        <div className="section-heading">
          <Wrench aria-hidden="true" size={16} />
          <span>工具调用</span>
        </div>
        {relatedTools.length ? (
          relatedTools.map((toolCall) => (
            <article className="detail-card" key={toolCall.id}>
              <strong>{toolCall.name}</strong>
              <p>{toolCall.resultPreview}</p>
              <small>{toolCall.durationMs} 毫秒</small>
            </article>
          ))
        ) : (
          <p className="empty-state">这个节点没有工具调用。</p>
        )}
      </section>

      <section className="inspector-section">
        <div className="section-heading">
          <Database aria-hidden="true" size={16} />
          <span>向量库命中</span>
        </div>
        {relatedMatches.length ? (
          relatedMatches.map((match) => (
            <article className="detail-card" key={match.id}>
              <strong>{match.title}</strong>
              <p>{match.contentPreview}</p>
              <small>
                {match.provider} · {match.collection} ·{" "}
                {typeof match.score === "number" ? match.score.toFixed(2) : "无分数"}
              </small>
            </article>
          ))
        ) : (
          <p className="empty-state">这个节点没有向量检索结果。</p>
        )}
      </section>

      <JsonViewer label="事件详情 JSON" value={event?.payload ?? {}} />
      <JsonViewer label="请求 JSON" value={requestJson} />
      <JsonViewer label="响应 JSON" value={responseJson} />
    </aside>
  );
}
