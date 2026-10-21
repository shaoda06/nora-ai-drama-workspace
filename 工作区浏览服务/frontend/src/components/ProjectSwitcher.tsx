import { useId, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Link, useLocation } from 'react-router-dom';
import { get } from '../api';
import { Result } from '../components';

export function ProjectSwitcher() {
  const id = useId();
  const menu = useRef<HTMLElement>(null);
  const location = useLocation();
  const [expanded, setExpanded] = useState(false);
  const [position, setPosition] = useState({ left: 0, top: 0 });
  const projects = useQuery({ queryKey: ['projects'],
    queryFn: () => get<{ id: string; name: string }[]>('/api/projects'), enabled: expanded });
  return <div className="brand-project-switcher">
    <Link className="brand" to="/">Nora工作台</Link>
    <button type="button" className="brand-project-toggle" aria-label="切换项目" aria-expanded={expanded}
      aria-controls={id} popoverTarget={id} onClick={event => {
        const rect = event.currentTarget.parentElement!.getBoundingClientRect();
        const width = Math.min(280, window.innerWidth - 32);
        setPosition({ left: Math.max(16, Math.min(rect.left, window.innerWidth - width - 16)), top: rect.bottom + 6 });
      }}>
      <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="m3 4.5 3 3 3-3" fill="none" stroke="currentColor" strokeWidth="1.5" /></svg>
    </button>
    <nav ref={menu} id={id} popover="auto" className="brand-project-menu" aria-label="项目列表" style={position}
      onToggle={event => setExpanded(event.currentTarget.matches(':popover-open'))}>
      <Result loading={projects.isPending} error={projects.error} retry={projects.refetch} retrying={projects.isFetching} />
      {projects.data?.map(project => <Link key={project.id} to={`/projects/${encodeURIComponent(project.id)}`}
        aria-current={location.pathname === `/projects/${encodeURIComponent(project.id)}` ? 'page' : undefined}
        onClick={() => menu.current!.hidePopover()}>{project.name}</Link>)}
      {projects.data?.length === 0 && <p className="muted">暂无项目。</p>}
    </nav>
  </div>;
}
