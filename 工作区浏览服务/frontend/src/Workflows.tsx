import { PageCheckStatus } from './components/PageCheckStatus';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get } from './api';
import { Result } from './components';
import { PageHeader } from './components/PageHeader';
import { DownloadButton } from './components/DownloadButton';
import './Workflows.css';

type Workflow = { name: string; group: 'formal' | 'backup'; canvasUrl: string; apiUrl: string | null };
const groups = [
  { id: 'formal', title: '正式工作流', description: '日常制作使用的工作流。' },
  { id: 'backup', title: '备用工作流', description: '来自「非正式工作流」目录，按具体需要选用。' },
] as const;

export default function Workflows() {
  const query = useQuery({ queryKey: ['workflows'], queryFn: () => get<Workflow[]>('/api/workflows') });
  return <>
    <PageCheckStatus queries={[query]} />
    <PageHeader title="内置工作流" description="画布版可在 ComfyUI 中打开编辑；API 版用于程序提交。" />
    <Result page loading={query.isPending} error={query.error} retry={query.refetch} retrying={query.isFetching} />
    {query.data && groups.map(group => {
      const items = query.data.filter(item => item.group === group.id);
      return <section className="workflow-group" key={group.id} aria-labelledby={`workflows-${group.id}`}>
        <div className="workflow-group-heading"><h2 id={`workflows-${group.id}`}>{group.title}<span>{items.length}</span></h2><p>{group.description}</p></div>
        <div className="workflow-list">{items.map(item => <WorkflowCard item={item} key={item.canvasUrl} />)}</div>
        {items.length === 0 && <p className="muted">暂无{group.title}。</p>}
      </section>;
    })}
    {query.data?.length === 0 && <p className="muted">暂无内置工作流。</p>}
  </>;
}

function WorkflowCard({ item }: { item: Workflow }) {
  const [busy, setBusy] = useState(false);
  return <article className="workflow-row">
    <div className="workflow-info"><h3>{item.name}</h3></div>
    <div className="workflow-downloads">
      <DownloadButton url={item.canvasUrl} label="下载画布版" title={`${item.name} · 画布版`} disabled={busy} onStateChange={state => setBusy(state.busy)} />
      <DownloadButton url={item.apiUrl} label="下载 API 版" title={item.apiUrl ? `${item.name} · API 版` : 'API 文件缺失'} disabled={busy} onStateChange={state => setBusy(state.busy)} />
    </div>
  </article>;
}
