import { PointerTooltip } from './PointerTooltip';
import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { get, projectUrl } from '../api';
import type { FileItem, RecordData } from '../api';
import { Document, Result } from '../components';
import { UnderlineTabs } from './UnderlineTabs';
import { latestVideo, selectedRevision } from './SegmentVideo';
import { SegmentWorkspace } from './SegmentWorkspace';
import { useRevisionNotesExport } from './RevisionNotes';
import { useSceneVideoCache } from './useSceneVideoCache';
import type { NoteScope, ReviewVersions } from './RevisionNotes';
import { useRefreshState } from '../refreshPosition';
import { SceneStoryboardEditor } from './SceneStoryboardEditor';
import { SceneDownloads } from './SceneDownloads';
import { SegmentStageStrip } from './SegmentStageStrip';
import { PREVIOUS_ENDING } from '../previousEpisodeEnding';
import type { PreviousEpisodeEnding } from '../previousEpisodeEnding';

type Segments = NonNullable<FileItem['segments']>[string];
type Selection = { stage: string; key: string };
type ReviewRound = { stage: string; order: string[]; versions: ReviewVersions };

export function SceneWorkspace({ scope, segments, previousEnding, emptyMessage, revision, storyboardDocument }: { scope: NoteScope; segments: Segments; previousEnding: PreviousEpisodeEnding | null; emptyMessage: string; revision: number; directorFiles: FileItem[]; storyboardDocument?: RecordData }) {
  const { scene } = scope;
  const queryClient = useQueryClient();
  const positionKey = `scene/${scope.project}/${scope.episode}/${scene}`;
  const [view, setView] = useRefreshState(positionKey + '/view', 'segments');
  const storyboardPath = `09-剧集制作/${scope.episode}/03-分镜脚本/${scope.episode}-${scene}-场次分镜.md`;
  const storyboard = useQuery({ queryKey: ['document', scope.project, storyboardPath, revision], queryFn: () => get<RecordData>(`${projectUrl(scope.project)}/document?path=${encodeURIComponent(storyboardPath)}`), enabled: view === 'storyboard' && !!scene && !storyboardDocument, placeholderData: previous => previous });
  const previousVideo = latestVideo(previousEnding?.segment?.videos.filter(video => video.url) || []);
  const [requestedSegment, setSegment] = useRefreshState(positionKey + '/segment', segments[0]?.id || '');
  const viewingPrevious = requestedSegment === PREVIOUS_ENDING && !!previousVideo;
  const segment = viewingPrevious ? PREVIOUS_ENDING : segments.some(item => item.id === requestedSegment) ? requestedSegment : segments[0]?.id || '';
  const displayScope = viewingPrevious ? { ...scope, episode: previousEnding!.episode, scene: previousEnding!.scene } : scope;
  const [selections, setSelections] = useRefreshState<Record<string, Selection>>(positionKey + '/selections', {});
  const [reviewRound, setReviewRound] = useRefreshState<ReviewRound | null>(positionKey + '/reviewRound', null);
  const [continuous, setContinuous] = useState(false);
  const [wideVideo, setWideVideo] = useRefreshState(positionKey + '/wideVideo', false);
  const [segmentTab, setSegmentTab] = useRefreshState(positionKey + '/segmentTab', 'script');
  const [autoPlay, setAutoPlay] = useState(false);
  const [error, setError] = useState('');
  const currentSegment = viewingPrevious ? previousEnding!.segment : segments.find(item => item.id === segment);
  const latest = viewingPrevious ? previousVideo : currentSegment && latestVideo(currentSegment.videos);
  const savedSelection = selections[segment];
  const savedRevision = savedSelection && currentSegment && selectedRevision(currentSegment.videos, savedSelection);
  const chosen = savedRevision ? { stage: savedRevision.stage, key: savedRevision.key }
    : savedSelection && (!savedSelection.key || reviewRound) ? savedSelection : { stage: latest?.stage || '', key: latest?.key || '' };
  const notesExport = useRevisionNotesExport(displayScope, viewingPrevious ? previousEnding!.segments : segments, reviewRound && {
    stage: reviewRound.stage,
    versions: viewingPrevious ? { [currentSegment!.id]: reviewRound.versions[PREVIOUS_ENDING] ?? null } : reviewRound.versions,
  }, viewingPrevious ? async () => {
    const item = await queryClient.fetchQuery({ queryKey: ['episode', scope.project, displayScope.episode, revision],
      queryFn: () => get<FileItem>(`${projectUrl(scope.project)}/episodes/${displayScope.episode}`) });
    return item.segments?.[displayScope.scene] || [];
  } : undefined);
  const roundVideo = (id: string) => {
    const fixed = reviewRound?.versions[id];
    const items = id === PREVIOUS_ENDING ? previousEnding?.segment?.videos : segments.find(item => item.id === id)?.videos;
    return fixed && items ? selectedRevision(items, fixed) : undefined;
  };
  const preparationOrder = reviewRound?.order || [
    ...(previousVideo ? [PREVIOUS_ENDING] : []), ...segments.map(item => item.id),
  ];
  const preparationVideos = reviewRound ? reviewRound.order.flatMap(id => {
    const video = roundVideo(id);
    return video?.url ? [video] : [];
  }) : [
    ...(previousVideo ? [previousVideo] : []),
    ...segments.flatMap(item => {
      const video = latestVideo(item.videos);
      return video?.url ? [video] : [];
    }),
  ];
  const priorityVideos = [segment, preparationOrder[preparationOrder.indexOf(segment) + 1]].flatMap(id => {
    const video = reviewRound ? roundVideo(id) : id === PREVIOUS_ENDING ? previousVideo
      : latestVideo(segments.find(item => item.id === id)?.videos || []);
    return video?.url ? [video.url] : [];
  });
  const videoCache = useSceneVideoCache(preparationVideos, priorityVideos);
  const beginReview = (playContinuously: boolean) => {
    const entries = [
      ...(previousEnding?.segment ? [{ id: PREVIOUS_ENDING, videos: previousEnding.segment.videos }] : []),
      ...segments,
    ];
    const versions: ReviewVersions = Object.fromEntries(entries.map(item => {
      const video = latestVideo(item.videos.filter(video => video.stage === chosen.stage && video.url));
      return [item.id, video ? { stage: video.stage, run: video.run, key: video.key } : null];
    }));
    setReviewRound({ stage: chosen.stage, order: entries.map(item => item.id), versions });
    setSelections(previous => ({ ...previous, ...Object.fromEntries(entries.map(item => [item.id, { stage: chosen.stage, key: versions[item.id]?.key || '' }])) }));
    setAutoPlay(false);
    setContinuous(playContinuously && !!versions[segment]);
    setError(versions[segment] ? '' : `${viewingPrevious ? '上集末段' : segment}暂无${chosen.stage}可播放视频，本轮不会换用其他画质。`);
  };
  const toggleContinuous = (checked: boolean) => {
    setAutoPlay(false);
    if (!checked) { setContinuous(false); return; }
    if (!reviewRound) { beginReview(true); return; }
    const video = roundVideo(segment);
    if (!video?.url) { setContinuous(false); setError(`${viewingPrevious ? '上集末段' : segment}的本轮${reviewRound.stage}视频不可播放，请检查或开始新一轮。`); return; }
    setSelections(previous => ({ ...previous, [segment]: { stage: video.stage, key: video.key } }));
    setContinuous(true);
    setError('');
  };
  useEffect(() => {
    setSelections(previous => {
      const arriving = segments.filter(item => !previous[item.id] && item.videos.length).map(item => {
        const latest = reviewRound ? roundVideo(item.id) : latestVideo(item.videos);
        return [item.id, { stage: reviewRound?.stage || latest!.stage, key: latest?.key || '' }];
      });
      return arriving.length ? { ...previous, ...Object.fromEntries(arriving) } : previous;
    });
  }, [segments, reviewRound]);
  const advance = () => {
    const next = reviewRound?.order[reviewRound.order.indexOf(segment) + 1];
    if (!continuous || !next) { setAutoPlay(false); return; }
    const video = roundVideo(next);
    if (!video?.url) { setAutoPlay(false); setError(`${next}的本轮${reviewRound!.stage}视频不可播放，连续播放已停在当前分段；不会换用其他版本。`); return; }
    setSelections(previous => ({ ...previous, [next]: { stage: video.stage, key: video.key } }));
    setError('');
    setSegment(next);
    setAutoPlay(true);
  };
  const selectSegment = (id: string) => {
    if (reviewRound) setSelections(previous => ({ ...previous, [id]: { stage: reviewRound.stage, key: roundVideo(id)?.key || '' } }));
    setAutoPlay(false); setSegment(id); setError('');
  };
  const selectPrevious = () => {
    if (!reviewRound) setSelections(previous => ({ ...previous, [PREVIOUS_ENDING]: { stage: previousVideo!.stage, key: previousVideo!.key } }));
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
      {videoCache.failures.length ? `${reviewRound ? '本轮' : '最新'}视频已准备 ${videoCache.ready}／${videoCache.total}，${videoCache.failures.length}个准备失败`
        : videoCache.ready === videoCache.total ? `${reviewRound ? '本轮' : '最新'}视频已全部准备好` : `${reviewRound ? '本轮' : '最新'}视频已准备 ${videoCache.ready}／${videoCache.total}`}{(reviewRound ? !!roundVideo(PREVIOUS_ENDING)?.url : !!previousVideo) ? '（含上集末段）' : ''}
    </p></PointerTooltip>}
    <div className="scene-review-round">
      <span role="status">{reviewRound ? `本轮${reviewRound.stage}版本已固定；暂停连播后仍保留。${reviewRound.order.filter(id => !reviewRound.versions[id]).length ? '部分分段暂无本轮视频。' : ''}` : '开启连续播放，将固定当前画质下各段最新可播放候选。'}</span>
      {reviewRound && <button disabled={!chosen.stage} onClick={() => beginReview(false)}>开始新一轮</button>}
      {reviewRound && savedRevision && reviewRound.versions[segment]?.key !== savedRevision.key && <span>当前查看版本不属于本轮，导出仍按本轮版本。</span>}
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    {reviewRound?.versions[segment] && !roundVideo(segment)?.url && <p className="error" role="alert">{viewingPrevious ? '上集末段' : segment}的本轮{reviewRound.stage} {reviewRound.versions[segment]!.run}视频已不可播放，请检查或开始新一轮；不会自动换用其他版本。</p>}
    {viewingPrevious && <p className="previous-ending-context">上集末段 · {previousEnding!.episode} · {previousEnding!.scene} · {currentSegment!.id} <span>点击本集分段返回</span></p>}
    {currentSegment && <SegmentWorkspace key={`${displayScope.episode}/${displayScope.scene}/${currentSegment.id}`} scope={displayScope} segment={currentSegment.id} revision={revision} items={currentSegment.videos} selection={chosen} cachedSources={videoCache.sources} retainSource={videoCache.retainSource}
      tab={segmentTab} onTabChange={setSegmentTab}
      segmentNavigation={navigation(true)}
      wideVideo={wideVideo} onToggleWide={() => setWideVideo(value => !value)}
      continuousControl={<label className="scene-continuous"><input type="checkbox" checked={continuous} disabled={!chosen.stage} onChange={event => toggleContinuous(event.target.checked)} />连续播放</label>}
      autoPlay={autoPlay} onVideoError={() => setAutoPlay(false)} onVideoEnded={advance}
      onSelectionChange={value => { setContinuous(false); setAutoPlay(false); setError(''); setSelections(previous => ({ ...previous, [segment]: value })); }}
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
