import { createContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { get } from '../api';
import { Notifications } from './Notifications';

export const HeaderControlsContext = createContext<HTMLElement | null>(null);
export const FooterSyncContext = createContext<HTMLElement | null>(null);

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const service = useQuery({ queryKey: ['service'], queryFn: () => get<{ environment: string }>('/api/service'), staleTime: Infinity });
  const development = service.data?.environment === 'development';
  const [backTop, setBackTop] = useState(false);
  const [controlsRoot, setControlsRoot] = useState<HTMLDivElement | null>(null);
  const [syncRoot, setSyncRoot] = useState<HTMLSpanElement | null>(null);
  const header = useRef<HTMLElement>(null);
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
  return <Notifications><HeaderControlsContext.Provider value={controlsRoot}><FooterSyncContext.Provider value={syncRoot}>
    <header className="site-header" ref={header}>
      <div className="header-main"><Link className="brand" to="/">Nora工作台</Link>
        <div className="header-controls" ref={setControlsRoot} /></div>
    </header>
    <main className={location.pathname.startsWith('/projects/') ? 'project-page' : undefined}>{children}</main>
    <footer className="site-footer">
      <span className="service-dot">{development ? '开发环境 · 共用正式资料' : '服务运行中'}</span>
      <Link className="history-link" to="/history">版本与开发记录</Link>
      <span className="footer-sync"><span ref={setSyncRoot} />{!location.pathname.startsWith('/projects/') && '上次同步：—'}</span>
    </footer>
    {backTop && <button className="back-top" onClick={() => window.scrollTo({ top: 0, behavior: 'auto' })}>↑ 返回顶部</button>}
  </FooterSyncContext.Provider></HeaderControlsContext.Provider></Notifications>;
}
