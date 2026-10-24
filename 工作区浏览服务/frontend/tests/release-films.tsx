import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Link, MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Project from '../src/Project';
import { HeaderControlsContext } from '../src/components/AppShell';
import { Notifications } from '../src/components/Notifications';
import { TabSelect } from '../src/components/TabSelect';
import '../src/style.css';
import.meta.glob('../src/**/*.css', { eager: true });

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
// Project has a disabled, cache-only section observer; any accidental fetch must fail this fixture.
client.setQueryDefaults(['section'], { queryFn: () => { throw new Error('缓存观察器不应主动读取'); } });
function Fixture() {
  const [header, setHeader] = useState<HTMLDivElement | null>(null);
  const headerElement = useRef<HTMLElement>(null);
  // Mirror AppShell's header layout and scroll offset without its real task/API polling.
  useEffect(() => {
    const observer = new ResizeObserver(([entry]) => document.documentElement.style.setProperty('--site-header-height', `${entry.borderBoxSize[0].blockSize}px`));
    observer.observe(headerElement.current!);
    return () => observer.disconnect();
  }, []);
  return <HeaderControlsContext.Provider value={header}>
    <div className="workspace-with-tasks">
    <header className="site-header" ref={headerElement}><div className="header-main">
      <div className="brand-project-switcher"><Link className="brand" to="/">Nora工作台</Link><TabSelect iconOnly label="项目切换示例" items={[{ value: 'fixture', label: '只读项目示例' }]} selected="fixture" onChange={() => {}} /></div>
      <div className="header-controls" ref={setHeader} />
    </div></header>
    <main className="project-page"><Routes><Route path="/projects/:name" element={<Project />} /></Routes></main>
    </div>
  </HeaderControlsContext.Provider>;
}
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/projects/发布目录示例']}><Notifications><Fixture /></Notifications></MemoryRouter></QueryClientProvider>);
