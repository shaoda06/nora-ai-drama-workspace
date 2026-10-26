import { useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { GenerationContext, SegmentVideo as VideoItem } from '../api';
import { get, projectUrl } from '../api';
import { Original, PreviewContext, Rich, Result } from '../components';
import { TabNav } from './TabNav';
import { UnderlineTabs } from './UnderlineTabs';
import { TabSelect } from './TabSelect';
import { candidateLabel, latestVideo, missingVideoState, SegmentVideo } from './SegmentVideo';
import type { SegmentVideoHandle } from './SegmentVideo';
import { CopyButton } from './CopyButton';
import { PromptSections } from './PromptSections';
import { RevisionNoteEditor } from './RevisionNotes';
import type { NoteScope } from './RevisionNotes';
import { useRefreshState } from '../refreshPosition';
import { SegmentLayout } from './SegmentLayout';
import './LatestSelection.css';

function SegmentReferences({ context }: { context?: GenerationContext }) {
  const preview = useContext(PreviewContext);
  return <section className="segment-references" aria-label="参考素材区域">
    {context ? (['common', 'segment'] as const).map(group => <div className={`segment-reference-group is-${group}`} key={group}>
      <h3>{group === 'common' ? '公共参考素材' : '本组参考素材'}</h3>
      <div className="segment-reference-images">{context.references[group].map((material, index) => <figure key={index}>
        <figcaption>{material.label}</figcaption>
        {material.url ? <button className="reference-preview" onClick={() => preview({ kind: material.kind, name: material.name, url: material.url })} aria-label={`查看 ${material.label} ${material.name}`}>
          {material.kind === 'image' ? <img src={material.url} alt={material.name} loading="lazy" /> : material.kind === 'video' ? <><video src={material.url} muted preload="metadata" /><span className="reference-media-label">视频 ▶</span></> : <span className="reference-audio"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18V5l12-2v13M9 9l12-2" fill="none" stroke="currentColor" strokeWidth="2" /><circle cx="6" cy="18" r="3" fill="currentColor" /><circle cx="18" cy="16" r="3" fill="currentColor" /></svg><span>音频</span></span>}
        </button> : <p className="muted">原素材缺失</p>}
      </figure>)}{!context.references[group].length && <p className="muted">{context.issues.length ? '该次参考素材关联尚未完整记录。' : '该次未使用此类参考素材。'}</p>}</div>
    </div>) : <span className="placeholder-label">参考素材区域</span>}
  </section>;
}

export function SegmentWorkspace({ scope, segment, revision, roundNumber, items, selection: { stage, key: selected }, onSelectionChange, tab, onTabChange, notesExportControl, plannedScript, segmentNavigation, autoPlay, onVideoEnded, onVideoError, cachedSources, retainSource, wideVideo, onToggleWide, continuous = false, continuousControl }: {
  scope: NoteScope; segment: string; roundNumber?: number;
  revision: number;
  items: VideoItem[]; selection: { stage: string; key: string }; onSelectionChange: (selection: { stage: string; key: string }) => void;
  tab: string; onTabChange: (tab: string) => void;
  wideVideo: boolean; onToggleWide: () => void; continuous?: boolean; continuousControl: ReactNode;
  plannedScript?: { html: string; url?: string; label: string }; notesExportControl: ReactNode; segmentNavigation: ReactNode; autoPlay: boolean; onVideoEnded: () => void; onVideoError: () => void;
  cachedSources: Record<string, string>;
  retainSource: (source: string) => () => void;
}) {
  const positionKey = `segment/${scope.project}/${scope.episode}/${scope.scene}/${segment}`;
  const [language, setLanguage] = useRefreshState(positionKey + '/language', 'zh');
  const [scriptMode, setScriptMode] = useRefreshState(positionKey + '/scriptMode', 'aligned');
  const [playback, setPlayback] = useState({ key: '', time: 0 });
  const [loadedFile, setLoadedFile] = useState({ key: '', revision: '' });
  const scriptContent = useRef<HTMLDivElement>(null);
  const shotTimeline = useRef<HTMLDivElement>(null);
  const player = useRef<SegmentVideoHandle>(null);
  const latest = latestVideo(items.filter(item => item.stage === stage));
  const versions = items.filter(item => item.stage === stage).sort((a, b) => b.candidateNumber - a.candidateNumber);
  const current = versions.find(item => item.key === selected);
  const [productSelection, setProductSelection] = useState({ version: '', id: '' });
  const products = current?.products || [];
  const product = products.find(item => productSelection.version === current?.key && item.id === productSelection.id)
    || products.find(item => item.role === '最终产物');
  const displayVideo = current && product ? { ...current, url: product.previewUrl || product.url,
    downloadUrl: product.url, previewNote: product.previewNote, reviewFileRevision: current.fileRevision,
    fileRevision: product.fileRevision + ':' + (product.previewRevision || '') } : current;
  const identity = current && `${scope.episode}-${scope.scene}-${segment}-${current.run}-${current.stage}`;
  const detail = useQuery({ queryKey: ['generation-context', scope.project, identity, revision],
    queryFn: () => get<GenerationContext>(`${projectUrl(scope.project)}/episodes/${scope.episode}/contexts/${encodeURIComponent(identity!)}`),
    placeholderData: (previous, query) => query?.queryKey[1] === scope.project && query.queryKey[2] === identity ? previous : undefined,
    enabled: !!current && !current.context });
  const context = current?.context || (current ? detail.data : undefined);
  const awaitingGeneration = current && !current.url && !missingVideoState(current).unavailable
    && context?.issues.includes('该次生成的资料关联尚未记录。');
  const prompt = context?.prompts[language === 'zh' ? 'chinese' : 'english'];
  const scriptHtml = context?.scriptHtml || plannedScript?.html || '';
  const shots = context?.shots || [];
  const canAlign = !!current?.url && shots.length > 0 && shots.every(shot => shot.duration !== null);
  const time = playback.key === current?.key ? playback.time : 0;
  let plannedDuration = 0;
  const timedShots = canAlign ? shots.map(shot => {
    const start = plannedDuration;
    plannedDuration += shot.duration!;
    return { shot, start, end: plannedDuration };
  }) : [];
  const activeTimedShot = timedShots.find(item => time < item.end) || timedShots[timedShots.length - 1];
  const activeShot = activeTimedShot?.shot;
  const aligned = scriptMode === 'aligned' && canAlign;
  const editingNotes = tab === 'notes';
  const showShotTimeline = canAlign && (tab === 'script' || editingNotes);
  useEffect(() => {
    scriptContent.current!.scrollTop = 0;
  }, [current?.key, tab, scriptMode, tab === 'script' && aligned ? activeShot?.id : undefined]);
  useEffect(() => {
    if (!showShotTimeline) return;
    const container = shotTimeline.current!;
    const title = container.querySelector('[aria-current="step"]')!.getBoundingClientRect();
    const bounds = container.getBoundingClientRect();
    container.scrollBy({ left: title.left < bounds.left ? title.left - bounds.left : Math.max(0, title.right - bounds.right) });
  }, [tab, activeShot?.id, current?.key, showShotTimeline]);
  const selectors = <div className="segment-selectors">
      <TabSelect size="toolbar" highlightSelected label="画质选择" selected={stage} onChange={value => onSelectionChange({ stage: value, key: '' })} items={['一采', '二采', '后处理'].map(value => ({ value, label: value }))} />
      <TabSelect size="toolbar" highlightSelected label="版本切换" reselect disabled={!stage} selected={current?.key || ''} onChange={key => onSelectionChange({ stage, key })} items={versions.map(item => ({ value: item.key, label: candidateLabel(item.candidateNumber), badge: item.approved ? '已采用' : undefined }))} />
      {products.length > 1 && <TabSelect size="toolbar" highlightSelected label="产物选择" selected={product!.id} onChange={id => setProductSelection({ version: current!.key, id })} items={products.map(item => ({ value: item.id, label: item.label, badge: item.role }))} />}
      <span className="production-latest">当前最新{latest ? selected !== latest.key && <>：{candidateLabel(latest.candidateNumber)}，<button className="production-latest-link" aria-label="切换到本段最新版本" onClick={() => onSelectionChange({ stage: latest.stage, key: latest.key })}>点击切换</button></> : '：暂无版本'}</span>
    </div>;
  return <>
    {!wideVideo && selectors}
    <SegmentLayout wide={wideVideo} navigation={segmentNavigation} player={<SegmentVideo playerRef={player} selectorControl={wideVideo ? selectors : undefined} key={`${current?.key || 'empty'}/${product?.id || ''}`} wide={wideVideo} onToggleWide={onToggleWide} continuous={continuous} continuousControl={continuousControl} current={displayVideo} cachedSource={displayVideo && cachedSources[displayVideo.url]} retainSource={retainSource} autoPlay={autoPlay} onEnded={onVideoEnded} onError={onVideoError} onTimeChange={time => setPlayback({ key: current!.key, time })} onFileRevision={revision => setLoadedFile({ key: current!.key, revision })} />}>
      <SegmentReferences context={context} />
      <section className="segment-script" aria-label="分镜脚本、提示词与修改意见区域">
        <div className="segment-script-header">
          <UnderlineTabs label="分段文字内容" items={[{ value: 'script', label: '分镜脚本' }, { value: 'prompt', label: '提示词' }, { value: 'notes', label: '修改意见' }]} selected={tab} onChange={onTabChange} disabled={!current} />
          {editingNotes && <div className="segment-notes-export">{notesExportControl}</div>}
          {!editingNotes && <Original url={tab === 'script' ? (context?.scriptUrl || plannedScript?.url) : context?.prompts[language === 'zh' ? 'chineseUrl' : 'englishUrl']} label="查看原文件" />}
        </div>
        {showShotTimeline && <div className="shot-timeline-scroll" ref={shotTimeline}>
          <div className="shot-timeline" role="group" aria-label="分镜跳转"
            style={{ gridTemplateColumns: timedShots.map(item => `minmax(90px, ${item.shot.duration}fr)`).join(' '), minWidth: `${timedShots.length * 90}px` }}>
            {timedShots.map(({ shot, start }) => <button type="button" className="shot-timeline-item" key={shot.id} aria-current={shot.id === activeShot!.id ? 'step' : undefined}
              aria-label={`跳转到${shot.id}，${Number(start.toFixed(3))}秒`} title={`跳转到 ${Number(start.toFixed(3))}秒`} onClick={() => player.current?.seekTo(start)}>
              <span className="shot-timeline-title">{shot.id.match(/SH\d+$/)?.[0] || shot.id}</span>
              <span className="shot-timeline-track"><span style={{ transform: `scaleX(${Math.max(0, Math.min(1, (time - start) / shot.duration!))})` }} /></span>
            </button>)}
          </div>
        </div>}
        {tab === 'script' && <div className="segment-script-modes">
          <TabNav compact label="分镜显示方式" items={[{ value: 'aligned', label: '跟视频对齐', disabled: !canAlign }, { value: 'all', label: '显示全部' }]} selected={aligned ? 'aligned' : 'all'} onChange={setScriptMode} disabled={!current} />
        </div>}
        <div className={'segment-script-content' + (aligned && tab === 'script' ? ' is-aligned' : '')} ref={scriptContent}>
        {current && !current.context && <Result loading={detail.isPending} error={detail.error} retry={detail.refetch} retrying={detail.isFetching} />}
        {editingNotes && current ? <RevisionNoteEditor key={`${roundNumber}/${current.stage}/${current.run}`} roundNumber={roundNumber} scope={scope} segment={segment} current={current} time={time} shot={activeShot?.id.match(/SH\d+$/)?.[0] || activeShot?.id} shotStart={activeTimedShot?.start} fileRevision={loadedFile.key === current.key ? loadedFile.revision : current.fileRevision} /> : !context ? tab === 'script' && scriptHtml ? <Rich html={scriptHtml} /> : <div className="script-placeholder">{editingNotes ? '修改意见区域' : tab === 'script' ? '分镜脚本区域' : '提示词区域'}</div> : <>
          {awaitingGeneration ? <p className="notice" role="status">这版视频还没生成。{tab === 'script' && plannedScript?.html
            ? `现在看到的是${plannedScript.label}，不是生成视频时留下的记录。`
            : '还没有实际生成时使用的提示词和素材记录。'}</p>
            : context.issues.length > 0 && <details className="notice generation-context-issues"><summary>{segment} / {current!.stage} / {current!.run} 资料关联提示</summary>{context.issues.map(issue => <p key={issue}>{issue}</p>)}</details>}
          {context.source && <p className="muted">生成资料来源：{context.source}</p>}
          {tab === 'script' ? scriptHtml ? <Rich html={aligned ? activeShot!.html : scriptHtml} /> : <div className="script-placeholder">该次分镜原文尚未关联或已缺失。</div> : <>
            <div className="segment-prompt-actions">
              <TabNav compact label="提示词语言" items={[{ value: 'zh', label: '中文' }, { value: 'en', label: '英文' }]} selected={language} onChange={setLanguage} />
              {prompt && <CopyButton label="复制" text={prompt} />}
            </div>
            {prompt ? <PromptSections key={`${current!.key}/${language}`} text={prompt} language={language} /> : <div className="script-placeholder">{awaitingGeneration
              ? `生成时，这里会记录实际使用的${language === 'zh' ? '提示词中文参考版' : '英文提示词'}。`
              : `该次${language === 'zh' ? '中文参考版' : '实际提交的英文提示词'}尚未关联或已缺失。`}</div>}
          </>}
          {!awaitingGeneration && context.issues.length > 0 && <div className="notice">{context.issues.map(issue => <p key={issue}>{issue}</p>)}</div>}
        </>}
        </div>
      </section>
    </SegmentLayout>
  </>;
}
