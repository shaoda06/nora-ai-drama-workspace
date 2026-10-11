import { useQuery } from '@tanstack/react-query';
import { get } from './api';
import { Result } from './components';
import { PageHeader } from './components/PageHeader';
import { DownloadButton } from './components/DownloadButton';
import './Workflows.css';

type Workflow = { name: string; group: 'formal' | 'backup'; explicitOnly: boolean; canvasUrl: string; apiUrl: string | null };
const groups = [
  { id: 'formal', title: '正式工作流', description: '日常制作使用的工作流。' },
  { id: 'backup', title: '备用工作流', description: '来自「非正式工作流」目录，按具体需要选用。' },
] as const;

export default function Workflows() {
  const query = useQuery({ queryKey: ['workflows'], queryFn: () => get<Workflow[]>('/api/workflows') });
  return <>
    <PageHeader title="内置工作流" description="画布版可在 ComfyUI 中打开编辑；API 版用于程序提交。" />
    <Result page loading={query.isPending} error={query.error} retry={query.refetch} retrying={query.isFetching} />
    {query.data && groups.map(group => {
      const items = query.data.filter(item => item.group === group.id);
      return <section className="workflow-group" key={group.id} aria-labelledby={`workflows-${group.id}`}>
        <div className="workflow-group-heading"><h2 id={`workflows-${group.id}`}>{group.title}<span>{items.length}</span></h2><p>{group.description}</p></div>
        <div className="workflow-list">{items.map(item => <article className="workflow-row" key={item.canvasUrl}>
          <div className="workflow-info"><h3>{item.name}</h3>
            {item.explicitOnly && <p>仅在用户明确指定时使用。</p>}
          </div>
          <div className="workflow-downloads"><DownloadButton url={item.canvasUrl} label="下载画布版" title={`${item.name} · 画布版`} />
            <DownloadButton url={item.apiUrl} label="下载 API 版" title={item.apiUrl ? `${item.name} · API 版` : 'API 文件缺失'} />
          </div>
        </article>)}</div>
        {items.length === 0 && <p className="muted">暂无{group.title}。</p>}
      </section>;
    })}
    {query.data?.length === 0 && <p className="muted">暂无内置工作流。</p>}
  </>;
}
