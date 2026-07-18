import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { NAVIGATION, type NavigationNode } from "../navigation/menu";
import { useExecutionStatus } from "../presentation/coreModels";
import { formatChinaDateTime } from "../presentation/time";
import StatusBadge from "../ui/StatusBadge";

interface AppShellProps {
  children: ReactNode;
}

function hasActivePath(node: NavigationNode, pathname: string): boolean {
  return node.path === pathname || Boolean(node.children?.some((child) => hasActivePath(child, pathname)));
}

function NavGlyph() {
  return (
    <span className="nav-glyph" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M4 19V5h16v14H4Z" />
        <path d="M8 15v-3m4 3V8m4 7v-5" />
      </svg>
    </span>
  );
}

function NavigationItem({ node, depth = 0 }: { node: NavigationNode; depth?: number }) {
  const { pathname } = useLocation();
  const shouldOpen = hasActivePath(node, pathname);
  const [open, setOpen] = useState(shouldOpen);
  const childrenId = `nav-group-${node.id}`;

  useEffect(() => {
    if (shouldOpen) {
      setOpen(true);
    }
  }, [shouldOpen]);

  if (node.section) {
    return <div className="app-sidebar__section">{node.label}</div>;
  }

  if (!node.children?.length && node.path) {
    return (
      <NavLink
        className={({ isActive }) => `app-sidebar__link app-sidebar__link--level-${depth}${isActive ? " is-active" : ""}`}
        end
        to={node.path}
      >
        <NavGlyph />
        <span>{node.label}</span>
      </NavLink>
    );
  }

  return (
    <div className={`app-sidebar__group app-sidebar__group--level-${depth}`}>
      <button
        aria-controls={childrenId}
        aria-expanded={open}
        className="app-sidebar__group-button"
        type="button"
        onClick={() => setOpen((current) => !current)}
      >
        <NavGlyph />
        <span>{node.label}</span>
        <span className={`app-sidebar__chevron${open ? " is-open" : ""}`} aria-hidden="true" />
      </button>
      {open ? (
        <div className="app-sidebar__children" id={childrenId}>
          {node.children?.map((child) => (
            <NavigationItem key={child.id} node={child} depth={depth + 1} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export default function AppShell({ children }: AppShellProps) {
  const [clock, setClock] = useState(() => formatChinaDateTime(new Date()));
  const execution = useExecutionStatus();
  const executionKnown = execution.kind === "live" && Boolean(execution.data);
  const releaseLocks = executionKnown ? execution.data?.release_locks ?? [] : [];
  const tradingLock = releaseLocks.find((lock) => lock.key === "TRADING_EXECUTION_ENABLED");

  useEffect(() => {
    const timer = window.setInterval(() => setClock(formatChinaDateTime(new Date())), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <NavLink className="app-sidebar__brand" to="/">
          <span className="app-sidebar__brand-mark" aria-hidden="true">
            <NavGlyph />
          </span>
          <span>
            <strong>量化运营台</strong>
            <small>QUANT OPS</small>
          </span>
        </NavLink>
        <nav className="app-sidebar__nav" aria-label="量化运营台导航">
          {NAVIGATION.map((node) => (
            <NavigationItem key={node.id} node={node} />
          ))}
        </nav>
      </aside>
      <div className="app-shell__content">
        <header className="app-topbar">
          <div className="app-topbar__status">
            <StatusBadge label={executionKnown ? execution.data?.mode?.toUpperCase() ?? "未知" : "模式未知"} tone={executionKnown ? "info" : "reject"} />
            <StatusBadge label={`自动执行：${executionKnown ? tradingLock?.enabled ? "已开启" : tradingLock ? "关闭" : "状态未知" : "状态未知"}`} tone="reject" />
            <StatusBadge label="数据：待审核" tone="review" />
          </div>
          <div className="app-topbar__right">
            <span className="app-topbar__clock">{clock}</span>
            <span className="app-topbar__lock-count">{executionKnown ? releaseLocks.length ? `${releaseLocks.filter((lock) => !lock.enabled).length} 项发布锁关闭` : "发布锁状态未知" : "发布锁状态未知"}</span>
          </div>
        </header>
        <main className="app-shell__main">{children}</main>
        <footer className="app-footer">
          当前为运营台展示层。数据资格、业务发布与交易执行必须分别满足既有安全门禁。
        </footer>
      </div>
    </div>
  );
}
