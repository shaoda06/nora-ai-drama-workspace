import { useContext, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import type { FileItem } from '../api';
import { PreviewContext } from '../components';
import { TabNav } from './TabNav';
import { Pagination } from './Pagination';
import { EpisodeButton } from './EpisodeButton';
import { SceneWorkspace } from './SceneWorkspace';
import { useRefreshState } from '../refreshPosition';
import { BreadcrumbActionsContext } from './Breadcrumbs';
import { projectUrl } from '../api';
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
  const current = items.find(item => item.name === selected);
  useEffect(() => {
    if (selected && !current) onSelect(null);
  }, [selected, current, onSelect]);
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
  return current ? <div className="episode-detail">
    {breadcrumbActions && episodeComplete && createPortal(<a className="stage-download-link" download
      href={`${projectUrl(project)}/episodes/${current.name}/download`}
      title={`下载${current.name}全部${scenes.length}个场次、${segmentCount}段后处理正式版视频`}>打包下载本集内容</a>, breadcrumbActions)}
    <div className="episode-scene-header">
      {scenes.length > 0 && <TabNav label="本集场次" items={scenes.map(id => ({ value: id, label: '场次 ' + id }))} selected={selectedScene} onChange={setScene} />}
      <button className="link episode-script-link" disabled={!script} title={script ? undefined : '本集剧本尚未建立'} onClick={() => preview(script!)}>查看本集剧本</button>
    </div>
    {issues.length > 0 ? <div className="notice episode-data-issues" role="alert">
      <strong>制作资料需要修正</strong>
      <ul>{issues.map((issue, index) => <li key={index}>
        <button className="link" title={issue.key} onClick={() => preview({ kind: 'document', key: issue.key, name: issue.key.split('/').pop()! })}>{issue.key.split('/').pop()}</button>：{issue.message}
      </li>)}</ul>
    </div> : null}
    {selectedScene ? <SceneWorkspace key={current.name + '/' + selectedScene} scope={{ project, episode: current.name, scene: selectedScene }} segments={segments} emptyMessage={emptyMessage} revision={revision} directorFiles={directorFiles || []} storyboardDocument={current.storyboards?.[selectedScene]?.doc} />
      : <div className="scene-empty" role="status"><h3>暂无可显示的场次</h3><p className="muted">{emptyMessage}</p></div>}
  </div> : <>
    <div ref={cards} className="episode-grid">{items.slice((page - 1) * 36, page * 36).map(item => <EpisodeButton key={item.key} item={item} onSelect={open} />)}</div>
    {!items.length && <p className="muted">尚无剧集制作目录。</p>}
    <Pagination page={page} total={items.length} change={setPage} />
  </>;
}
