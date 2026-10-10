import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { get, projectUrl } from '../api';
import { Result } from '../components';
import './SceneDownloads.css';

type Resource = { count: number; url: string | null; files: { name: string; url: string }[] };
type Downloads = Record<string, Record<'videos' | 'director' | 'canvas', Resource>>;

function DownloadButton({ resource, label, bundle = false, onDownload }: { resource?: Resource; label: string; bundle?: boolean; onDownload: () => void }) {
  const className = bundle ? 'stage-download-bundle stage-download-link' : 'stage-download-link';
  return resource?.url
    ? <a className={className} href={resource.url} download onClick={onDownload} title={`下载本集该阶段的${resource.count}个文件`}>{label}</a>
    : <button type="button" className={className} disabled title="本集该阶段暂无对应文件">{label}</button>;
}

function OriginalDownloads({ resource, label, onDownload }: { resource?: Resource; label: string; onDownload: (name: string) => void }) {
  return resource?.files.length
    ? <>{resource.files.map(file => <a key={file.url} className="stage-download-link" href={file.url} download
      onClick={() => onDownload(file.name)} title={`下载原文件：${file.name}`}>{resource.files.length === 1 ? label : file.name}</a>)}</>
    : <button type="button" className="stage-download-link" disabled title="本集该阶段暂无对应文件">{label}</button>;
}

export function SceneDownloads({ project, episode, revision }: { project: string; episode: string; revision: number }) {
  const [requestedDownload, setRequestedDownload] = useState('');
  const downloads = useQuery({ queryKey: ['episode-downloads', project, episode, revision],
    queryFn: () => get<Downloads>(`${projectUrl(project)}/episodes/${episode}/downloads`) });
  return <div className="stage-downloads" aria-label="资源下载">
    <Result loading={downloads.isPending} error={downloads.error} retry={downloads.refetch} retrying={downloads.isFetching} />
    {requestedDownload && <p className="muted" role="status">已请求下载：{requestedDownload}。保存情况请查看浏览器下载列表。</p>}
    {['后处理', '二采', '一采'].map(stage => <section className="stage-download-section" key={stage} aria-label={stage + '资源下载'}>
      <h3>{stage}</h3>
      <section className="stage-download-group" aria-label={stage + '正式版视频下载'}>
        <h4>正式版视频下载</h4>
        <DownloadButton resource={downloads.data?.[stage].videos} label="打包下载正式版视频" bundle onDownload={() => setRequestedDownload(stage + '正式版视频 ZIP')} />
        {downloads.data && <span className="stage-download-count muted">{downloads.data[stage].videos.count}个正式版视频</span>}
      </section>
      <section className="stage-download-group" aria-label={stage + '导演包下载'}>
        <h4>导演包下载</h4>
        <div className="stage-download-actions">
          <OriginalDownloads resource={downloads.data?.[stage].director} label="下载导演包" onDownload={setRequestedDownload} />
          <OriginalDownloads resource={downloads.data?.[stage].canvas} label="下载画布" onDownload={setRequestedDownload} />
        </div>
      </section>
    </section>)}
  </div>;
}
