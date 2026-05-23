import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { getInitialMockRun } from "@/lib/mock/agent-runs";
import { AgentWorkbench } from "./workbench";

describe("AgentWorkbench", () => {
  it("renders the trace workbench with Chinese interface labels", () => {
    render(<AgentWorkbench initialRun={getInitialMockRun()} />);

    expect(
      screen.getByRole("heading", { name: "LangGraph 轨迹调试台" })
    ).toBeInTheDocument();
    expect(screen.getByLabelText("调试指令")).toBeInTheDocument();
    expect(screen.getAllByText("检索上下文").length).toBeGreaterThan(0);
    expect(screen.getByText("LangGraph 路由策略")).toBeInTheDocument();
    expect(
      screen.getByText(/这次 Agent 先进入 retrieve_context/)
    ).toBeInTheDocument();
    expect(screen.queryByText("Prompt")).not.toBeInTheDocument();
    expect(screen.queryByText("Final Answer")).not.toBeInTheDocument();
  });

  it("does not crash when a vector match has no score", () => {
    const run = getInitialMockRun();
    run.vectorMatches = run.vectorMatches.map((match) => {
      const looseMatch = { ...match } as Record<string, unknown>;
      delete looseMatch.score;
      return looseMatch as (typeof run.vectorMatches)[number];
    });

    render(<AgentWorkbench initialRun={run} />);

    expect(screen.getByRole("heading", { name: /LangGraph/ })).toBeInTheDocument();
  });
});
