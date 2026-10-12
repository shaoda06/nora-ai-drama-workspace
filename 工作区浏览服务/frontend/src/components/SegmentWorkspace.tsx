import { useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { GenerationContext, SegmentVideo as VideoItem } from '../api';
import { Original, PreviewContext, Rich } from '../components';
import { TabNav } from './TabNav';
import { UnderlineTabs } from './UnderlineTabs';
import { TabSelect } from './TabSelect';
import { candidateLabel, latestVideo, SegmentVideo } from './SegmentVideo';
import type { SegmentVideoHandle } from './SegmentVideo';
import { CopyButton } from './CopyButton';
import { PromptSections } from './PromptSections';
import { RevisionNoteEditor } from './RevisionNotes';
import type { NoteScope } from './RevisionNotes';
import { useRefreshState } from '../refreshPosition';
import './SegmentWideLayout.css';

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

export function SegmentWorkspace({ scope, segment, items, selection: { stage, key: selected }, onSelectionChange, notesExportControl, segmentNavigation, autoPlay, onVideoEnded, onVideoError, cachedSources, wideVideo, onToggleWide, continuousControl }: {
  scope: NoteScope; segment: string;
  items: VideoItem[]; selection: { stage: string; key: string }; onSelectionChange: (selection: { stage: string; key: string }) => void;
  wideVideo: boolean; onToggleWide: () => void; continuousControl: ReactNode;
  notesExportControl: ReactNode; segmentNavigation: ReactNode; autoPlay: boolean; onVideoEnded: () => void; onVideoError: () => void;
  cachedSources: Record<string, string>;
}) {
  const positionKey = `segment/${scope.project}/${scope.episode}/${scope.scene}/${segment}`;
  const [tab, setTab] = useRefreshState(positionKey + '/tab', 'script');
  const [language, setLanguage] = useRefreshState(positionKey + '/language', 'zh');
  const [scriptMode, setScriptMode] = useRefreshState(positionKey + '/scriptMode', 'aligned');
  const [playback, setPlayback] = useState({ key: '', time: 0 });
  const [loadedFile, setLoadedFile] = useState({ key: '', revision: '' });
  const scriptContent = useRef<HTMLDivElement>(null);
  const shotTimeline = useRef<HTMLDivElement>(null);
  const player = useRef<SegmentVideoHandle>(null);
  const latest = latestVideo(items);
  const versions = items.filter(item => item.stage === stage).sort((a, b) => Number(b.approved) - Number(a.approved) || b.candidateNumber - a.candidateNumber);
  const current = versions.find(item => item.key === selected);
  const context = current?.context;
  const prompt = context?.prompts[language === 'zh' ? 'chinese' : 'english'];
  const shots = context?.shots || [];
  const canAlign = !!current?.url && shots.length > 0 && shots.every(shot => shot.duration !== null);
  const time = playback.key === current?.key ? playback.time : 0;
  let plannedDuration = 0;
  const timedShots = canAlign ? shots.map(shot => {
    const start = plannedDuration;
    plannedDuration += shot.duration!;
    return { shot, start, end: plannedDuration };
  }) : [];
  const activeShot = (timedShots.find(item => time < item.end) || timedShots[timedShots.length - 1])?.shot;
  const aligned = scriptMode === 'aligned' && canAlign;
  const editingNotes = tab === 'notes';
  useEffect(() => {
    scriptContent.current!.scrollTop = 0;
  }, [current?.key, tab, scriptMode, tab === 'script' && aligned ? activeShot?.id : undefined]);
  useEffect(() => {
    if (tab !== 'script' || !canAlign || editingNotes) return;
    const container = shotTimeline.current!;
    const title = container.querySelector('[aria-current="step"]')!.getBoundingClientRect();
    const bounds = container.getBoundingClientRect();
    container.scrollBy({ left: title.left < bounds.left ? title.left - bounds.left : Math.max(0, title.right - bounds.right) });
  }, [tab, activeShot?.id, current?.key, editingNotes]);
  const selectors = <div className="segment-selectors tabs tabs-grouped">
      <TabSelect label="画质选择" selected={stage} onChange={value => onSelectionChange({ stage: value, key: '' })} items={['一采', '二采', '后处理'].map(value => ({ value, label: value }))} />
      <TabSelect label="版本切换" disabled={!stage} selected={current?.key || ''} onChange={key => onSelectionChange({ stage, key })} items={versions.map(item => ({ value: item.key, label: item.approved ? '正式版' : candidateLabel(item.candidateNumber) }))} />
      <button disabled={!latest} onClick={() => onSelectionChange({ stage: latest!.stage, key: latest!.key })}>最新</button>
    </div>;
  return <>
    {!wideVideo && selectors}
    <div className={'segment-workspace' + (wideVideo ? ' is-wide' : '')}>
      <div className="segment-playback-row">
      <SegmentVideo playerRef={player} selectorControl={wideVideo ? selectors : undefined} key={current?.key || 'empty'} wide={wideVideo} onToggleWide={onToggleWide} continuousControl={continuousControl} current={current} cachedSource={current && cachedSources[current.url]} autoPlay={autoPlay} onEnded={onVideoEnded} onError={onVideoError} onTimeChange={time => setPlayback({ key: current!.key, time })} onFileRevision={revision => setLoadedFile({ key: current!.key, revision })} />
      {wideVideo && <aside className="segment-side-navigation" aria-label="宽屏分段导航">{segmentNavigation}</aside>}
      </div>
      <SegmentReferences context={context} />
      <section className="segment-script" aria-label="分镜脚本、提示词与修改意见区域">
        <div className="segment-script-header">
          <UnderlineTabs label="分段文字内容" items={[{ value: 'script', label: '分镜脚本' }, { value: 'prompt', label: '提示词' }, { value: 'notes', label: '修改意见' }]} selected={tab} onChange={setTab} disabled={!current} />
          {editingNotes && <div className="segment-notes-export">{notesExportControl}</div>}
          {!editingNotes && <Original url={tab === 'script' ? context?.scriptUrl : context?.prompts[language === 'zh' ? 'chineseUrl' : 'englishUrl']} label="查看原文件" />}
        </div>
        {tab === 'script' && <div className="segment-script-modes">
          <TabNav compact label="分镜显示方式" items={[{ value: 'aligned', label: '跟视频对齐', disabled: !canAlign }, { value: 'all', label: '显示全部' }]} selected={aligned ? 'aligned' : 'all'} onChange={setScriptMode} disabled={!current} />
        </div>}
        {tab === 'script' && canAlign && !editingNotes && <div className="shot-timeline-scroll" ref={shotTimeline}>
          <div className="shot-timeline" role="group" aria-label="分镜跳转"
            style={{ gridTemplateColumns: timedShots.map(item => `minmax(90px, ${item.shot.duration}fr)`).join(' '), minWidth: `${timedShots.length * 90}px` }}>
            {timedShots.map(({ shot, start }) => <button type="button" className="shot-timeline-item" key={shot.id} aria-current={shot.id === activeShot!.id ? 'step' : undefined}
              aria-label={`跳转到${shot.id}，${Number(start.toFixed(3))}秒`} title={`跳转到 ${Number(start.toFixed(3))}秒`} onClick={() => player.current?.seekTo(start)}>
              <span className="shot-timeline-title">{shot.id.match(/SH\d+$/)?.[0] || shot.id}</span>
              <span className="shot-timeline-track"><span style={{ transform: `scaleX(${Math.max(0, Math.min(1, (time - start) / shot.duration!))})` }} /></span>
            </button>)}
          </div>
        </div>}
        <div className={'segment-script-content' + (aligned && tab === 'script' ? ' is-aligned' : '')} ref={scriptContent}>
        {editingNotes && current ? <RevisionNoteEditor key={`${current.stage}/${current.run}`} scope={scope} segment={segment} current={current} time={time} fileRevision={loadedFile.key === current.key ? loadedFile.revision : current.fileRevision} /> : !context ? <div className="script-placeholder">{editingNotes ? '修改意见区域' : tab === 'script' ? '分镜脚本区域' : '提示词区域'}</div> : <>
          {context.issues.length > 0 && <details className="notice generation-context-issues"><summary>{segment} / {current!.stage} / {current!.run} 资料关联提示</summary>{context.issues.map(issue => <p key={issue}>{issue}</p>)}</details>}
          {context.source && <p className="muted">生成资料来源：{context.source}</p>}
          {tab === 'script' ? context.scriptHtml ? <Rich html={aligned ? activeShot!.html : context.scriptHtml} /> : <div className="script-placeholder">该次分镜原文尚未关联或已缺失。</div> : <>
            <div className="segment-prompt-actions">
              <TabNav compact label="提示词语言" items={[{ value: 'zh', label: '中文' }, { value: 'en', label: '英文' }]} selected={language} onChange={setLanguage} />
              {prompt && <CopyButton label="复制" text={prompt} />}
            </div>
            {prompt ? <PromptSections key={`${current!.key}/${language}`} text={prompt} language={language} /> : <div className="script-placeholder">该次{language === 'zh' ? '中文参考版' : '实际提交的英文提示词'}尚未关联或已缺失。</div>}
          </>}
          {context.issues.length > 0 && <div className="notice">{context.issues.map(issue => <p key={issue}>{issue}</p>)}</div>}
        </>}
        </div>
      </section>
    </div>
  </>;
}
