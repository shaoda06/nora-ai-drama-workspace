import { Component, lazy, Suspense } from 'react';
import type { ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter, Routes, Route, Link } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { get } from './api';
import { Result } from './components';
import { AppShell } from './components/AppShell';
import { PageHeader } from './components/PageHeader';
import { EntryCard } from './components/EntryCard';
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
  return <><PageHeader eyebrow="NORA · WORKSPACE" title="工作区" description="从这里进入项目，查看制作资料与素材。" /><div className="section-heading"><h2>短剧项目</h2><span className="muted">自动发现 projects 目录中的项目</span></div><Result loading={projects.isPending} error={projects.error} /><div className="grid">{projects.data?.map(item => <EntryCard key={item.id} to={`/projects/${encodeURIComponent(item.id)}`} title={item.name} description="进入项目浏览" icon="▤" />)}</div>{projects.data?.length === 0 && <p className="muted">暂无项目。项目资料保存到工作区 projects 目录后会出现在这里。</p>}<div className="section-heading"><h2>共用工具</h2></div><div className="grid"><EntryCard to="/krea2" title="Krea2 风格库" description="预览、提示词与资源更新" /><EntryCard to="/history" title="版本与开发记录" description="功能进度、实现过程与验证" /></div></>;
}
function App() {
  return <AppShell><Suspense fallback={<p role="status">正在打开…</p>}><Routes><Route path="/" element={<Home />} /><Route path="/projects/:name" element={<Project />} /><Route path="/krea2" element={<Krea />} /><Route path="/history" element={<History />} /><Route path="*" element={<p>入口不存在。<Link to="/">回到工作区</Link></p>} /></Routes></Suspense></AppShell>;
}
createRoot(document.getElementById('root')!).render(<PageBoundary><QueryClientProvider client={client}><HashRouter><App /></HashRouter></QueryClientProvider></PageBoundary>);
