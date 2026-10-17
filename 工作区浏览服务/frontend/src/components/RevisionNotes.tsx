import { useEffect, useRef, useState } from 'react';
import type { SegmentVideo } from '../api';
import { Dialog } from '../components';
import { editNote, loadNotes, noteKey, saveNote, useSceneNotes } from '../revisionNotes';
import { CopyButton } from './CopyButton';
import { candidateLabel } from './SegmentVideo';
import { TabNav } from './TabNav';

export interface NoteScope { project: string; episode: string; scene: string }
export function RevisionNoteEditor({ scope, segment, current, fileRevision, time, shot }: { scope: NoteScope; segment: string; current: SegmentVideo; fileRevision: string; time: number; shot?: string }) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const [insertMessage, setInsertMessage] = useState('');
  const tenths = Math.floor(time * 10);
  const timestamp = `${String(Math.floor(tenths / 600)).padStart(2, '0')}.${String(Math.floor(tenths / 10) % 60).padStart(2, '0')}.${tenths % 10}秒${shot ? `，${shot}` : ''}：`;
  const data = useSceneNotes(scope.project, scope.episode, scope.scene);
  const identity = { segment, stage: current.stage, run: current.run };
  const key = noteKey(identity);
  const draft = data.drafts[key];
  const note = data.notes[key];
  const text = draft?.value.text ?? note?.text ?? '';
  useEffect(() => () => { void saveNote(data.url, key); }, [data.url, key]);
  const status = draft ? { waiting: '等待保存', saving: '保存中…', saved: '已保存', error: '未保存' }[draft.status] : note ? '已保存' : '尚未填写';
  const statusKind = data.error ? 'error' : data.loading ? 'loading' : draft?.status ?? (note ? 'saved' : 'empty');
  const insertTime = () => {
    const editor = textarea.current!;
    const editing = document.activeElement === editor;
    const start = editing ? editor.selectionStart : text.length;
    const end = editing ? editor.selectionEnd : text.length;
    const before = text.slice(0, start);
    const inserted = (before && !before.endsWith('\n') ? '\n' : '') + timestamp;
    const value = before + inserted + text.slice(end);
    if (value.length > editor.maxLength) { setInsertMessage('文字已达上限，无法插入时间。'); return; }
    editNote(data.url, { ...identity, text: value, fileRevision });
    requestAnimationFrame(() => {
      editor.focus();
      editor.setSelectionRange(start + inserted.length, start + inserted.length);
    });
    setInsertMessage('');
  };
  return <div className="revision-note-editor">
    <p className="revision-note-identity">{scope.project} / {scope.episode} / {scope.scene} / {segment} / {current.stage} / {current.approved ? '正式版' : candidateLabel(current.candidateNumber)} · {current.run}</p>
    {data.error && <p className="error" role="alert">修改意见读取失败：{data.error}<button onClick={() => { void loadNotes(data.url); }}>重试读取</button></p>}
    <div className="revision-note-heading">
      <div className="revision-note-label"><label htmlFor="revision-note-text">修改意见</label><button className="link" disabled={!data.loaded || !current.url} onPointerDown={event => { if (document.activeElement === textarea.current) event.preventDefault(); }} onClick={insertTime}>插入时间</button><button className="link" disabled={!data.loaded || !text} onClick={() => editNote(data.url, { ...identity, text: '', fileRevision })}>清空</button></div>
      <div className="revision-note-status" role="status"><span className="revision-note-state" data-state={statusKind}>{data.error ? '读取失败' : data.loading ? '正在读取…' : status}</span>{note && <span className="muted">更新于 {new Date(note.updatedAt).toLocaleString('zh-CN')}</span>}{draft?.status === 'error' && <button onClick={() => { void saveNote(data.url, key); }}>重试保存</button>}</div>
    </div>
    <textarea ref={textarea} id="revision-note-text" placeholder="填写修改意见..." maxLength={20000} disabled={!data.loaded} value={text}
      onChange={event => editNote(data.url, { ...identity, text: event.target.value, fileRevision })} onBlur={() => { void saveNote(data.url, key); }} />
    {insertMessage && <p role="status" className="muted">{insertMessage}</p>}
    {draft?.error && <p className="error">{draft.error}</p>}
    {note && note.fileRevision !== fileRevision && <p className="muted">该意见记录于此版本更新前。</p>}
  </div>;
}

export type ReviewVersions = Record<string, Pick<SegmentVideo, 'stage' | 'run' | 'key'> | null>;
type ExportMode = 'round' | 'history';
type ExportDraft = { original: string; text: string };

export function useRevisionNotesExport(scope: NoteScope, segments: { id: string; videos: SegmentVideo[] }[], review: { stage: string; label?: string; versions: ReviewVersions } | null, loadHistorySegments?: () => Promise<{ id: string; videos: SegmentVideo[] }[]>) {
  const data = useSceneNotes(scope.project, scope.episode, scope.scene);
  const [draft, setDraft] = useState<Record<ExportMode, ExportDraft> | null>(null);
  const [mode, setMode] = useState<ExportMode>('round');
  const [confirmClose, setConfirmClose] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState(false);
  const changed = draft !== null && Object.values(draft).some(item => item.text !== item.original);
  const close = () => { if (changed) setConfirmClose(true); else setDraft(null); };
  const buildExport = (mode: ExportMode, exportSegments = segments): ExportDraft => {
    const values = { ...data.notes, ...Object.fromEntries(Object.entries(data.drafts).map(([key, draft]) => [key, draft.value])) };
    const ids = mode === 'round' && review ? Object.keys(review.versions) : exportSegments.map(segment => segment.id);
    const notes = Object.values(values).filter(note => {
      if (!note.text.trim()) return false;
      if (mode === 'history') return true;
      const version = review?.versions[note.segment];
      return version?.stage === note.stage && version.run === note.run;
    }).sort((a, b) => {
      const order = (id: string) => { const index = ids.indexOf(id); return index < 0 ? ids.length + Number(id.slice(1)) : index; };
      return order(a.segment) - order(b.segment) || ['一采', '二采', '后处理'].indexOf(a.stage) - ['一采', '二采', '后处理'].indexOf(b.stage) || Number(b.run.slice(1)) - Number(a.run.slice(1));
    });
    const text = `${scope.project} / ${scope.episode} / ${scope.scene} ${mode === 'round' ? `${review?.label || '本轮'}审看意见` : '全部历史意见'}\n\n` + (notes.length ? notes.map(note => {
      const video = exportSegments.find(segment => segment.id === note.segment)?.videos.find(video => video.stage === note.stage && video.run === note.run);
      const label = video ? (video.approved ? '正式版' : candidateLabel(video.candidateNumber)) : '';
      const status = data.drafts[noteKey(note)]?.status;
      return `【${note.segment} / ${note.stage} / ${note.run}${label ? ' / ' + label : ''}${status && status !== 'saved' ? ' / 未保存草稿' : ''}】\n${note.text}`;
    }).join('\n\n') : mode === 'history' ? '本场次暂无修改意见。' : review ? '本轮审看版本暂无修改意见。' : '尚未固定本轮版本，请先开启连续播放。');
    return { original: text, text };
  };
  const exportNotes = async () => {
    setExporting(true);
    setExportError(false);
    try {
      const exportSegments = loadHistorySegments ? await loadHistorySegments() : segments;
      setDraft({ round: buildExport('round', exportSegments), history: buildExport('history', exportSegments) });
      setMode('round');
      setConfirmClose(false);
    } catch {
      setExportError(true);
    } finally {
      setExporting(false);
    }
  };
  return { control: <><button disabled={!data.loaded || exporting} onClick={() => { void exportNotes(); }}>{exporting ? '正在读取意见…' : '导出修改意见'}</button>
    {exportError && <span className="error">导出资料读取失败，请重试。</span>}
    {data.error && <span className="error">意见读取失败<button onClick={() => { void loadNotes(data.url); }}>重试</button></span>}</>,
    dialog: draft !== null && <Dialog title={`${scope.episode} · ${scope.scene} 导出修改意见`} close={close} headerActions={confirmClose ? <div className="revision-export-close-actions"><button autoFocus onClick={() => setConfirmClose(false)}>继续编辑</button><button className="revision-export-discard" onClick={() => { setDraft(null); setConfirmClose(false); }}>放弃修改并关闭</button></div> : undefined}>
      <TabNav compact label="意见导出范围" items={[{ value: 'round', label: '本轮意见' }, { value: 'history', label: '全部历史意见' }]} selected={mode} onChange={value => { setMode(value as ExportMode); setConfirmClose(false); }} />
      <p className="muted">{mode === 'history' ? '本场次全部画质、全部版本中已填写的意见。' : review ? `仅包含${review.label || '浏览片单'}固定的审看版本；没有填写意见时不补入旧版本意见。` : '尚未固定本轮版本，请先开启连续播放，或选择全部历史意见。'}此处编辑只影响本次导出稿。</p>
      <div className="revision-export-editor">
        <div className="revision-export-actions"><CopyButton label="复制" text={draft[mode].text} />{draft[mode].text !== draft[mode].original && <button onClick={() => { setDraft({ ...draft, [mode]: { ...draft[mode], text: draft[mode].original } }); setConfirmClose(false); }}>还原</button>}</div>
        <textarea className="revision-notes-export" aria-label="导出修改意见文本" value={draft[mode].text} onChange={event => { setDraft({ ...draft, [mode]: { ...draft[mode], text: event.target.value } }); setConfirmClose(false); }} />
      </div>
    </Dialog> };
}
