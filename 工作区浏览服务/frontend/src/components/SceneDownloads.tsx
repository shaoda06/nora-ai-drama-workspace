import { useQuery } from '@tanstack/react-query';
import { get, projectUrl } from '../api';
import { Result } from '../components';
import './SceneDownloads.css';

type Resource = { count: number; url: string | null };
type Downloads = Record<string, Record<'videos' | 'director' | 'canvas', Resource>>;

function DownloadButton({ resource, label, bundle = false }: { resource?: Resource; label: string; bundle?: boolean }) {
  const className = bundle ? 'stage-download-bundle stage-download-link' : 'stage-download-link';
  return resource?.url
    ? <a className={className} href={resource.url} download title={`下载本集该阶段的${resource.count}个文件`}>{label}</a>
    : <button type="button" className={className} disabled title="本集该阶段暂无对应文件">{label}</button>;
}

export function SceneDownloads({ project, episode, revision }: { project: string; episode: string; revision: number }) {
  const downloads = useQuery({ queryKey: ['episode-downloads', project, episode, revision],
    queryFn: () => get<Downloads>(`${projectUrl(project)}/episodes/${episode}/downloads`) });
  return <div className="stage-downloads" aria-label="资源下载">
    <Result loading={downloads.isPending} error={downloads.error} retry={downloads.refetch} retrying={downloads.isFetching} />
    {['后处理', '二采', '一采'].map(stage => <section className="stage-download-section" key={stage} aria-label={stage + '资源下载'}>
      <h3>{stage}</h3>
      <section className="stage-download-group" aria-label={stage + '正式版视频下载'}>
        <h4>正式版视频下载</h4>
        <DownloadButton resource={downloads.data?.[stage].videos} label="打包下载正式版视频" bundle />
        {downloads.data && <span className="stage-download-count muted">{downloads.data[stage].videos.count}个正式版视频</span>}
      </section>
      <section className="stage-download-group" aria-label={stage + '导演包下载'}>
        <h4>导演包下载</h4>
        <div className="stage-download-actions">
          <DownloadButton resource={downloads.data?.[stage].director} label="下载导演包" />
          <DownloadButton resource={downloads.data?.[stage].canvas} label="下载画布" />
        </div>
      </section>
    </section>)}
  </div>;
}
