import { Command, ImageIcon, Monitor, Paperclip, Send, Sparkles, Square } from "lucide-react";

interface PromptComposerProps {
  prompt: string;
  commandMode: "plan" | "build";
  isAnchored: boolean;
  isRunning: boolean;
  onCommandModeChange: (mode: "plan" | "build") => void;
  onPromptChange: (prompt: string) => void;
  onRun: () => void;
  onQueueGuidance: () => void;
  onStop: () => void;
  isStopping?: boolean;
}

const quickActions = [
  { icon: ImageIcon, label: "复制界面" },
  { icon: Command, label: "导入设计" },
  { icon: Monitor, label: "创建页面" },
  { icon: Sparkles, label: "优化内容" }
];

export function PromptComposer({
  prompt,
  commandMode,
  isAnchored,
  isRunning,
  onCommandModeChange,
  onPromptChange,
  onRun,
  onQueueGuidance,
  onStop,
  isStopping = false
}: PromptComposerProps) {
  const canRun = prompt.trim().length > 0;

  return (
    <div
      className={isAnchored ? "composer-wrap composer-bottom" : "composer-wrap composer-center"}
      data-testid="composer-shell"
    >
      <section className="prompt-composer">
        <label className="sr-only" htmlFor="prompt">
          输入消息
        </label>
        <textarea
          id="prompt"
          value={prompt}
          onChange={(event) => onPromptChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              if (isRunning) {
                onQueueGuidance();
              } else {
                onRun();
              }
            }
          }}
          placeholder="问我一个问题..."
          rows={3}
        />
        <div className="composer-toolbar">
          <div className="composer-tools">
            <button type="button" aria-label="添加附件">
              <Paperclip aria-hidden="true" size={18} />
            </button>
            <button type="button" aria-label="快捷指令">
              <Command aria-hidden="true" size={18} />
            </button>
            <div className="command-mode-toggle" aria-label="命令模式">
              <button
                type="button"
                className={commandMode === "plan" ? "active" : undefined}
                onClick={() => onCommandModeChange("plan")}
              >
                计划
              </button>
              <button
                type="button"
                className={commandMode === "build" ? "active" : undefined}
                onClick={() => onCommandModeChange("build")}
              >
                构建
              </button>
            </div>
          </div>
          <div className="composer-actions">
            {isRunning ? (
              <>
                <button className="queue-button" type="button" onClick={onQueueGuidance} disabled={!canRun}>
                  <Send aria-hidden="true" size={17} />
                  预提交
                </button>
                <button className="stop-button" type="button" onClick={onStop} disabled={isStopping}>
                  <Square aria-hidden="true" size={15} />
                  {isStopping ? "正在停止" : "终止"}
                </button>
              </>
            ) : (
              <button className="send-button" type="button" onClick={onRun} disabled={!canRun}>
                <Send aria-hidden="true" size={17} />
                发送
              </button>
            )}
          </div>
        </div>
      </section>

      {!isAnchored ? (
        <div className="quick-actions" aria-label="快捷功能">
          {quickActions.map(({ icon: Icon, label }) => (
            <button type="button" key={label}>
              <Icon aria-hidden="true" size={16} />
              {label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
