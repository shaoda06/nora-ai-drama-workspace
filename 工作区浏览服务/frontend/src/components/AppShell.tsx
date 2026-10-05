import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';

export function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [backTop, setBackTop] = useState(false);
  useEffect(() => {
    const listener = () => setBackTop(window.scrollY > 300);
    window.addEventListener('scroll', listener, { passive: true });
    return () => window.removeEventListener('scroll', listener);
  }, []);
  useEffect(() => { window.scrollTo(0, 0); }, [location.pathname]);
  return <>
    <header className="site-header">
      <Link className="brand" to="/">Nora工作台</Link>
      <nav aria-label="主导航">
        <NavLink to="/" end>工作区</NavLink>
        <NavLink to="/krea2">风格库</NavLink>
        <NavLink to="/history">开发记录</NavLink>
      </nav>
      <span className="service-dot">服务运行中</span>
    </header>
    <main>{children}</main>
    <footer>源文件与实际审核记录是内容依据 · 浏览页只读展示</footer>
    {backTop && <button className="back-top" onClick={() => window.scrollTo({ top: 0, behavior: 'auto' })}>↑ 返回顶部</button>}
  </>;
}
