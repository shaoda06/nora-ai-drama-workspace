import { createContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';

export const HeaderControlsContext = createContext<HTMLElement | null>(null);

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [backTop, setBackTop] = useState(false);
  const [controlsRoot, setControlsRoot] = useState<HTMLDivElement | null>(null);
  useEffect(() => {
    const listener = () => setBackTop(window.scrollY > 300);
    window.addEventListener('scroll', listener, { passive: true });
    return () => window.removeEventListener('scroll', listener);
  }, []);
  useEffect(() => { window.scrollTo(0, 0); }, [location.pathname]);
  return <HeaderControlsContext.Provider value={controlsRoot}>
    <header className="site-header">
      <div className="header-main"><Link className="brand" to="/">Nora工作台</Link>
        <div className="header-controls" ref={setControlsRoot} />
        <div className="header-info"><span className="service-dot">服务运行中</span>
          <Link className="history-link" to="/history">版本与开发记录</Link></div></div>
    </header>
    <main className={location.pathname.startsWith('/projects/') ? 'project-page' : undefined}>{children}</main>
    <footer>源文件与实际审核记录是内容依据 · 浏览页只读展示</footer>
    {backTop && <button className="back-top" onClick={() => window.scrollTo({ top: 0, behavior: 'auto' })}>↑ 返回顶部</button>}
  </HeaderControlsContext.Provider>;
}
