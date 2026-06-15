import { BookOpen, Clock3, PanelRightClose, PanelRightOpen } from "lucide-react";
import type { AgentRun } from "@/lib/types/agent";

interface InspectorPanelProps {
  isOpen: boolean;
  run?: AgentRun;
  onToggle: () => void;
}

function formatLatency(run?: AgentRun): string {
  if (!run || typeof run.latencyMs !== "number") {
    return "暂无记录";
  }

  return `${run.latencyMs} 毫秒`;
}

export function InspectorPanel({ isOpen, run, onToggle }: InspectorPanelProps) {
  const matches = run?.vectorMatches ?? [];

  return (
    <aside className={isOpen ? "right-panel expanded" : "right-panel collapsed"} data-testid="right-panel">
      <button
        className="panel-toggle"
        type="button"
        onClick={onToggle}
        aria-label={isOpen ? "收起侧栏" : "展开侧栏"}
      >
        {isOpen ? <PanelRightClose aria-hidden="true" size={18} /> : <PanelRightOpen aria-hidden="true" size={18} />}
        {isOpen ? <span>收起侧栏</span> : null}
      </button>

      {isOpen ? (
        <div className="right-panel-content">
          <header className="right-panel-header">
            <h2>资料侧栏</h2>
            <p>这里保留对当前回答有用的内容。</p>
          </header>

          <section className="side-section">
            <div className="section-heading">
              <BookOpen aria-hidden="true" size={16} />
              <span>参考资料</span>
            </div>
            {matches.length ? (
              <div className="source-list">
                {matches.map((match, index) => (
                  <article className="source-item" key={match.id}>
                    <strong>资料{index + 1}</strong>
                    <p>{match.contentPreview}</p>
                  </article>
                ))}
              </div>
            ) : (
              <p className="empty-state">暂无参考资料。</p>
            )}
          </section>

          <section className="side-section">
            <div className="section-heading">
              <Clock3 aria-hidden="true" size={16} />
              <span>本轮用时</span>
            </div>
            <p className="side-metric">{formatLatency(run)}</p>
          </section>
        </div>
      ) : null}
    </aside>
  );
}
