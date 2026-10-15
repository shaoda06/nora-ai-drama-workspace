import { PointerTooltip } from './PointerTooltip';
import { useContext, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import type { FileItem } from '../api';
import { PreviewContext, Result } from '../components';
import { TabNav } from './TabNav';
import { Pagination } from './Pagination';
import { EpisodeButton } from './EpisodeButton';
import { SceneWorkspace } from './SceneWorkspace';
import { useRefreshState } from '../refreshPosition';
import { BreadcrumbActionsContext } from './Breadcrumbs';
import { get, projectUrl } from '../api';
import { DownloadButton } from './DownloadButton';
import { previousEpisodeEnding } from '../previousEpisodeEnding';
import './SceneDownloads.css';

export function EpisodeProduction({ project, items, selected, onSelect, revision }: { project: string; items: FileItem[]; selected: string | null; onSelect: (episode: string | null) => void; revision: number }) {
  const preview = useContext(PreviewContext);
  const breadcrumbActions = useContext(BreadcrumbActionsContext);
  const [scene, setScene] = useRefreshState(`project/${project}/production/scene`, '');
  const [page, setPage] = useState(1);
  const cards = useRef<HTMLDivElement>(null);
  const previousEpisode = useRef(selected);
  useEffect(() => {
    if (!selected && previousEpisode.current) cards.current!.querySelector<HTMLButtonElement>(`[data-episode="${previousEpisode.current}"]`)?.focus();
    previousEpisode.current = selected;
  }, [selected]);
  const selectedItem = items.find(item => item.name === selected);
  const detail = useQuery({ queryKey: ['episode', project, selected, revision],
    queryFn: () => get<FileItem>(`${projectUrl(project)}/episodes/${selected}`), enabled: !!selectedItem,
    placeholderData: (previous, query) => query?.queryKey[2] === selected ? previous : undefined });
  const current = selectedItem && detail.data?.name === selected ? detail.data : undefined;
  useEffect(() => {
    if (selected && !selectedItem) onSelect(null);
  }, [selected, selectedItem, onSelect]);
  const script = current?.script;
  const scenes = current?.scenes || [];
  const selectedScene = scenes.includes(scene) ? scene : scenes[0] || '';
  const segments = current?.segments?.[selectedScene] || [];
  const issues = (current?.productionIssues || []).filter(issue => !issue.scene || issue.scene === selectedScene);
  const episodeComplete = current?.productionComplete && !current.productionIssues?.length && scenes.length > 0 && scenes.every(id => {
    const sceneSegments = current.segments?.[id] || [];
    return sceneSegments.length > 0 && sceneSegments.every(item =>
      item.videos.filter(video => video.stage === '后处理' && video.approved).length === 1);
  });
  const segmentCount = scenes.reduce((count, id) => count + (current?.segments?.[id]?.length || 0), 0);
  const emptyMessage = issues.length > 0 ? '请先修正上方提示的文件结构，保存后页面会重新读取资料。'
    : !script ? '本集剧本尚未建立，请先准备本集剧本，再整理场次分镜和分段计划。'
    : '本场尚无分段计划，请先完善本集分镜索引。';
  let directorFiles = current?.children;
  for (const folder of ['06-阶段采用视频', '01-一采', selectedScene + '-场次', '导演包']) {
    directorFiles = directorFiles?.find(item => item.name === folder)?.children;
  }
  const open = (name: string) => {
    setScene('');
    onSelect(name);
  };
  return selectedItem && !current ? <Result page loading={detail.isPending} error={detail.error} retry={detail.refetch} retrying={detail.isFetching} /> : current ? <div className="episode-detail">
    {breadcrumbActions && episodeComplete && createPortal(<DownloadButton key={current.name} pack
      url={`${projectUrl(project)}/episodes/${current.name}/download`} label="本集打包下载"
      title={`下载${current.name}全部${scenes.length}个场次、${segmentCount}段后处理正式版视频`} />, breadcrumbActions)}
    <div className="episode-scene-header">
      {scenes.length > 0 && <TabNav label="本集场次" items={scenes.map(id => ({ value: id, label: '场次 ' + id }))} selected={selectedScene} onChange={setScene} />}
      <PointerTooltip text={script ? undefined : '本集剧本尚未建立'}><button className="link episode-script-link" disabled={!script}  onClick={() => preview(script!)}>查看本集剧本</button></PointerTooltip>
    </div>
    {!!current.warnings?.length && <details className="notice"><summary>资料提示（{current.warnings.length}）</summary>{current.warnings.map(message => <p key={message}>{message}</p>)}</details>}
    {issues.length > 0 ? <div className="notice episode-data-issues" role="alert">
      <strong>制作资料需要修正</strong>
      <ul>{issues.map((issue, index) => <li key={index}>
        <PointerTooltip text={issue.key}><button className="link"  onClick={() => preview({ kind: 'document', key: issue.key, name: issue.key.split('/').pop()! })}>{issue.key.split('/').pop()}</button></PointerTooltip>：{issue.message}
      </li>)}</ul>
    </div> : null}
    {selectedScene ? <SceneWorkspace key={current.name + '/' + selectedScene} scope={{ project, episode: current.name, scene: selectedScene }} segments={segments} previousEnding={previousEpisodeEnding(current.previousEpisode ? [current.previousEpisode] : [], current.name)} emptyMessage={emptyMessage} revision={revision} directorFiles={directorFiles || []} storyboardDocument={current.storyboards?.[selectedScene]?.doc} />
      : <div className="scene-empty" role="status"><h3>暂无可显示的场次</h3><p className="muted">{emptyMessage}</p></div>}
  </div> : <>
    <div ref={cards} className="episode-grid">{items.slice((page - 1) * 36, page * 36).map(item => <EpisodeButton key={item.key} item={item} onSelect={open} />)}</div>
    {!items.length && <p className="muted">尚无剧集制作目录。</p>}
    <Pagination page={page} total={items.length} change={setPage} />
  </>;
}
