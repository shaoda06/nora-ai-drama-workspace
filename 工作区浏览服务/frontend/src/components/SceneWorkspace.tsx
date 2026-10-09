import { useEffect, useState } from 'react';
import type { CSSProperties } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get, projectUrl } from '../api';
import type { FileItem, RecordData } from '../api';
import { Document, Result, Rich } from '../components';
import { UnderlineTabs } from './UnderlineTabs';
import { latestVideo } from './SegmentVideo';
import { SegmentWorkspace } from './SegmentWorkspace';
import { useRevisionNotesExport } from './RevisionNotes';
import { useSceneVideoCache } from './useSceneVideoCache';
import type { NoteScope } from './RevisionNotes';
import { useRefreshState } from '../refreshPosition';

type Segments = NonNullable<FileItem['segments']>[string];
type Selection = { stage: string; key: string };

export function SceneWorkspace({ scope, segments, revision }: { scope: NoteScope; segments: Segments; revision: number }) {
  const { scene } = scope;
  const positionKey = `scene/${scope.project}/${scope.episode}/${scene}`;
  const [view, setView] = useRefreshState(positionKey + '/view', 'segments');
  const storyboardPath = `09-剧集制作/${scope.episode}/03-分镜脚本/${scope.episode}-${scene}-场次分镜.md`;
  const storyboard = useQuery({ queryKey: ['document', scope.project, storyboardPath, revision], queryFn: () => get<RecordData>(`${projectUrl(scope.project)}/document?path=${encodeURIComponent(storyboardPath)}`), enabled: view === 'storyboard' && !!scene, placeholderData: previous => previous });
  const notesExport = useRevisionNotesExport(scope, segments);
  const videoCache = useSceneVideoCache(segments.flatMap(item => {
    const video = latestVideo(item.videos);
    return video ? [video] : [];
  }));
  const [requestedSegment, setSegment] = useRefreshState(positionKey + '/segment', segments[0]?.id || '');
  const segment = segments.some(item => item.id === requestedSegment) ? requestedSegment : segments[0]?.id || '';
  const [selections, setSelections] = useRefreshState<Record<string, Selection>>(positionKey + '/selections', {});
  const [continuous, setContinuous] = useState(false);
  const [autoPlay, setAutoPlay] = useState(false);
  const [error, setError] = useState('');
  const currentSegment = segments.find(item => item.id === segment);
  const latest = currentSegment && latestVideo(currentSegment.videos);
  const savedSelection = selections[segment];
  const chosen = savedSelection && (!savedSelection.key || currentSegment?.videos.some(video => video.stage === savedSelection.stage && video.key === savedSelection.key))
    ? savedSelection : { stage: latest?.stage || '', key: latest?.key || '' };
  useEffect(() => {
    setSelections(previous => {
      const arriving = segments.filter(item => !previous[item.id] && item.videos.length).map(item => {
        const latest = latestVideo(item.videos)!;
        return [item.id, { stage: latest.stage, key: latest.key }];
      });
      return arriving.length ? { ...previous, ...Object.fromEntries(arriving) } : previous;
    });
  }, [segments]);
  const advance = () => {
    const next = segments[segments.findIndex(item => item.id === segment) + 1];
    if (!continuous || !next) { setAutoPlay(false); return; }
    const selected = selections[next.id];
    const video = selected ? next.videos.find(item => item.stage === selected.stage && item.key === selected.key) : latestVideo(next.videos);
    if (!video) { setAutoPlay(false); setError(`${next.id}尚未选定可播放的画质和版本，连续播放已停在当前分段。`); return; }
    setError('');
    setSegment(next.id);
    setAutoPlay(true);
  };
  return <>
    <div className="scene-workspace-tabs"><UnderlineTabs label="场次内容" items={[{ value: 'segments', label: '分段制作' }, { value: 'storyboard', label: '场次分镜' }, { value: 'dialogue', label: '分镜修改' }, { value: 'downloads', label: '资源下载' }]} selected={view} onChange={value => { setAutoPlay(false); setView(value); }} /></div>
    <div className="episode-scene-content" aria-label={scene ? `场次 ${scene} 内容` : '场次内容'}>
    {view === 'segments' ? <>
    {segments.some((item, index) => index > 0 && Number(item.id.slice(1)) < Number(segments[index - 1].id.slice(1))) && <p className="segment-order-note muted">分段按分镜索引中的剧情顺序排列，编号保留原标识。</p>}
    {segments.length > 0 && <div className="segment-scroll"><div className="segment-strip" role="group" aria-label="本场分段" style={{ '--segment-columns': segments.map(item => `minmax(0, ${item.duration}fr)`).join(' ') } as CSSProperties}>
      {segments.map(item => <button key={item.id} aria-label={`分段 ${item.id}，计划时长 ${item.duration}秒`} title={`${item.id} · 计划时长 ${item.duration}秒`} aria-pressed={item.id === segment} onClick={() => { setAutoPlay(false); setSegment(item.id); setError(''); }}><span>{item.id}</span><span>{item.duration}秒</span></button>)}
    </div></div>}
    {videoCache.total > 0 && <p className="scene-video-preparation" role="status" title={videoCache.failures.join('\n')}>
      {videoCache.failures.length ? `最新视频已准备 ${videoCache.ready}／${videoCache.total}，${videoCache.failures.length}个准备失败`
        : videoCache.ready === videoCache.total ? '本场最新视频已全部准备好' : `最新视频已准备 ${videoCache.ready}／${videoCache.total}`}
    </p>}
    {error && <p className="error" role="alert">{error}</p>}
    {currentSegment && <SegmentWorkspace key={segment} scope={scope} segment={segment} items={currentSegment.videos} selection={chosen} cachedSources={videoCache.sources}
      autoPlay={autoPlay} onVideoError={() => setAutoPlay(false)} onVideoEnded={advance}
      onSelectionChange={value => { setAutoPlay(false); setError(''); setSelections(previous => ({ ...previous, [segment]: value })); }}
      playbackControl={<div className="scene-review-actions"><label className="scene-continuous"><input type="checkbox" checked={continuous} onChange={event => setContinuous(event.target.checked)} />连续播放</label>{notesExport.control}</div>} />}
    {notesExport.dialog}
    </> : view === 'storyboard' ? <div className="scene-storyboard">
      {!scene ? <p className="muted">本集尚无场次分镜。</p> : <>
        <Result loading={storyboard.isPending} error={storyboard.error} retry={storyboard.refetch} retrying={storyboard.isFetching} />
        {storyboard.data && <Document value={storyboard.data} />}
      </>}
    </div> : view === 'dialogue' ? <div className="scene-revision-layout">
      <section className="scene-revision-pane" aria-label="当前场次分镜正文">
        {segments.map(item => <div className="scene-revision-segment" key={item.id}><h3>分段 {item.id}</h3><Rich html={item.scriptHtml} /></div>)}
      </section>
      <section className="scene-revision-pane" aria-label="分镜修改预留区域" />
    </div> : null}
  </div></>;
}
