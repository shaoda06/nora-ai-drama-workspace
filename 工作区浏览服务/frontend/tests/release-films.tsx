import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Project from '../src/Project';
import { HeaderControlsContext } from '../src/components/AppShell';
import { Notifications } from '../src/components/Notifications';
import '../src/style.css';
import.meta.glob('../src/**/*.css', { eager: true });

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
// Project has a disabled, cache-only section observer; any accidental fetch must fail this fixture.
client.setQueryDefaults(['section'], { queryFn: () => { throw new Error('缓存观察器不应主动读取'); } });
function Fixture() {
  const [header, setHeader] = useState<HTMLDivElement | null>(null);
  return <HeaderControlsContext.Provider value={header}>
    <header className="site-header"><div className="header-controls" ref={setHeader} /></header>
    <main className="project-page"><Routes><Route path="/projects/:name" element={<Project />} /></Routes></main>
  </HeaderControlsContext.Provider>;
}
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/projects/发布目录示例']}><Notifications><Fixture /></Notifications></MemoryRouter></QueryClientProvider>);
