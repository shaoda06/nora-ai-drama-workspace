import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { get, projectUrl } from '../api';
import { Result } from '../components';
import './SceneDownloads.css';

type Resource = { count: number; url: string | null; files: { name: string; url: string }[] };
type Downloads = Record<string, Record<'videos' | 'director' | 'canvas', Resource>>;

function DownloadButton({ url, label, title }: { url: string | null; label: string; title: string }) {
  const [requests, setRequests] = useState<string[]>([]);
  return <div className="stage-download-row">
    {url
      ? <a className="stage-download-link" href={url} download title={title}
        onClick={() => setRequests(previous => [...previous, new Date().toLocaleTimeString('zh-CN', { hour12: false })])}>{label}</a>
      : <button type="button" className="stage-download-link" disabled title="本集该阶段暂无对应文件">{label}</button>}
    {requests.map((time, index) => <span className="stage-download-message muted" role="status" key={index}>
      {time} 已请求下载，请查看浏览器下载列表。
    </span>)}
  </div>;
}

function OriginalDownloads({ resource, label }: { resource: Resource; label: string }) {
  return resource.files.length
    ? <>{resource.files.map(file => <DownloadButton key={file.url} url={file.url} label={file.name} title={`下载原文件：${file.name}`} />)}</>
    : <DownloadButton url={null} label={label} title="本集该阶段暂无对应文件" />;
}

export function SceneDownloads({ project, episode, revision }: { project: string; episode: string; revision: number }) {
  const downloads = useQuery({ queryKey: ['episode-downloads', project, episode, revision],
    queryFn: () => get<Downloads>(`${projectUrl(project)}/episodes/${episode}/downloads`) });
  if (downloads.isFetching || downloads.isPending || downloads.error) return <div className="stage-downloads" aria-label="资源下载">
    <Result loading={downloads.isFetching || downloads.isPending} error={downloads.error} retry={downloads.refetch} retrying={downloads.isFetching} />
  </div>;
  return <div className="stage-downloads" aria-label="资源下载">
    {['后处理', '二采', '一采'].map(stage => <section className="stage-download-section" key={stage} aria-label={stage + '资源下载'}>
      <h3>{stage}</h3>
      <section className="stage-download-group" aria-label={stage + '正式版视频下载'}>
        <h4>正式版视频下载 <small className="stage-download-count muted">{downloads.data[stage].videos.count}个正式版视频</small></h4>
        <DownloadButton url={downloads.data[stage].videos.url} label="打包下载" title={`下载本集${stage}的${downloads.data[stage].videos.count}个正式版视频`} />
      </section>
      <details className="stage-download-group" aria-label={stage + '导演包下载'}>
        <summary>导演包下载</summary>
        <div className="stage-download-actions">
          <OriginalDownloads resource={downloads.data[stage].director} label="下载导演包" />
          <OriginalDownloads resource={downloads.data[stage].canvas} label="下载画布" />
        </div>
      </details>
    </section>)}
  </div>;
}
