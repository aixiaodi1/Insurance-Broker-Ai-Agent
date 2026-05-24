import { AgentWorkbench } from "@/components/workbench/workbench";
import { getInitialMockRun } from "@/lib/mock/agent-runs";

export default function HomePage() {
  return <AgentWorkbench initialRun={getInitialMockRun()} />;
}
