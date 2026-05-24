import type { AgentNodeStatus, AgentRunStatus } from "@/lib/types/agent";

type Status = AgentNodeStatus | AgentRunStatus;

const statusLabels: Record<Status, string> = {
  idle: "空闲",
  pending: "等待中",
  running: "运行中",
  succeeded: "成功",
  failed: "失败"
};

export function StatusPill({ status }: { status: Status }) {
  return <span className={`status-pill status-${status}`}>{statusLabels[status]}</span>;
}
