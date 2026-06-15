import { type MouseEvent, useState } from "react";
import {
  Archive,
  BookOpen,
  MoreHorizontal,
  MessageSquarePlus,
  Pencil,
  Pin,
  Search,
  Trash2
} from "lucide-react";
import type { AgentSession } from "@/lib/types/agent";

interface LeftRailProps {
  activeSessionId: string;
  sessions: AgentSession[];
  onNewSession: () => void;
  onArchiveSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  onPinSession: (sessionId: string) => void;
  onRenameSession: (sessionId: string) => void;
  onSelectSession: (sessionId: string) => void;
  onToggleRightPanel: () => void;
}

const SESSION_MENU_WIDTH = 132;
const SESSION_MENU_HEIGHT = 146;
const SESSION_MENU_GAP = 6;
const VIEWPORT_GUTTER = 8;

interface OpenSessionMenu {
  sessionId: string;
  left: number;
  top: number;
}

function formatSessionDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "刚刚";
  }

  return `${date.getMonth() + 1}月${date.getDate()}日`;
}

export function LeftRail({
  activeSessionId,
  sessions,
  onNewSession,
  onArchiveSession,
  onDeleteSession,
  onPinSession,
  onRenameSession,
  onSelectSession,
  onToggleRightPanel
}: LeftRailProps) {
  const [openMenu, setOpenMenu] = useState<OpenSessionMenu | undefined>();

  function handleAction(action: (sessionId: string) => void, sessionId: string) {
    action(sessionId);
    setOpenMenu(undefined);
  }

  function handleMenuToggle(event: MouseEvent<HTMLButtonElement>, sessionId: string) {
    const rect = event.currentTarget.getBoundingClientRect();
    const viewportWidth = window.innerWidth || document.documentElement.clientWidth;
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
    const maxLeft = Math.max(VIEWPORT_GUTTER, viewportWidth - SESSION_MENU_WIDTH - VIEWPORT_GUTTER);
    const maxTop = Math.max(VIEWPORT_GUTTER, viewportHeight - SESSION_MENU_HEIGHT - VIEWPORT_GUTTER);
    const left = Math.min(Math.max(VIEWPORT_GUTTER, rect.right - SESSION_MENU_WIDTH), maxLeft);
    const top = Math.min(Math.max(VIEWPORT_GUTTER, rect.bottom + SESSION_MENU_GAP), maxTop);

    setOpenMenu((current) => (current?.sessionId === sessionId ? undefined : { sessionId, left, top }));
  }

  return (
    <aside className="left-rail">
      <div className="rail-brand">
        <h1>经纪人助手</h1>
      </div>

      <div className="rail-actions" aria-label="功能按钮">
        <button className="rail-action primary" type="button" onClick={onNewSession}>
          <MessageSquarePlus aria-hidden="true" size={17} />
          <span>新会话</span>
        </button>
        <button className="rail-action" type="button">
          <Search aria-hidden="true" size={17} />
          <span>查找会话</span>
        </button>
        <button className="rail-action" type="button" onClick={onToggleRightPanel}>
          <BookOpen aria-hidden="true" size={17} />
          <span>资料侧栏</span>
        </button>
      </div>

      <section className="rail-section rail-grow session-section">
        <div className="section-heading session-heading">
          <span>会话历史</span>
          <small>{sessions.length}</small>
        </div>
        <div className="session-list" onScroll={() => setOpenMenu(undefined)}>
          {sessions.map((session) => (
            <div
              className={session.id === activeSessionId ? "session-item active" : "session-item"}
              key={session.id}
            >
              <button
                className="session-row"
                data-testid="session-row"
                type="button"
                onClick={() => onSelectSession(session.id)}
              >
                <span>{session.title}</span>
                <small>{formatSessionDate(session.updatedAt)}</small>
              </button>
              <button
                aria-expanded={openMenu?.sessionId === session.id}
                aria-label={`会话设置：${session.title}`}
                className="session-action-trigger"
                type="button"
                onClick={(event) => handleMenuToggle(event, session.id)}
              >
                <MoreHorizontal aria-hidden="true" size={16} />
              </button>
              {openMenu?.sessionId === session.id ? (
                <div className="session-menu" role="menu" style={{ left: openMenu.left, top: openMenu.top }}>
                  <button type="button" role="menuitem" onClick={() => handleAction(onRenameSession, session.id)}>
                    <Pencil aria-hidden="true" size={15} />
                    重命名
                  </button>
                  <button type="button" role="menuitem" onClick={() => handleAction(onPinSession, session.id)}>
                    <Pin aria-hidden="true" size={15} />
                    置顶聊天
                  </button>
                  <button type="button" role="menuitem" onClick={() => handleAction(onArchiveSession, session.id)}>
                    <Archive aria-hidden="true" size={15} />
                    归档
                  </button>
                  <button
                    className="danger"
                    type="button"
                    role="menuitem"
                    onClick={() => handleAction(onDeleteSession, session.id)}
                  >
                    <Trash2 aria-hidden="true" size={15} />
                    删除
                  </button>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      </section>
    </aside>
  );
}
