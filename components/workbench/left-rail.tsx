import { Database, History, ServerCog } from "lucide-react";
import type { AgentApiMode, AgentRun } from "@/lib/types/agent";
import { StatusPill } from "./status-pill";

interface LeftRailProps {
  apiMode: AgentApiMode;
  run: AgentRun;
  onModeChange: (mode: AgentApiMode) => void;
}

export function LeftRail({ apiMode, run, onModeChange }: LeftRailProps) {
  return (
    <aside className="left-rail">
      <div>
        <p className="eyebrow">Agent 调试</p>
        <h1>LangGraph 轨迹调试台</h1>
      </div>

      <section className="rail-section">
        <div className="section-heading">
          <ServerCog aria-hidden="true" size={16} />
          <span>API 模式</span>
        </div>
        <div className="segmented" aria-label="API 模式">
          <button
            className={apiMode === "mock" ? "active" : ""}
            type="button"
            onClick={() => onModeChange("mock")}
          >
            模拟数据
          </button>
          <button
            className={apiMode === "real" ? "active" : ""}
            type="button"
            onClick={() => onModeChange("real")}
          >
            FastAPI 后端
          </button>
        </div>
      </section>

      <section className="rail-section">
        <div className="section-heading">
          <Database aria-hidden="true" size={16} />
          <span>智能体配置</span>
        </div>
        <dl className="meta-list">
          <div>
            <dt>智能体</dt>
            <dd>{String(run.requestJson.agentId ?? "research-agent")}</dd>
          </div>
          <div>
            <dt>向量库</dt>
            <dd>{String(run.requestJson.vectorProvider ?? "qdrant")}</dd>
          </div>
          <div>
            <dt>状态</dt>
            <dd>
              <StatusPill status={run.status} />
            </dd>
          </div>
        </dl>
      </section>

      <section className="rail-section rail-grow">
        <div className="section-heading">
          <History aria-hidden="true" size={16} />
          <span>最近运行</span>
        </div>
        <button className="run-card active" type="button">
          <span>{run.id}</span>
          <small>{run.latencyMs ?? 0} 毫秒</small>
        </button>
      </section>
    </aside>
  );
}
