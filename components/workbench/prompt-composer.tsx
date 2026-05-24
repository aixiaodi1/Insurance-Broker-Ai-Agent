import { Play, SquareTerminal } from "lucide-react";
import type { AgentApiMode } from "@/lib/types/agent";

interface PromptComposerProps {
  prompt: string;
  apiMode: AgentApiMode;
  isRunning: boolean;
  onPromptChange: (prompt: string) => void;
  onRun: () => void;
}

export function PromptComposer({
  prompt,
  apiMode,
  isRunning,
  onPromptChange,
  onRun
}: PromptComposerProps) {
  const canRun = prompt.trim().length > 0 && !isRunning;

  return (
    <section className="prompt-composer">
      <div className="composer-topline">
        <label htmlFor="prompt">调试指令</label>
        <span>
          <SquareTerminal aria-hidden="true" size={15} />
          {apiMode === "mock" ? "模拟运行" : "FastAPI 运行"}
        </span>
      </div>
      <textarea
        id="prompt"
        value={prompt}
        onChange={(event) => onPromptChange(event.target.value)}
        rows={4}
      />
      <div className="composer-actions">
        <span>{prompt.trim() ? "可以运行" : "输入调试指令后再运行"}</span>
        <button type="button" onClick={onRun} disabled={!canRun}>
          <Play aria-hidden="true" size={16} />
          {isRunning ? "运行中" : "运行"}
        </button>
      </div>
    </section>
  );
}
