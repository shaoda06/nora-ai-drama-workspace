import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Project from '../src/Project';
import { HeaderControlsContext } from '../src/components/AppShell';
import { ProjectSwitcher } from '../src/components/ProjectSwitcher';
import { Notifications } from '../src/components/Notifications';
import '../src/style.css';
import.meta.glob('../src/**/*.css', { eager: true });

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
client.setQueryDefaults(['section'], { queryFn: () => { throw new Error('缓存观察器不应主动读取'); } });
client.setQueryDefaults(['episode'], { queryFn: () => { throw new Error('缓存观察器不应主动读取'); } });
function Fixture() {
  const [header, setHeader] = useState<HTMLDivElement | null>(null);
  return <HeaderControlsContext.Provider value={header}><div className="workspace-with-tasks">
    <header className="site-header"><div className="header-main"><ProjectSwitcher /><div className="header-controls" ref={setHeader} /></div></header>
    <main className="project-page"><Routes><Route path="/projects/:name" element={<Project />} /></Routes></main>
  </div></HeaderControlsContext.Provider>;
}
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><HashRouter><Notifications><Fixture /></Notifications></HashRouter></QueryClientProvider>);
