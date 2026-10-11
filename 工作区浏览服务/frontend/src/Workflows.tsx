import { useQuery } from '@tanstack/react-query';
import { get } from './api';
import { Result } from './components';
import { PageHeader } from './components/PageHeader';
import { DownloadButton } from './components/DownloadButton';

type Workflow = { name: string; explicitOnly: boolean; canvasUrl: string; apiUrl: string | null };

export default function Workflows() {
  const query = useQuery({ queryKey: ['workflows'], queryFn: () => get<Workflow[]>('/api/workflows') });
  return <>
    <PageHeader title="内置工作流" description="画布版可在 ComfyUI 中打开编辑；API 版用于程序提交。" />
    <Result page loading={query.isPending} error={query.error} retry={query.refetch} retrying={query.isFetching} />
    <div className="grid">{query.data?.map(item => <article key={item.name}>
      <h2>{item.name}</h2>
      {item.explicitOnly && <p className="muted">仅在用户明确指定时使用。</p>}
      <div className="stage-download-actions"><DownloadButton url={item.canvasUrl} label="下载画布版" title={`${item.name} · 画布版`} />
      <DownloadButton url={item.apiUrl} label="下载 API 版" title={item.apiUrl ? `${item.name} · API 版` : 'API 文件缺失'} /></div>
    </article>)}</div>
    {query.data?.length === 0 && <p className="muted">暂无内置工作流。</p>}
  </>;
}
