import { useEffect, useRef, useState } from 'react';
import type { PointerEvent, ReactNode } from 'react';
import { get, projectUrl, type SegmentVideo } from '../api';
import { combinationKey, combinationLabel, episodeExportNotes, shotOrderedText, type CombinationSummary, type EpisodeReview, type SavedEpisodeNotes } from '../episodeRevisionNotes';
import { Dialog } from '../components';
import { editNote, loadNotes, noteKey, prepareNotesExport, saveNote, saveReviewedNote, saveNotesExport, sceneNotesUrl, useSceneNotes } from '../revisionNotes';
import type { NoteInput } from '../revisionNotes';
import { FloatingMessage, useNotify } from './Notifications';
import { CopyButton } from './CopyButton';
import { candidateLabel } from './SegmentVideo';
import { TabNav } from './TabNav';

export interface NoteScope { project: string; episode: string; scene: string }
export type NoteShotTimeline = (passShot: (shot: string, start: number) => void, preserveFocus: (event: PointerEvent<HTMLButtonElement>) => void, disabled: boolean) => ReactNode;
export function RevisionNoteEditor({ scope, segment, current, fileRevision, time, shot, renderShotTimeline, roundNumber }: { scope: NoteScope; segment: string; current: SegmentVideo; fileRevision: string; time: number; shot?: string; renderShotTimeline: NoteShotTimeline; roundNumber?: number }) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const [review, setReview] = useState<{ key: string; text: string } | null>(null);
  const notify = useNotify();
  const data = useSceneNotes(scope.project, scope.episode, scope.scene);
  const identity = { roundNumber, segment, stage: current.stage, run: current.run };
  const key = noteKey(identity);
  const draft = data.drafts[key];
  const note = data.notes[key];
  const text = draft?.value.text ?? note?.text ?? '';
  useEffect(() => () => { void saveNote(data.url, key); }, [data.url, key]);
  const status = draft ? { waiting: '等待保存', saving: '保存中…', saved: '已保存', error: '未保存' }[draft.status] : note ? '已保存' : '尚未填写';
  const statusKind = data.error ? 'error' : data.loading ? 'loading' : draft?.status ?? (note ? 'saved' : 'empty');
  const reviewConflict = async () => {
    const saved = await loadNotes(data.url, true);
    if (saved) setReview({ key, text: saved.notes[key]?.text ?? '' });
    else notify('最新意见读取失败或仍在读取，请稍后重新核对。', 'error');
  };
  const insertTime = (passedShot?: { id: string; start: number }) => {
    const tenths = passedShot ? Math.round(passedShot.start * 10) : Math.floor(time * 10);
    const targetShot = passedShot?.id ?? shot;
    const timestamp = `${String(Math.floor(tenths / 600)).padStart(2, '0')}.${String(Math.floor(tenths / 10) % 60).padStart(2, '0')}.${tenths % 10}秒${targetShot ? `，${targetShot}` : ''}：${passedShot ? '这个分镜没问题' : ''}`;
    const editor = textarea.current!;
    const editing = document.activeElement === editor;
    const start = editing ? editor.selectionStart : text.length;
    const end = editing ? editor.selectionEnd : text.length;
    const before = text.slice(0, start);
    const inserted = (before && !before.endsWith('\n') ? '\n' : '') + timestamp;
    const value = before + inserted + text.slice(end);
    if (value.length > editor.maxLength) { notify('文字已达上限，无法插入时间。'); return; }
    editNote(data.url, { ...identity, text: value, fileRevision });
    requestAnimationFrame(() => {
      editor.focus();
      editor.setSelectionRange(start + inserted.length, start + inserted.length);
    });
  };
  const preserveFocus = (event: PointerEvent<HTMLButtonElement>) => { if (document.activeElement === textarea.current) event.preventDefault(); };
  return <div className="revision-note-editor">
    {renderShotTimeline((id, start) => insertTime({ id, start }), preserveFocus, !data.loaded || !current.url)}
    <div className="revision-note-heading">
      <div className="revision-note-label"><button className="link" disabled={!data.loaded || !current.url} onPointerDown={event => { if (document.activeElement === textarea.current) event.preventDefault(); }} onClick={() => insertTime()}>插入时间</button><button className="link" disabled={!data.loaded || !text} onClick={() => editNote(data.url, { ...identity, text: '', fileRevision })}>清空</button></div>
      <div className="revision-note-status" role="status"><span className="revision-note-state" data-state={statusKind}>{data.error ? '读取失败' : data.loading ? '正在读取…' : status}</span>{note && <span className="muted">更新于 {new Date(note.updatedAt).toLocaleString('zh-CN')}</span>}</div>
    </div>
    <textarea ref={textarea} id="revision-note-text" aria-label="修改意见" placeholder="填写修改意见..." maxLength={20000} disabled={!data.loaded} value={text}
      onChange={event => editNote(data.url, { ...identity, text: event.target.value, fileRevision })} onBlur={() => { void saveNote(data.url, key); }} />

    {draft?.error && <FloatingMessage tone="error">{draft.error}{draft.conflict ? <button disabled={data.loading} onClick={() => { void reviewConflict(); }}>核对最新意见</button> : <button onClick={() => { void saveNote(data.url, key); }}>重试保存</button>}</FloatingMessage>}
    {note && note.fileRevision !== fileRevision && <p className="muted">该意见记录于此版本更新前。</p>}
    {review?.key === key && draft?.conflict && <Dialog title="核对修改意见" close={() => setReview(null)}>
      <p>其他页面已更新这条意见。本页文字仍保留；请对照后整理，再保存。</p>
      <label>项目中最新意见<textarea aria-label="项目中最新意见" readOnly value={review.text} /></label>
      <label>本页待保存意见<textarea aria-label="本页待保存意见" maxLength={20000} value={text} onChange={event => editNote(data.url, { ...identity, text: event.target.value, fileRevision })} /></label>
      <button onClick={() => { void saveReviewedNote(data.url, key, review.text); setReview(null); }}>保存核对后的本页意见</button>
    </Dialog>}
  </div>;
}

export type ReviewVersions = Record<string, Pick<SegmentVideo, 'stage' | 'run' | 'key'> | null>;
type ExportMode = 'round' | 'history';
type ExportNote = NoteInput & { key: string; title: string; original: string; scene?: string; current?: boolean; editable?: boolean };
type ExportOverall = { number: number; text: string; original: string };
type LegacyOverall = { scene: string; number: number; text: string };
type ExportCombination = { key: string; scenes: Record<string, number>; text: string; original: string };
type ExportDraft = { notes: ExportNote[]; rounds: ExportOverall[]; legacyRounds: LegacyOverall[]; combination: ExportCombination | null; combinationHistory: CombinationSummary[]; number?: number; label: string; scope: NoteScope; url: string; episode: boolean };

export function useRevisionNotesExport(scope: NoteScope | null, segments: { id: string; videos: SegmentVideo[] }[], review: { stage: string; label?: string; number?: number; versions: ReviewVersions } | null, loadHistorySegments?: () => Promise<{ id: string; videos: SegmentVideo[] }[]>, episodeReview?: EpisodeReview) {
  const data = useSceneNotes(scope?.project || '', scope?.episode || '', scope?.scene || '', !!scope);
  const [draft, setDraft] = useState<ExportDraft | null>(null);
  const [mode, setMode] = useState<ExportMode>('round');
  const [confirmClose, setConfirmClose] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const notify = useNotify();
  const [exportError, setExportError] = useState('');
  const changed = draft !== null && ([...draft.notes, ...draft.rounds].some(item => item.text !== item.original) || !!draft.combination && draft.combination.text !== draft.combination.original);
  useEffect(() => {
    if (!changed) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [changed]);
  const close = () => { if (saving) return; if (changed) setConfirmClose(true); else setDraft(null); };
  const exportNotes = async () => {
    if (!scope) return;
    setExporting(true);
    setExportError('');
    try {
      if (episodeReview) {
        const url = `${projectUrl(scope.project)}/revision-notes/${scope.episode}`;
        const [saved, fresh] = await Promise.all([
          get<SavedEpisodeNotes>(url),
          Promise.all(episodeReview.scenes.map(async scene => [scene.id, await prepareNotesExport(sceneNotesUrl(scope.project, scope.episode, scene.id))] as const)),
        ]);
        const values = { ...saved, scenes: { ...saved.scenes, ...Object.fromEntries(fresh) } };
        const rounds = Object.values(values.rounds).map(item => ({ number: item.number, text: item.text, original: item.text }));
        if (episodeReview.number && !rounds.some(item => item.number === episodeReview.number)) rounds.push({ number: episodeReview.number, text: '', original: '' });
        rounds.sort((a, b) => a.number - b.number);
        const legacyRounds = Object.entries(values.scenes).flatMap(([scene, saved]) => Object.values(saved.rounds).map(item => ({ scene, number: item.number, text: item.text })))
          .filter(item => item.text.trim()).sort((a, b) => Number(a.scene.slice(1)) - Number(b.scene.slice(1)) || a.number - b.number);
        let combination: ExportCombination | null = null;
        if (!episodeReview.number && episodeReview.scenes.length && episodeReview.scenes.every(scene => scene.number != null)) {
          const scenes = Object.fromEntries(episodeReview.scenes.map(scene => [scene.id, scene.number!]));
          const key = combinationKey(scenes);
          const text = values.combinations?.[key]?.text || '';
          combination = { key, scenes, text, original: text };
        }
        const combinationHistory = Object.entries(values.combinations || {}).filter(([key, item]) => key !== combination?.key && item.text.trim()).map(([, item]) => item);
        setDraft({ notes: episodeExportNotes(values, episodeReview), rounds, legacyRounds, combination, combinationHistory, number: episodeReview.number,
          label: episodeReview.number ? `第${episodeReview.number}轮` : '当前各场组合', scope: { ...scope }, url, episode: true });
      } else {
        const [saved, exportSegments] = await Promise.all([prepareNotesExport(data.url), loadHistorySegments ? loadHistorySegments() : Promise.resolve(segments)]);
        const ids = exportSegments.map(segment => segment.id);
        const order = (id: string) => { const index = ids.indexOf(id); return index < 0 ? ids.length + Number(id.slice(1)) : index; };
        const notes = Object.values(saved.notes).filter(note => note.text.trim()).sort((a, b) => (a.roundNumber ?? 0) - (b.roundNumber ?? 0) || order(a.segment) - order(b.segment) || ['一采', '二采', '后处理'].indexOf(a.stage) - ['一采', '二采', '后处理'].indexOf(b.stage) || Number(b.run.slice(1)) - Number(a.run.slice(1))).map(note => {
          const video = exportSegments.find(item => item.id === note.segment)?.videos.find(item => item.stage === note.stage && item.run === note.run);
          const label = video ? candidateLabel(video.candidateNumber, video.approved) : '';
          return { ...note, key: noteKey(note), title: `${note.roundNumber ? `第${note.roundNumber}轮` : '未标注轮次'} / ${note.segment} / ${note.stage} / ${note.run}${label ? ' / ' + label : ''}`, original: note.text };
        });
        const rounds = Object.values(saved.rounds).map(item => ({ number: item.number, text: item.text, original: item.text }));
        if (review?.number && !rounds.some(item => item.number === review.number)) rounds.push({ number: review.number, text: '', original: '' });
        rounds.sort((a, b) => a.number - b.number);
        setDraft({ notes, rounds, legacyRounds: [], combination: null, combinationHistory: [], number: review?.number, label: review?.label || '浏览片单', scope: { ...scope }, url: data.url, episode: false });
      }
      setMode('round'); setConfirmClose(false); setMessage('');
    } catch (error) { setExportError(String(error)); }
    finally { setExporting(false); }
  };
  const visibleNotes = draft?.notes.filter(item => mode === 'history' || (draft.episode ? item.current : draft.number != null && item.roundNumber === draft.number)) || [];
  const visibleRounds = draft?.rounds.filter(item => mode === 'history' || item.number === draft.number) || [];
  const overallLabel = draft?.episode ? '本轮汇总意见' : '整场总体意见';
  const text = draft ? `${draft.scope.project} / ${draft.scope.episode}${draft.episode ? '' : ' / ' + draft.scope.scene} ${mode === 'round' ? draft.label + '审看意见' : '全部历史意见'}\n\n` + [
    ...visibleNotes.filter(item => item.text.trim()).map(item => `【${item.title}】\n${shotOrderedText(item.text)}`),
    ...visibleRounds.filter(item => item.text.trim()).map(item => `【第${item.number}轮 · ${overallLabel}】\n${item.text}`),
    ...(draft.combination?.text.trim() ? [`【本轮汇总意见（${combinationLabel(draft.combination.scenes)}）】\n${draft.combination.text}`] : []),
    ...(mode === 'history' ? draft.combinationHistory.map(item => `【整集汇总意见（${combinationLabel(item.scenes)}）】\n${item.text}`) : []),
    ...(mode === 'history' ? draft.legacyRounds.map(item => `【${item.scene} / 第${item.number}轮 · 整场总体意见（历史）】\n${item.text}`) : []),
  ].join('\n\n') : '';
  const save = async () => {
    const opened = draft!;
    setSaving(true); setConfirmClose(false); setMessage('');
    try {
      const notes = opened.notes.filter(item => item.text !== item.original).map(({ roundNumber, segment, stage, run, text, fileRevision, original, scene }) => ({ roundNumber, segment, stage, run, text, fileRevision, expectedText: original, ...(opened.episode ? { scene } : {}) }));
      const rounds = opened.rounds.filter(item => item.text !== item.original).map(({ number, text, original }) => ({ number, text, expectedText: original }));
      if (opened.episode) {
        const combination = opened.combination && opened.combination.text !== opened.combination.original ? { scenes: opened.combination.scenes, text: opened.combination.text, expectedText: opened.combination.original } : undefined;
        const response = await fetch(opened.url + '/export', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ notes, rounds, combination }) });
        if (!response.ok) {
          const error = await response.json();
          throw new Error(typeof error.detail === 'string' ? error.detail : `保存失败（${response.status}）`);
        }
        await Promise.all([...new Set(notes.map(item => item.scene!))].map(scene => loadNotes(sceneNotesUrl(opened.scope.project, opened.scope.episode, scene), true)));
      } else await saveNotesExport(opened.url, { notes, rounds });
      setDraft({ ...opened, notes: opened.notes.map(item => ({ ...item, original: item.text })), rounds: opened.rounds.map(item => ({ ...item, original: item.text })), combination: opened.combination ? { ...opened.combination, original: opened.combination.text } : null });
      notify('已保存。'); setConfirmClose(false);
    } catch (error) { setMessage(`未保存：${error instanceof Error ? error.message : String(error)}`); }
    finally { setSaving(false); }
  };
  return { control: <><button disabled={!data.loaded || exporting} onClick={() => { void exportNotes(); }}>{exporting ? '正在读取意见…' : '导出修改意见'}</button>
    {exportError && <FloatingMessage tone="error">导出资料读取失败：{exportError}<button onClick={() => { void exportNotes(); }}>重试</button></FloatingMessage>}
    {data.error && <FloatingMessage tone="error">修改意见读取失败：{data.error}<button onClick={() => { void loadNotes(data.url); }}>重试</button></FloatingMessage>}</>,
    dialog: draft !== null && <Dialog title={`${draft.scope.episode}${draft.episode ? ' · ' + draft.label : ' · ' + draft.scope.scene} 导出修改意见`} close={close} headerActions={confirmClose ? <div className="revision-export-close-actions"><button autoFocus onClick={() => setConfirmClose(false)}>继续编辑</button><button className="revision-export-discard" onClick={() => { setDraft(null); setConfirmClose(false); }}>放弃修改并关闭</button></div> : undefined}>
      <p className="muted">这是打开时读取的意见快照。修改后需保存才能写回项目；复制只放入剪贴板，请粘贴到制作会话交给 Agent。</p>
      <TabNav compact label="意见导出范围" items={[{ value: 'round', label: draft.episode && !draft.number ? '当前组合意见' : '本轮意见' }, { value: 'history', label: '全部历史意见' }]} selected={mode} onChange={value => { setMode(value as ExportMode); setConfirmClose(false); }} />
      {confirmClose && <p className="notice" role="alert">尚有未保存的修改。放弃修改并关闭后，这些修改不会保留。</p>}
      <div className="revision-export-structured">
        <fieldset disabled={saving} className="revision-export-fields">
          {visibleNotes.map(item => <section className="revision-export-note" key={item.key}>
            <label><strong>{item.title}</strong><textarea aria-label={`${item.title} 修改意见`} maxLength={20000} readOnly={draft.episode && !item.editable} value={item.text} onChange={event => { setDraft({ ...draft, notes: draft.notes.map(note => note.key === item.key ? { ...note, text: event.target.value } : note) }); setConfirmClose(false); setMessage(''); }} /></label>
          </section>)}
          {!visibleNotes.length && <p className="muted">{mode === 'round' ? '当前范围暂无分段意见。' : '暂无分段意见。'}</p>}
          <section className="revision-export-overall" aria-label={overallLabel}>
            {visibleRounds.map(item => <label key={item.number}><strong>第{item.number}轮 · {overallLabel}</strong><textarea aria-label={`第${item.number}轮 ${overallLabel}`} placeholder={draft.episode ? '填写整集本轮共用的意见…' : '填写整场共用的意见…'} maxLength={20000} value={item.text} onChange={event => { setDraft({ ...draft, rounds: draft.rounds.map(note => note.number === item.number ? { ...note, text: event.target.value } : note) }); setConfirmClose(false); setMessage(''); }} /></label>)}
            {draft.combination && <label><strong>本轮汇总意见</strong><textarea aria-label="本轮汇总意见" placeholder="填写整集本轮共用的意见…" maxLength={20000} value={draft.combination.text} onChange={event => { setDraft({ ...draft, combination: { ...draft.combination!, text: event.target.value } }); setConfirmClose(false); setMessage(''); }} /></label>}
            {!visibleRounds.length && !draft.combination && <p className="muted">{draft.episode ? '请先选择各场已登记的修改轮次，再填写整集汇总意见。' : mode === 'round' ? '整场总体意见按已登记的场次轮次保存；请先选择本场次的修改轮次。' : '暂无按轮次保存的整场总体意见。'}</p>}
          </section>
          {mode === 'history' && draft.combinationHistory.map(item => <section className="revision-export-legacy" key={combinationKey(item.scenes)}><strong>整集汇总意见（{combinationLabel(item.scenes)}）</strong><textarea aria-label={`整集汇总意见（${combinationLabel(item.scenes)}）`} readOnly value={item.text} /></section>)}
          {mode === 'history' && draft.legacyRounds.map(item => <section className="revision-export-legacy" key={`${item.scene}/${item.number}`}><strong>{item.scene} / 第{item.number}轮 · 整场总体意见（历史）</strong><textarea aria-label={`${item.scene} 第${item.number}轮 整场总体意见（历史只读）`} readOnly value={item.text} /></section>)}
        </fieldset>
        <footer className="revision-export-save"><button disabled={!changed || saving} onClick={() => { void save(); }}>{saving ? '保存中…' : '保存'}</button><button disabled={!changed || saving} onClick={() => { setDraft({ ...draft, notes: draft.notes.map(item => ({ ...item, text: item.original })), rounds: draft.rounds.map(item => ({ ...item, text: item.original })), combination: draft.combination ? { ...draft.combination, text: draft.combination.original } : null }); setConfirmClose(false); setMessage(''); }}>还原</button><div className="revision-export-toolbar"><CopyButton label="复制" text={(changed ? '【未保存草稿：以下内容尚未全部写回项目意见文件】\n\n' : '') + text} successMessage={changed ? '已复制；有未保存的修改' : '已复制'} /></div><span role="status" className="muted">{changed ? '有未保存的修改' : ''}</span>{message && <FloatingMessage tone="error">{message}</FloatingMessage>}</footer>
      </div>
    </Dialog> };
}
