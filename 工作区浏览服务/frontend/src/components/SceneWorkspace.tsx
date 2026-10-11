import { PointerTooltip } from './PointerTooltip';
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get, projectUrl } from '../api';
import type { FileItem, RecordData } from '../api';
import { Document, Result } from '../components';
import { UnderlineTabs } from './UnderlineTabs';
import { latestVideo, selectedRevision } from './SegmentVideo';
import { SegmentWorkspace } from './SegmentWorkspace';
import { useRevisionNotesExport } from './RevisionNotes';
import { useSceneVideoCache } from './useSceneVideoCache';
import type { NoteScope } from './RevisionNotes';
import { useRefreshState } from '../refreshPosition';
import { SceneStoryboardEditor } from './SceneStoryboardEditor';
import { SceneDownloads } from './SceneDownloads';
import { SegmentStageStrip } from './SegmentStageStrip';
import { PREVIOUS_ENDING } from '../previousEpisodeEnding';
import type { PreviousEpisodeEnding } from '../previousEpisodeEnding';

type Segments = NonNullable<FileItem['segments']>[string];
type Selection = { stage: string; key: string };

export function SceneWorkspace({ scope, segments, previousEnding, emptyMessage, revision, storyboardDocument }: { scope: NoteScope; segments: Segments; previousEnding: PreviousEpisodeEnding | null; emptyMessage: string; revision: number; directorFiles: FileItem[]; storyboardDocument?: RecordData }) {
  const { scene } = scope;
  const positionKey = `scene/${scope.project}/${scope.episode}/${scene}`;
  const [view, setView] = useRefreshState(positionKey + '/view', 'segments');
  const storyboardPath = `09-剧集制作/${scope.episode}/03-分镜脚本/${scope.episode}-${scene}-场次分镜.md`;
  const storyboard = useQuery({ queryKey: ['document', scope.project, storyboardPath, revision], queryFn: () => get<RecordData>(`${projectUrl(scope.project)}/document?path=${encodeURIComponent(storyboardPath)}`), enabled: view === 'storyboard' && !!scene && !storyboardDocument, placeholderData: previous => previous });
  const videoCache = useSceneVideoCache(segments.flatMap(item => {
    const video = latestVideo(item.videos);
    return video?.url ? [video] : [];
  }));
  const [requestedSegment, setSegment] = useRefreshState(positionKey + '/segment', segments[0]?.id || '');
  const previousVideo = latestVideo(previousEnding?.segment?.videos.filter(video => video.url) || []);
  const viewingPrevious = requestedSegment === PREVIOUS_ENDING && !!previousVideo;
  const segment = viewingPrevious ? PREVIOUS_ENDING : segments.some(item => item.id === requestedSegment) ? requestedSegment : segments[0]?.id || '';
  const displayScope = viewingPrevious ? { ...scope, episode: previousEnding!.episode, scene: previousEnding!.scene } : scope;
  const notesExport = useRevisionNotesExport(displayScope, viewingPrevious ? previousEnding!.segments : segments);
  const [selections, setSelections] = useRefreshState<Record<string, Selection>>(positionKey + '/selections', {});
  const [continuous, setContinuous] = useState(false);
  const [wideVideo, setWideVideo] = useRefreshState(positionKey + '/wideVideo', false);
  const [autoPlay, setAutoPlay] = useState(false);
  const [error, setError] = useState('');
  const currentSegment = viewingPrevious ? previousEnding!.segment : segments.find(item => item.id === segment);
  const latest = viewingPrevious ? previousVideo : currentSegment && latestVideo(currentSegment.videos);
  const savedSelection = selections[segment];
  const savedRevision = savedSelection && currentSegment && selectedRevision(currentSegment.videos, savedSelection);
  const chosen = savedRevision ? { stage: savedRevision.stage, key: savedRevision.key }
    : savedSelection && !savedSelection.key ? savedSelection : { stage: latest?.stage || '', key: latest?.key || '' };
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
    const next = viewingPrevious ? segments[0] : segments[segments.findIndex(item => item.id === segment) + 1];
    if (!continuous || !next) { setAutoPlay(false); return; }
    const selected = selections[next.id];
    const video = selected ? selectedRevision(next.videos, selected) : latestVideo(next.videos);
    if (!video?.url) { setAutoPlay(false); setError(`${next.id}尚未选定可播放的画质和版本，连续播放已停在当前分段。`); return; }
    setError('');
    setSegment(next.id);
    setAutoPlay(true);
  };
  const selectSegment = (id: string) => { setAutoPlay(false); setSegment(id); setError(''); };
  const selectPrevious = () => {
    setSelections(previous => ({ ...previous, [PREVIOUS_ENDING]: { stage: previousVideo!.stage, key: previousVideo!.key } }));
    selectSegment(PREVIOUS_ENDING);
  };
  const navigation = (vertical = false) => <SegmentStageStrip vertical={vertical} segments={segments} selected={segment}
    previousEnding={previousEnding} previousSelected={viewingPrevious} onPreviousSelect={selectPrevious} onSelect={selectSegment} />;
  return <>
    <div className="scene-workspace-tabs"><UnderlineTabs label="场次内容" items={[{ value: 'segments', label: '分段制作' }, { value: 'storyboard', label: '场次分镜' }, { value: 'dialogue', label: '分镜修改' }, { value: 'downloads', label: '资源下载' }]} selected={view} onChange={value => { setAutoPlay(false); setView(value); }} /></div>
    <div className="episode-scene-content" aria-label={scene ? `场次 ${scene} 内容` : '场次内容'}>
    {view === 'segments' ? <>
    {segments.length === 0 ? <div className="scene-empty" role="status"><h3>{scene ? '暂无可显示的分段' : '暂无可显示的场次'}</h3><p className="muted">{emptyMessage}</p></div> : null}
    {segments.some((item, index) => index > 0 && Number(item.id.slice(1)) < Number(segments[index - 1].id.slice(1))) && <p className="segment-order-note muted">分段按分镜索引中的剧情顺序排列，编号保留原标识。</p>}
    {!wideVideo && (segments.length > 0 || previousEnding) && navigation()}
    {!wideVideo && videoCache.total > 0 && <PointerTooltip text={videoCache.failures.join('\n')}><p className="scene-video-preparation" role="status" >
      {videoCache.failures.length ? `最新视频已准备 ${videoCache.ready}／${videoCache.total}，${videoCache.failures.length}个准备失败`
        : videoCache.ready === videoCache.total ? '本场最新视频已全部准备好' : `最新视频已准备 ${videoCache.ready}／${videoCache.total}`}
    </p></PointerTooltip>}
    {error && <p className="error" role="alert">{error}</p>}
    {viewingPrevious && <p className="previous-ending-context">上集末段 · {previousEnding!.episode} · {previousEnding!.scene} · {currentSegment!.id} <span>点击本集分段返回</span></p>}
    {currentSegment && <SegmentWorkspace key={`${displayScope.episode}/${displayScope.scene}/${currentSegment.id}`} scope={displayScope} segment={currentSegment.id} items={currentSegment.videos} selection={chosen} cachedSources={videoCache.sources}
      segmentNavigation={navigation(true)}
      wideVideo={wideVideo} onToggleWide={() => setWideVideo(value => !value)}
      continuousControl={<label className="scene-continuous"><input type="checkbox" checked={continuous} onChange={event => setContinuous(event.target.checked)} />连续播放</label>}
      autoPlay={autoPlay} onVideoError={() => setAutoPlay(false)} onVideoEnded={advance}
      onSelectionChange={value => { setAutoPlay(false); setError(''); setSelections(previous => ({ ...previous, [segment]: value })); }}
      notesExportControl={notesExport.control} />}
    {notesExport.dialog}
    </> : view === 'storyboard' ? <div className="scene-storyboard">
      {!scene ? <p className="muted">本集尚无场次分镜。</p> : <>
        {!storyboardDocument && <Result loading={storyboard.isPending} error={storyboard.error} retry={storyboard.refetch} retrying={storyboard.isFetching} />}
        {(storyboardDocument || storyboard.data) && <Document value={storyboardDocument || storyboard.data!} />}
      </>}
    </div> : view === 'dialogue' ? <SceneStoryboardEditor key={positionKey} scope={scope} segments={segments} /> : <SceneDownloads project={scope.project} episode={scope.episode} scene={scene} revision={revision} />}
  </div></>;
}
