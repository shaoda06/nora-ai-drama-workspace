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
    : <DownloadButton url={null} label={label} title="本场该阶段暂无对应文件" />;
}

export function SceneDownloads({ project, episode, scene, revision }: { project: string; episode: string; scene: string; revision: number }) {
  const downloads = useQuery({ queryKey: ['episode-downloads', project, episode, scene, revision],
    queryFn: () => get<Downloads>(`${projectUrl(project)}/episodes/${episode}/downloads?scene=${encodeURIComponent(scene)}`), placeholderData: keepPreviousData });
  return <div className="stage-downloads" aria-label="资源下载">
    {(downloads.isFetching || downloads.isPending || downloads.error) && <Result
      loading={downloads.isFetching || downloads.isPending} error={downloads.error} retry={downloads.refetch} retrying={downloads.isFetching} />}
    <div hidden={downloads.isFetching || downloads.isPending || !!downloads.error}>
    {downloads.data && <>
    {['后处理', '二采', '一采'].map(stage => <section className="stage-download-section" key={stage} aria-label={stage + '资源下载'}>
      <h3>{stage}</h3>
      <section className="stage-download-group" aria-label={stage + '已采用视频下载'}>
        <h4>已采用视频下载 <small className="stage-download-count muted">{downloads.data[stage].videos.count}份产物文件</small></h4>
        <div className="stage-download-actions">
        <DownloadButton url={downloads.data[stage].videos.url ? downloads.data[stage].videos.url + '&format=jypack' : null}
          label="剪映草稿包" pack title="下载后双击或拖入剪映，由剪映导入本场已采用视频；需支持原生草稿包导入及对应会员权限" />
        <DownloadButton url={downloads.data[stage].videos.url} label="视频 ZIP 包" pack title={downloads.data[stage].videos.url
          ? `仅下载${episode}场次${scene}的${stage}已采用视频，共${downloads.data[stage].videos.count}份产物文件`
          : `场次${scene}的${stage}暂无已采用视频`} />
        </div>
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
