import { Component, lazy, Suspense, useState } from 'react';
import type { ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { createHashRouter, RouterProvider, Routes, Route, Link } from 'react-router-dom';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { get } from './api';
import { Dialog, Document, Result } from './components';
import { AppShell } from './components/AppShell';
import { EntryCard } from './components/EntryCard';
import { Loading } from './components/Loading';
import './style.css';
const Project = lazy(() => import('./Project'));
const Krea = lazy(() => import('./Krea'));
const History = lazy(() => import('./History'));
const Workflows = lazy(() => import('./Workflows'));
const Prompts = lazy(() => import('./Prompts'));
const Assets = lazy(() => import('./Assets'));
const client = new QueryClient({ defaultOptions: { queries: { staleTime: 2000, retry: false, refetchOnWindowFocus: false } } });
class PageBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  render() {
    return this.state.error ? <div className="error" role="alert"><p>页面无法打开：{this.state.error.message}</p><p>服务代码更新后，已打开的浏览页需要重新载入。</p><button onClick={() => window.location.reload()}>重新打开页面</button></div> : this.props.children;
  }
}
function Home() {
  const [indexOpen, setIndexOpen] = useState(false);
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => get<{ id: string; name: string }[]>('/api/projects'), refetchInterval: 5000 });
  const index = useQuery({ queryKey: ['project-index'], queryFn: () => get<{ title: string; html: string }>('/api/project-index'), enabled: indexOpen, refetchInterval: 5000 });
  return <div className="home">
    <div className="section-heading"><h2>共用工具</h2></div>
    <div className="grid"><EntryCard to="/assets/person" title="资产管理" description="人物资料、服装、道具与图片相册" /><EntryCard to="/prompts" title="提示词管理" description="分类整理、编辑与搜索常用提示词" /><EntryCard to="/krea2" title="Krea2 风格库" description="预览、提示词与资源更新" /><EntryCard to="/workflows" title="内置工作流" description="下载画布版与 API 版工作流" /></div>
    <div className="section-heading"><h2>短剧项目</h2><span className="muted">按<button type="button" className="link" aria-label="查看项目总索引" onClick={() => setIndexOpen(true)}>项目总索引</button>排序</span></div>
    <Result page loading={projects.isPending} error={projects.error} retry={projects.refetch} retrying={projects.isFetching} />
    <div className="grid">{projects.data?.map((item, index) => <EntryCard key={item.id} to={`/projects/${encodeURIComponent(item.id)}`} title={`${String(index + 1).padStart(2, '0')}-${item.name}`} description="进入项目浏览" icon="▤" />)}</div>
    {projects.data?.length === 0 && <p className="muted">暂无项目。项目资料保存到工作区 projects 目录后会出现在这里。</p>}
    {indexOpen && <Dialog title="项目总索引" close={() => setIndexOpen(false)}>
      <Result loading={index.isPending} error={index.error} retry={index.refetch} retrying={index.isFetching} />
      {index.data && <div className="project-index-document"><Document value={index.data} showOriginal={false} /></div>}
    </Dialog>}
  </div>;
}
function App() {
  return <AppShell><Suspense fallback={<Loading page />}><Routes><Route path="/" element={<Home />} /><Route path="/projects/:name" element={<Project />} /><Route path="/krea2" element={<Krea />} /><Route path="/workflows" element={<Workflows />} /><Route path="/prompts" element={<Prompts />} /><Route path="/assets/:kind?/:id?" element={<Assets />} /><Route path="/history" element={<History />} /><Route path="*" element={<p>入口不存在。<Link to="/">回到工作区</Link></p>} /></Routes></Suspense></AppShell>;
}
const router = createHashRouter([{ path: '*', element: <PageBoundary><App /></PageBoundary> }]);
createRoot(document.getElementById('root')!).render(<PageBoundary><QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider></PageBoundary>);
