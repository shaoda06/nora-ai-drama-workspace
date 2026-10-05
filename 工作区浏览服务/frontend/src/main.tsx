import { Component, lazy, Suspense, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter, Routes, Route, NavLink, Link, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { get } from './api';
import { Result } from './components';
import './style.css';
const Project = lazy(() => import('./Project'));
const Krea = lazy(() => import('./Krea'));
const History = lazy(() => import('./History'));
const client = new QueryClient({ defaultOptions: { queries: { staleTime: 2000, retry: false, refetchOnWindowFocus: false } } });
class PageBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    return this.state.error ? <div className="error" role="alert"><p>页面无法打开：{this.state.error.message}</p><p>服务代码更新后，已打开的浏览页需要重新载入。</p><button onClick={() => window.location.reload()}>重新打开页面</button></div> : this.props.children;
  }
}
function Home() {
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => get<{ id: string; name: string }[]>('/api/projects'), refetchInterval: 5000 });
  return <><p className="eyebrow">NORA · WORKSPACE</p><h1>工作区</h1><p className="lead">从这里进入项目，查看制作资料与素材。</p><div className="section-heading"><h2>短剧项目</h2><span className="muted">自动发现 projects 目录中的项目</span></div><Result loading={projects.isPending} error={projects.error} /><div className="grid">{projects.data?.map(item => <Link className="project-card" key={item.id} to={`/projects/${encodeURIComponent(item.id)}`}><span className="project-icon">▤</span><h3>{item.name}</h3><p>进入项目浏览 <span>→</span></p></Link>)}</div>{projects.data?.length === 0 && <p className="muted">暂无项目。项目资料保存到工作区 projects 目录后会出现在这里。</p>}<div className="section-heading"><h2>共用工具</h2></div><div className="grid"><Link className="project-card" to="/krea2"><h3>Krea2 风格库</h3><p>预览、提示词与资源更新 →</p></Link><Link className="project-card" to="/history"><h3>版本与开发记录</h3><p>功能进度、实现过程与验证 →</p></Link></div></>;
}
function App() {
  const location = useLocation();
  const [backTop, setBackTop] = useState(false);
  useEffect(() => { const listener = () => setBackTop(window.scrollY > 300); window.addEventListener('scroll', listener, { passive: true }); return () => window.removeEventListener('scroll', listener); }, []);
  useEffect(() => { window.scrollTo(0, 0); }, [location.pathname]);
  return <><header className="site-header"><Link className="brand" to="/">Nora <span>工作区浏览</span></Link><nav aria-label="主导航"><NavLink to="/" end>工作区</NavLink><NavLink to="/krea2">风格库</NavLink><NavLink to="/history">开发记录</NavLink></nav><span className="service-dot">服务运行中</span></header><main><Suspense fallback={<p role="status">正在打开…</p>}><Routes><Route path="/" element={<Home />} /><Route path="/projects/:name" element={<Project />} /><Route path="/krea2" element={<Krea />} /><Route path="/history" element={<History />} /><Route path="*" element={<p>入口不存在。<Link to="/">回到工作区</Link></p>} /></Routes></Suspense></main><footer>源文件与实际审核记录是内容依据 · 浏览页只读展示</footer>{backTop && <button className="back-top" onClick={() => window.scrollTo({ top: 0, behavior: 'auto' })}>↑ 返回顶部</button>}</>;
}
createRoot(document.getElementById('root')!).render(<PageBoundary><QueryClientProvider client={client}><HashRouter><App /></HashRouter></QueryClientProvider></PageBoundary>);
