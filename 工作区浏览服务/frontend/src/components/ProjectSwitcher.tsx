import { useQuery } from '@tanstack/react-query';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { get } from '../api';
import { Result } from '../components';
import { TabSelect } from './TabSelect';

export function ProjectSwitcher() {
  const location = useLocation();
  const navigate = useNavigate();
  const projects = useQuery({ queryKey: ['projects'],
    queryFn: () => get<{ id: string; name: string }[]>('/api/projects') });
  return <div className="brand-project-switcher">
    <Link className="brand" to="/">Nora工作台</Link>
    <TabSelect iconOnly label={projects.isPending ? '正在读取项目' : projects.data?.length === 0 ? '暂无项目' : '切换项目'}
      selected={location.pathname} onChange={navigate}
      items={(projects.data || []).map(project => ({ value: `/projects/${encodeURIComponent(project.id)}`, label: project.name }))} />
    <Result loading={false} error={projects.error} retry={projects.refetch} retrying={projects.isFetching} />
  </div>;
}
