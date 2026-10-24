import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { get, projectUrl } from '../api';
import type { FileItem, RecordData, SceneRound, DirectorSheets } from '../api';
import { Document, Result } from '../components';
import { UnderlineTabs } from './UnderlineTabs';
import { latestVideo, missingVideoState, selectedRevision } from './SegmentVideo';
import { SegmentWorkspace } from './SegmentWorkspace';
import { useRevisionNotesExport } from './RevisionNotes';
import { useSceneVideoCache } from './useSceneVideoCache';
import type { NoteScope, ReviewVersions } from './RevisionNotes';
import { useRefreshState } from '../refreshPosition';
import { SceneStoryboardEditor } from './SceneStoryboardEditor';
import { SceneDirectorSheets } from './SceneDirectorSheets';
import { SceneDownloads } from './SceneDownloads';
import { SegmentStageStrip } from './SegmentStageStrip';
import { TabSelect } from './TabSelect';
import { MessagePanel } from './MessagePanel';
import { PointerTooltip } from './PointerTooltip';
import './LatestSelection.css';
import { PREVIOUS_ENDING } from '../previousEpisodeEnding';
import type { PreviousEpisodeEnding } from '../previousEpisodeEnding';

type Segments = NonNullable<FileItem['segments']>[string];
type Selection = { stage: string; key: string };
type ReviewRound = { stage: string; order: string[]; versions: ReviewVersions };

export function SceneWorkspace({ scope, segments: allSegments, sceneRounds = [], selectedRound, onRoundChange, previousEnding, emptyMessage, revision, storyboardDocument, directorSheets, storyboardVersion }: { scope: NoteScope; segments: Segments; sceneRounds?: SceneRound[]; selectedRound?: number; onRoundChange: (number: number) => void; previousEnding: PreviousEpisodeEnding | null; emptyMessage: string; revision: number; directorFiles: FileItem[]; storyboardDocument?: RecordData; directorSheets?: DirectorSheets; storyboardVersion: string }) {
  const { scene } = scope;
  const productionRound = sceneRounds.find(item => item.number === selectedRound);
  const latestRound = sceneRounds.at(-1);
  const newVideoSegments = new Set((productionRound?.segments || []).filter(entry =>
    allSegments.find(item => item.id === entry.id)?.videos.some(video => video.stage === entry.stage && video.run === entry.run && video.url)
    && !sceneRounds.some(round => round.number < productionRound!.number
      && round.segments.some(previous => previous.id === entry.id && previous.stage === entry.stage && previous.run === entry.run))
  ).map(entry => entry.id));
  const segments = productionRound ? productionRound.segments.map(entry => ({ ...allSegments.find(item => item.id === entry.id)!, ...entry })) : allSegments.filter(item => !item.historical);
  const queryClient = useQueryClient();
  const positionKey = `scene/${scope.project}/${scope.episode}/${scene}`;
  const [view, setView] = useRefreshState(positionKey + '/view', 'segments');
  const storyboardPath = `09-剧集制作/${scope.episode}/03-分镜脚本/${scope.episode}-${scene}-场次分镜.md`;
  const storyboard = useQuery({ queryKey: ['document', scope.project, storyboardPath, revision], queryFn: () => get<RecordData>(`${projectUrl(scope.project)}/document?path=${encodeURIComponent(storyboardPath)}`), enabled: view === 'storyboard' && !!scene && !storyboardDocument && !productionRound, placeholderData: previous => previous });
  const previousVideo = latestVideo(previousEnding?.segment?.videos.filter(video => video.url) || []);
  const [requestedSegment, setSegment] = useRefreshState(positionKey + '/segment', segments[0]?.id || '');
  const viewingPrevious = requestedSegment === PREVIOUS_ENDING && !!previousVideo;
  const segment = viewingPrevious ? PREVIOUS_ENDING : segments.some(item => item.id === requestedSegment) ? requestedSegment : segments[0]?.id || '';
  const displayScope = viewingPrevious ? { ...scope, episode: previousEnding!.episode, scene: previousEnding!.scene } : scope;
  const [selections, setSelections] = useRefreshState<Record<string, Selection>>(positionKey + (productionRound ? `/round/${productionRound.number}` : '') + '/selections', {});
  const [pendingSelection, setPendingSelection] = useState<{ round: number; segment: string; value: Selection } | null>(null);
  useEffect(() => {
    if (pendingSelection?.round === productionRound?.number && pendingSelection) {
      setSelections(previous => ({ ...previous, [pendingSelection.segment]: pendingSelection.value }));
      setPendingSelection(null);
    }
  }, [pendingSelection, productionRound?.number]);
  const fixedVersions: ReviewVersions = Object.fromEntries((productionRound?.segments || []).map(entry => {
    const video = allSegments.find(item => item.id === entry.id)?.videos.find(video => video.stage === entry.stage && video.run === entry.run);
    return [entry.id, video ? { stage: video.stage, run: video.run, key: video.key } : null];
  }));
  const roundStages = new Set(productionRound?.segments.map(entry => entry.stage));
  const reviewRound: (ReviewRound & { label?: string }) | null = productionRound ? { stage: roundStages.size === 1 ? productionRound.segments[0].stage : '混合阶段',
    label: `第${productionRound.number}轮`, order: productionRound.segments.map(entry => entry.id), versions: fixedVersions } : null;
  const [continuous, setContinuous] = useState(false);
  const [wideVideo, setWideVideo] = useRefreshState(positionKey + '/wideVideo', false);
  const [segmentTab, setSegmentTab] = useRefreshState(positionKey + '/segmentTab', 'script');
  const [autoPlay, setAutoPlay] = useState(false);
  const [error, setError] = useState<{ message: string; unavailable: boolean } | null>(null);
  const currentSegment = viewingPrevious ? previousEnding!.segment : segments.find(item => item.id === segment);
  const latest = viewingPrevious ? previousVideo : currentSegment && latestVideo(currentSegment.videos);
  const roundEntry = productionRound?.segments.find(item => item.id === segment);
  const roundDefault = roundEntry && currentSegment?.videos.find(video => video.stage === roundEntry.stage && video.run === roundEntry.run);
  const savedSelection = pendingSelection?.round === productionRound?.number && pendingSelection?.segment === segment
    ? pendingSelection.value : selections[segment];
  const savedRevision = savedSelection && currentSegment && selectedRevision(currentSegment.videos, savedSelection);
  const chosen = savedRevision ? { stage: savedRevision.stage, key: savedRevision.key }
    : savedSelection && (!savedSelection.key || reviewRound) ? savedSelection : { stage: roundDefault?.stage || latest?.stage || '', key: roundDefault?.key || latest?.key || '' };
  const viewingRoundRevision = roundEntry && currentSegment && selectedRevision(currentSegment.videos, chosen)?.run === roundEntry.run && chosen.stage === roundEntry.stage;
  const notesExport = useRevisionNotesExport(displayScope, viewingPrevious ? previousEnding!.segments : segments, reviewRound && {
    stage: reviewRound.stage, label: reviewRound.label, number: viewingPrevious ? undefined : productionRound?.number,
    versions: viewingPrevious ? { [currentSegment!.id]: reviewRound.versions[PREVIOUS_ENDING] ?? null } : productionRound
      ? Object.fromEntries(productionRound.segments.map(entry => [entry.id, { stage: entry.stage, run: entry.run, key: fixedVersions[entry.id]?.key || '' }])) : reviewRound.versions,
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
  const roundVideoIssue = (id: string) => {
    const version = reviewRound?.versions[id] || productionRound?.segments.find(entry => entry.id === id);
    const issue = missingVideoState(roundVideo(id), version && 'key' in version ? version.key : '');
    return { ...issue, message: `${id === PREVIOUS_ENDING ? '上集末段' : id}的本轮${version?.stage || reviewRound?.stage || ''}${version ? ` ${version.run}` : ''}${issue.message}` };
  };
  const missingRoundVideos = productionRound ? productionRound.segments.filter(entry => !roundVideo(entry.id)?.url).length : 0;
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
  const toggleContinuous = (checked: boolean) => {
    setAutoPlay(false);
    if (!checked) { setContinuous(false); return; }
    if (!reviewRound) { setContinuous(false); return; }
    const video = roundVideo(segment);
    if (!video?.url || selectedRevision(currentSegment!.videos, chosen)?.key !== video.key) { setContinuous(false); setError(null); return; }
    setContinuous(true);
    setError(null);
  };
  useEffect(() => {
    setSelections(previous => {
      const arriving = segments.filter(item => !previous[item.id] && item.videos.length).map(item => {
        const latest = reviewRound ? roundVideo(item.id) : latestVideo(item.videos);
        return [item.id, { stage: latest?.stage || reviewRound!.stage, key: latest?.key || '' }];
      });
      return arriving.length ? { ...previous, ...Object.fromEntries(arriving) } : previous;
    });
  }, [segments, reviewRound]);
  const advance = () => {
    const next = reviewRound?.order[reviewRound.order.indexOf(segment) + 1];
    if (!continuous || !next) { setAutoPlay(false); return; }
    const video = roundVideo(next);
    if (!video?.url) { const issue = roundVideoIssue(next); setAutoPlay(false); setError({ ...issue, message: `${issue.message}连续播放已停在当前分段；不会换用其他版本。` }); return; }
    setSelections(previous => ({ ...previous, [next]: { stage: video.stage, key: video.key } }));
    setError(null);
    setSegment(next);
    setAutoPlay(true);
  };
  const selectSegment = (id: string) => {
    if (reviewRound && id !== PREVIOUS_ENDING) {
      const video = roundVideo(id);
      setSelections(previous => ({ ...previous, [id]: { stage: video?.stage || reviewRound.stage, key: video?.key || '' } }));
    }
    setAutoPlay(false); setSegment(id); setError(null);
  };
  const selectPrevious = () => {
    setSelections(previous => ({ ...previous, [PREVIOUS_ENDING]: { stage: previousVideo!.stage, key: previousVideo!.key } }));
    selectSegment(PREVIOUS_ENDING);
  };
  const navigation = (vertical = false) => <SegmentStageStrip vertical={vertical} segments={segments} selected={segment} newVideoSegments={newVideoSegments}
    previousEnding={previousEnding} previousSelected={viewingPrevious} onPreviousSelect={selectPrevious} onSelect={selectSegment} />;
  const changeRound = (number: number, keepSegment = false) => {
    const next = sceneRounds.find(item => item.number === number)!;
    setAutoPlay(false); setContinuous(false); setError(null);
    setPendingSelection(null); setSelections({}); setSegment(keepSegment ? segment : next.segments[0].id); onRoundChange(number);
  };
  const changeSelection = (value: Selection) => {
    setContinuous(false); setAutoPlay(false); setError(null);
    const video = value.key && !viewingPrevious && selectedRevision(currentSegment!.videos, value);
    const matchingRound = video && sceneRounds.reduce<SceneRound | undefined>((latest, round) =>
      round.segments.some(entry => entry.id === segment && entry.stage === video.stage && entry.run === video.run)
        && (!latest || round.number > latest.number) ? round : latest, undefined);
    if (matchingRound) {
      changeRound(matchingRound.number, true);
      setPendingSelection({ round: matchingRound.number, segment, value });
      return;
    }
    setSelections(previous => ({ ...previous, [segment]: value }));
  };
  return <>
    <div className="scene-workspace-tabs">
      <UnderlineTabs label="场次内容" items={[{ value: 'segments', label: '分段制作' }, { value: 'storyboard', label: '场次分镜' }, { value: 'director-sheets', label: '导演分镜表' }, { value: 'dialogue', label: '分镜修改' }, { value: 'downloads', label: '资源下载' }]} selected={view} onChange={value => { setAutoPlay(false); setView(value); }} />
    {sceneRounds.length > 0 && <div className="scene-round-selector">
      <span className="production-latest">当前最新{selectedRound !== latestRound!.number && <>：第{latestRound!.number}轮：剧本{latestRound!.script?.version || '缺失'} · 分镜{latestRound!.storyboard?.version || '缺失'}，<button className="production-latest-link" aria-label="切换到最新修改轮次" onClick={() => changeRound(latestRound!.number)}>点击切换</button></>}</span>
      <TabSelect size="toolbar" highlightSelected label="场次修改轮次" selected={String(selectedRound)} onChange={value => changeRound(Number(value))}
        items={[...sceneRounds].reverse().map(item => ({ value: String(item.number),
          label: `第${item.number}轮：剧本${item.script?.version || '缺失'} · 分镜${item.storyboard?.version || '缺失'}` }))} />
    </div>}
    </div>
    <div className="episode-scene-content" aria-label={scene ? `场次 ${scene} 内容` : '场次内容'}>
    {view === 'segments' && <>
    {segments.length === 0 ? <div className="scene-empty" role="status"><h3>{scene ? '暂无可显示的分段' : '暂无可显示的场次'}</h3><p className="muted">{emptyMessage}</p></div> : null}
    {!wideVideo && (segments.length > 0 || previousEnding) && navigation()}
    {!wideVideo && (videoCache.total > 0 || productionRound) && <PointerTooltip text={videoCache.failures.join('\n')}><p className="scene-video-preparation" role="status">
      {productionRound ? `第${productionRound.number}轮视频已准备 ${videoCache.ready}／${productionRound.segments.length}${missingRoundVideos ? `，${missingRoundVideos}段尚无可播放视频` : ''}${videoCache.failures.length ? `，${videoCache.failures.length}个准备失败` : ''}` : videoCache.failures.length ? `${reviewRound ? '本轮' : '最新'}视频已准备 ${videoCache.ready}／${videoCache.total}，${videoCache.failures.length}个准备失败`
        : videoCache.ready === videoCache.total ? `${reviewRound ? '本轮' : '最新'}视频已全部准备好` : `${reviewRound ? '本轮' : '最新'}视频已准备 ${videoCache.ready}／${videoCache.total}`}{(reviewRound ? !!roundVideo(PREVIOUS_ENDING)?.url : !!previousVideo) ? '（含上集末段）' : ''}
    </p></PointerTooltip>}
    </>}
    <MessagePanel label="场次提示" messages={[
      !!productionRound?.issues.length && { id: 'round-issues', tone: 'error', content: `${productionRound.issues.join('；')}；不会换用当前文档。` },
      view === 'segments' && !!reviewRound && !!(savedRevision && reviewRound.versions[segment]?.key !== savedRevision.key) && {
        id: 'review-round', content: savedRevision && reviewRound.versions[segment]?.key !== savedRevision.key
          ? productionRound && !viewingPrevious ? `该版本未登记整场轮次，不能连续播放；导出仍按第${productionRound.number}轮。` : '当前查看版本不属于本轮，导出仍按本轮版本。' : null,
      },
      view === 'segments' && !productionRound && !viewingPrevious && !!currentSegment && { id: 'round-missing', content: '本场尚未登记整场轮次，不能连续播放。' },
      view === 'segments' && !!error && { id: 'playback', tone: error.unavailable ? 'error' : 'info', content: error.message },
      view === 'segments' && viewingPrevious && { id: 'previous-ending', content: <>上集末段{productionRound ? '（接续参考，不属于本场修改轮次）' : ''} · {previousEnding!.episode} · {previousEnding!.scene} · {currentSegment!.id}，点击本集分段返回</> },
      view === 'segments' && segments.some((item, index) => index > 0 && Number(item.id.slice(1)) < Number(segments[index - 1].id.slice(1))) && { id: 'segment-order', content: '分段按分镜索引中的剧情顺序排列，编号保留原标识。' },
      view === 'storyboard' && !!productionRound && !storyboardDocument && { id: 'storyboard-missing', tone: 'error', content: '本轮分镜文件不可用，请核对轮次资料。' },
      view === 'dialogue' && !!productionRound && productionRound.number !== sceneRounds.at(-1)?.number && { id: 'historical-round', content: '当前为历史轮次，请切换到最新修改轮次后编辑。' },
    ]} />
    {view === 'segments' ? <>
    {currentSegment && <SegmentWorkspace key={`${displayScope.episode}/${displayScope.scene}/${currentSegment.id}`} scope={displayScope} roundNumber={viewingPrevious ? undefined : productionRound?.number} segment={currentSegment.id} revision={revision} items={currentSegment.videos} selection={chosen} cachedSources={videoCache.sources} retainSource={videoCache.retainSource}
      tab={segmentTab} onTabChange={setSegmentTab}
      plannedScript={viewingRoundRevision ? { html: roundEntry.scriptHtml, url: roundEntry.scriptUrl,
        label: `第${productionRound!.number}轮保存的分镜${productionRound!.storyboard ? `（${productionRound!.storyboard.version}）` : ''}` } : undefined}
      segmentNavigation={navigation(true)}
      wideVideo={wideVideo} onToggleWide={() => setWideVideo(value => !value)}
      continuous={continuous}
      continuousControl={<label className="scene-continuous"><input type="checkbox" checked={continuous} disabled={!chosen.stage || !productionRound || !viewingRoundRevision} onChange={event => toggleContinuous(event.target.checked)} />连续播放</label>}
      autoPlay={autoPlay} onVideoError={() => setAutoPlay(false)} onVideoEnded={advance}
      onSelectionChange={changeSelection}
      notesExportControl={notesExport.control} />}
    {notesExport.dialog}
    </> : view === 'storyboard' ? <div className="scene-storyboard">
      {!scene ? <p className="muted">本集尚无场次分镜。</p> : <>
        {!storyboardDocument && !productionRound && <Result loading={storyboard.isPending} error={storyboard.error} retry={storyboard.refetch} retrying={storyboard.isFetching} />}
        {(storyboardDocument || (!productionRound && storyboard.data)) && <Document key={productionRound?.number || 'current'} value={storyboardDocument || storyboard.data!} />}
      </>}
    </div> : view === 'director-sheets' ? <SceneDirectorSheets key={positionKey + '/' + storyboardVersion} sheets={directorSheets} storyboardVersion={storyboardVersion} revision={revision} /> : view === 'dialogue' ? productionRound && productionRound.number !== sceneRounds.at(-1)?.number ? null : <SceneStoryboardEditor key={positionKey} scope={scope} segments={segments} /> : <SceneDownloads project={scope.project} episode={scope.episode} scene={scene} revision={revision} />}
  </div></>;
}
