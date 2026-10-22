import { createContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { APP_VERSION, useAppUpdate } from '../useAppUpdate';
import { restoreRefreshScroll } from '../refreshPosition';
import { FloatingMessage, Notifications } from './Notifications';
import { TaskSidebar } from './TaskSidebar';
import { BottomTools } from './BottomTools';
import { ProjectSwitcher } from './ProjectSwitcher';

export const HeaderControlsContext = createContext<HTMLElement | null>(null);
export const FooterCheckContext = createContext<HTMLElement | null>(null);

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const { service, pending } = useAppUpdate();
  const development = service.data?.environment === 'development';
  const [backTop, setBackTop] = useState(false);
  const [controlsRoot, setControlsRoot] = useState<HTMLDivElement | null>(null);
  const [checkRoot, setCheckRoot] = useState<HTMLSpanElement | null>(null);
  const header = useRef<HTMLElement>(null);
  const main = useRef<HTMLElement>(null);
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => {
      document.documentElement.style.setProperty('--site-header-height', `${entry.borderBoxSize[0].blockSize}px`);
    });
    observer.observe(header.current!);
    return () => { observer.disconnect(); document.documentElement.style.removeProperty('--site-header-height'); };
  }, []);
  useEffect(() => {
    const listener = () => setBackTop(window.scrollY > 300);
    window.addEventListener('scroll', listener, { passive: true });
    return () => window.removeEventListener('scroll', listener);
  }, []);
  useEffect(() => { window.scrollTo(0, 0); }, [location.pathname]);
  useEffect(() => restoreRefreshScroll(main.current!), []);
  return <Notifications><HeaderControlsContext.Provider value={controlsRoot}><FooterCheckContext.Provider value={checkRoot}>
    <div className="workspace-with-tasks"><TaskSidebar />
    <header className="site-header" ref={header}>
      <div className="header-main"><ProjectSwitcher />
        <div className="header-controls" ref={setControlsRoot} /></div>
    </header>
    <main ref={main} className={location.pathname.startsWith('/projects/') ? 'project-page' : undefined}>{children}</main>
    <footer className="site-footer">
      <span className="service-dot">{development ? '开发环境 · 共用正式资料' : '服务运行中'}</span>
      <Link className="history-link" to="/history">版本与开发记录 · v{APP_VERSION}</Link>
      <span className="footer-sync" ref={setCheckRoot} />
    </footer>
    <BottomTools>
      {backTop && <button className="back-top" onClick={() => window.scrollTo({ top: 0, behavior: 'auto' })}>↑ 返回顶部</button>}
    </BottomTools>
    {pending && <FloatingMessage>页面已有更新，将在编辑或播放结束后自动刷新。</FloatingMessage>}
    </div>
  </FooterCheckContext.Provider></HeaderControlsContext.Provider></Notifications>;
}
