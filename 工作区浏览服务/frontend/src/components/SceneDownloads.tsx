import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { get, projectUrl } from '../api';
import { Result } from '../components';
import { DownloadButton } from './DownloadButton';
import './SceneDownloads.css';

type Resource = { count: number; url: string | null; files: { name: string; url: string }[] };
type Downloads = Record<string, Record<'videos' | 'director' | 'canvas', Resource>>;

function OriginalDownloads({ resource, label }: { resource: Resource; label: string }) {
  return resource.files.length
    ? <>{resource.files.map(file => <DownloadButton key={file.url} url={file.url} label={file.name} title={`下载原文件：${file.name}`} />)}</>
    : <DownloadButton url={null} label={label} title="本集该阶段暂无对应文件" />;
}

export function SceneDownloads({ project, episode, revision }: { project: string; episode: string; revision: number }) {
  const downloads = useQuery({ queryKey: ['episode-downloads', project, episode, revision],
    queryFn: () => get<Downloads>(`${projectUrl(project)}/episodes/${episode}/downloads`), placeholderData: keepPreviousData });
  return <div className="stage-downloads" aria-label="资源下载">
    {(downloads.isFetching || downloads.isPending || downloads.error) && <Result
      loading={downloads.isFetching || downloads.isPending} error={downloads.error} retry={downloads.refetch} retrying={downloads.isFetching} />}
    <div hidden={downloads.isFetching || downloads.isPending || !!downloads.error}>
    {downloads.data && <>
    {['后处理', '二采', '一采'].map(stage => <section className="stage-download-section" key={stage} aria-label={stage + '资源下载'}>
      <h3>{stage}</h3>
      <section className="stage-download-group" aria-label={stage + '正式版视频下载'}>
        <h4>正式版视频下载 <small className="stage-download-count muted">{downloads.data[stage].videos.count}个正式版视频</small></h4>
        <DownloadButton url={downloads.data[stage].videos.url} label="打包下载" pack title={`下载本集${stage}的${downloads.data[stage].videos.count}个正式版视频`} />
      </section>
      <details className="stage-download-group" aria-label={stage + '导演包下载'}>
        <summary>导演包下载</summary>
        <div className="stage-download-actions">
          <OriginalDownloads resource={downloads.data[stage].director} label="下载导演包" />
          <OriginalDownloads resource={downloads.data[stage].canvas} label="下载画布" />
        </div>
      </details>
    </section>)}
    </>}
    </div>
  </div>;
}
