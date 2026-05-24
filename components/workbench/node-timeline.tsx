import type { AgentNode } from "@/lib/types/agent";
import { StatusPill } from "./status-pill";

interface NodeTimelineProps {
  nodes: AgentNode[];
  selectedNodeId: string;
  onSelectNode: (nodeId: string) => void;
}

export function NodeTimeline({
  nodes,
  selectedNodeId,
  onSelectNode
}: NodeTimelineProps) {
  return (
    <section className="node-timeline" aria-label="LangGraph 节点">
      {nodes.map((node) => (
        <button
          className={node.id === selectedNodeId ? "node-step active" : "node-step"}
          key={node.id}
          type="button"
          onClick={() => onSelectNode(node.id)}
        >
          <span className="node-id">{node.id}</span>
          <span>{node.label}</span>
          <StatusPill status={node.status} />
        </button>
      ))}
    </section>
  );
}
