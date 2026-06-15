import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getInitialMockRun } from "@/lib/mock/agent-runs";
import { AgentWorkbench } from "./workbench";
import * as agentClient from "@/lib/api/agent-client";

describe("AgentWorkbench", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a Chinese three-column chat workspace without debug controls", () => {
    const { container } = render(<AgentWorkbench initialRun={getInitialMockRun()} />);

    expect(screen.getByRole("heading", { name: "经纪人助手" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "新会话" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "查找会话" })).toBeInTheDocument();
    expect(screen.getByText("会话历史")).toBeInTheDocument();
    expect(screen.getByLabelText("输入消息")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "发送" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "添加附件" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "快捷指令" })).toBeInTheDocument();
    expect(screen.getByText("用时 2420 毫秒")).toBeInTheDocument();
    expect(screen.getByText("智能助理")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "展开侧栏" })).toBeInTheDocument();
    expect(screen.queryByText("调试")).not.toBeInTheDocument();
    expect(screen.queryByText("当前节点")).not.toBeInTheDocument();
    expect(screen.queryByText("工具调用")).not.toBeInTheDocument();
    expect(screen.queryByText("请求")).not.toBeInTheDocument();
    expect(screen.queryByText("响应")).not.toBeInTheDocument();
    expect(screen.queryByText("事件详情")).not.toBeInTheDocument();
    expect(container.textContent).not.toMatch(/[A-Za-z]/);
  });

  it("does not crash when a vector match has no score", () => {
    const run = getInitialMockRun();
    run.vectorMatches = run.vectorMatches.map((match) => {
      const looseMatch = { ...match } as Record<string, unknown>;
      delete looseMatch.score;
      return looseMatch as unknown as (typeof run.vectorMatches)[number];
    });

    render(<AgentWorkbench initialRun={run} />);

    expect(screen.getByRole("heading", { name: "经纪人助手" })).toBeInTheDocument();
  });

  it("shows sessions in the left rail and creates new threads", () => {
    render(<AgentWorkbench initialRun={getInitialMockRun()} />);

    expect(screen.getByRole("button", { name: /新会话/ })).toBeInTheDocument();
    expect(screen.getByText("会话历史")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /新会话/ }));

    expect(screen.getAllByTestId("session-row")).toHaveLength(2);
    expect(screen.getAllByText("新会话").length).toBeGreaterThan(0);
    expect(screen.getByText("今天需要我做什么？")).toBeInTheDocument();
    expect(screen.getByText("输入命令或提出问题")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "复制界面" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "导入设计" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "创建页面" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "优化内容" })).toBeInTheDocument();
    expect(screen.getByTestId("conversation-area")).toHaveClass("conversation-empty");
    expect(screen.getByTestId("composer-shell")).toHaveClass("composer-center");
  });

  it("keeps the composer at the bottom after conversation history exists", () => {
    render(<AgentWorkbench initialRun={getInitialMockRun()} />);

    expect(screen.getByTestId("conversation-area")).toHaveClass("conversation-active");
    expect(screen.getByTestId("composer-shell")).toHaveClass("composer-bottom");
  });

  it("expands and collapses the right side panel", () => {
    render(<AgentWorkbench initialRun={getInitialMockRun()} />);

    expect(screen.getByTestId("right-panel")).toHaveClass("collapsed");
    fireEvent.click(screen.getByRole("button", { name: "展开侧栏" }));

    expect(screen.getByTestId("right-panel")).toHaveClass("expanded");
    expect(screen.getByRole("button", { name: "收起侧栏" })).toBeInTheDocument();
    expect(screen.getByText("参考资料")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "收起侧栏" }));
    expect(screen.getByTestId("right-panel")).toHaveClass("collapsed");
  });

  it("opens session actions and renames a session", () => {
    vi.spyOn(window, "prompt").mockReturnValue("新的会话标题");

    render(<AgentWorkbench initialRun={getInitialMockRun()} />);

    const trigger = screen.getByRole("button", { name: /会话设置/ });
    vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({
      bottom: 148,
      height: 28,
      left: 214,
      right: 242,
      top: 120,
      width: 28,
      x: 214,
      y: 120,
      toJSON: () => ({})
    } as DOMRect);

    fireEvent.click(trigger);

    expect(screen.getByRole("menu")).toHaveStyle({ left: "110px", top: "154px" });
    expect(screen.getByRole("menuitem", { name: "重命名" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "置顶聊天" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "归档" })).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "删除" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("menuitem", { name: "重命名" }));

    expect(screen.getByText("新的会话标题")).toBeInTheDocument();
  });

  it("deletes a session from the left rail action menu", () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<AgentWorkbench initialRun={getInitialMockRun()} />);
    fireEvent.click(screen.getByRole("button", { name: /新会话/ }));

    expect(screen.getAllByTestId("session-row")).toHaveLength(2);

    fireEvent.click(screen.getAllByRole("button", { name: /会话设置/ })[0]);
    fireEvent.click(screen.getByRole("menuitem", { name: "删除" }));

    expect(screen.getAllByTestId("session-row")).toHaveLength(1);
  });

  it("reuses the active session thread id across sends", async () => {
    const spy = vi.spyOn(agentClient, "streamAgentRun");
    const first = getInitialMockRun();
    const second = getInitialMockRun();
    second.id = "run_mock_second";
    spy.mockResolvedValueOnce(first).mockResolvedValueOnce(second);

    render(<AgentWorkbench initialRun={getInitialMockRun()} />);

    const textbox = screen.getByLabelText("输入消息");
    fireEvent.change(textbox, { target: { value: "第一轮问题" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(1));

    const firstThreadId = spy.mock.calls[0][0].threadId;
    fireEvent.change(textbox, { target: { value: "继续追问" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));

    expect(spy.mock.calls[1][0].threadId).toBe(firstThreadId);
    expect(spy.mock.calls[0][0]).not.toHaveProperty("debug");
    expect(spy.mock.calls[1][0]).not.toHaveProperty("debug");
    expect(spy.mock.calls[0][1]).toMatchObject({ mode: "real" });
    expect(spy.mock.calls[1][1]).toMatchObject({ mode: "real" });
  });

  it("clears the composer and appends each submitted answer to the conversation", async () => {
    const spy = vi.spyOn(agentClient, "streamAgentRun");
    const run = getInitialMockRun();
    run.id = "run_mock_follow_up";
    run.prompt = "继续追问";
    run.finalAnswer = "这是第二轮回答。";
    run.latencyMs = 1234;
    spy.mockResolvedValueOnce(run);

    render(<AgentWorkbench initialRun={getInitialMockRun()} />);

    const textbox = screen.getByLabelText("输入消息") as HTMLTextAreaElement;
    fireEvent.change(textbox, { target: { value: "继续追问" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => expect(textbox.value).toBe(""));
    expect(screen.getByText("继续追问")).toBeInTheDocument();
    expect(screen.getByText("这是第二轮回答。")).toBeInTheDocument();
    expect(screen.getByText("用时 1234 毫秒")).toBeInTheDocument();

    const turns = screen.getAllByTestId("chat-turn");
    expect(turns[0]).toHaveTextContent("帮我检查智能助理为什么先检索再调用工具。");
    expect(turns[1]).toHaveTextContent("继续追问");
  });

  it("shows the submitted prompt and running process before the stream finishes", async () => {
    let resolveRun: ((run: ReturnType<typeof getInitialMockRun>) => void) | undefined;
    const spy = vi.spyOn(agentClient, "streamAgentRun").mockImplementation(async (_input, options) => {
      options.onEvent?.({ type: "run_started", summary: "正在分析请求。", timestamp: new Date().toISOString() });
      return await new Promise((resolve) => {
        resolveRun = resolve;
      });
    });

    render(<AgentWorkbench initialRun={getInitialMockRun()} />);

    const textbox = screen.getByLabelText("输入消息") as HTMLTextAreaElement;
    fireEvent.change(textbox, { target: { value: "streaming question" } });
    fireEvent.keyDown(textbox, { key: "Enter" });

    expect(textbox.value).toBe("");
    expect(await screen.findByText("streaming question")).toBeInTheDocument();
    expect(await screen.findByTestId("agent-process-block")).toBeInTheDocument();
    expect(screen.getAllByText("正在分析请求。").length).toBeGreaterThan(0);
    expect(spy).toHaveBeenCalledTimes(1);

    const run = getInitialMockRun();
    run.id = "run_stream_done";
    run.prompt = "streaming question";
    run.finalAnswer = "stream done";
    resolveRun?.(run);

    expect(await screen.findByText("stream done")).toBeInTheDocument();
  });

  it("does not repeat the final answer in the process summary", () => {
    const run = getInitialMockRun();
    run.finalAnswer = "unique final answer";
    run.responseJson = {
      ...run.responseJson,
      streamEvents: [
        {
          type: "final_answer",
          summary: "unique final answer",
          finalAnswer: "unique final answer",
          timestamp: new Date().toISOString()
        }
      ]
    };

    render(<AgentWorkbench initialRun={run} />);

    expect(screen.getAllByText("unique final answer")).toHaveLength(1);
  });

  it("renders process status in user-facing language", () => {
    const run = getInitialMockRun();
    run.finalAnswer = "done";
    run.responseJson = {
      ...run.responseJson,
      streamEvents: [
        {
          type: "final_answer",
          summary: "Final answer generated.",
          finalAnswer: "done",
          timestamp: new Date().toISOString()
        }
      ]
    };

    render(<AgentWorkbench initialRun={run} />);

    expect(screen.queryByText("Final answer generated.")).not.toBeInTheDocument();
    expect(screen.getAllByText("已生成回答").length).toBeGreaterThan(0);
  });

  it("preserves line breaks in assistant answers", () => {
    const run = getInitialMockRun();
    run.finalAnswer = "第一行\n- 第二行";

    render(<AgentWorkbench initialRun={run} />);

    expect(screen.getByText(/第一行/)).toHaveClass("answer-block");
  });

  it("shows a command approval dialog and reruns after approval", async () => {
    const spy = vi.spyOn(agentClient, "streamAgentRun");
    const approvalRun = getInitialMockRun();
    approvalRun.id = "run_needs_approval";
    approvalRun.prompt = "run command rm notes.md";
    approvalRun.status = "awaiting_approval";
    approvalRun.finalAnswer = "Command approval is required before I run this.";
    approvalRun.approvalRequest = {
      id: "cmd:1",
      type: "command",
      command: "rm notes.md",
      normalizedCommand: "rm notes.md",
      mode: "build",
      risk: "file_delete",
      reason: "dangerous_pattern"
    };
    const approvedRun = getInitialMockRun();
    approvedRun.id = "run_approved";
    approvedRun.prompt = "run command rm notes.md";
    approvedRun.finalAnswer = "approved output";

    spy.mockResolvedValueOnce(approvalRun).mockResolvedValueOnce(approvedRun);

    render(<AgentWorkbench initialRun={getInitialMockRun()} />);

    const textbox = screen.getByRole("textbox");
    fireEvent.change(textbox, { target: { value: "run command rm notes.md" } });
    fireEvent.keyDown(textbox, { key: "Enter" });

    expect(await screen.findByTestId("command-approval-dialog")).toBeInTheDocument();
    expect(screen.getByText("rm notes.md")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("approve-command"));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));

    expect(spy.mock.calls[1][0].collectedVars).toMatchObject({
      commandApproved: true,
      commandMode: "build",
      approvalId: "cmd:1",
      approvedCommand: "rm notes.md"
    });
    expect(await screen.findByText("approved output")).toBeInTheDocument();
  });
});
