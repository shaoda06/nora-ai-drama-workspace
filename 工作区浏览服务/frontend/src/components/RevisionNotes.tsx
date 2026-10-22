import { useEffect, useRef, useState } from 'react';
import type { SegmentVideo } from '../api';
import { Dialog } from '../components';
import { editNote, loadNotes, noteKey, prepareNotesExport, saveNote, saveNotesExport, useSceneNotes } from '../revisionNotes';
import type { NoteInput } from '../revisionNotes';
import { FloatingMessage, useNotify } from './Notifications';
import { CopyButton } from './CopyButton';
import { candidateLabel } from './SegmentVideo';
import { TabNav } from './TabNav';

export interface NoteScope { project: string; episode: string; scene: string }
export function RevisionNoteEditor({ scope, segment, current, fileRevision, time, shot }: { scope: NoteScope; segment: string; current: SegmentVideo; fileRevision: string; time: number; shot?: string }) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const notify = useNotify();
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
    if (value.length > editor.maxLength) { notify('文字已达上限，无法插入时间。'); return; }
    editNote(data.url, { ...identity, text: value, fileRevision });
    requestAnimationFrame(() => {
      editor.focus();
      editor.setSelectionRange(start + inserted.length, start + inserted.length);
    });
  };
  return <div className="revision-note-editor">
    <p className="revision-note-identity">{scope.project} / {scope.episode} / {scope.scene} / {segment} / {current.stage} / {current.approved ? '正式版' : candidateLabel(current.candidateNumber)} · {current.run}</p>
    <div className="revision-note-heading">
      <div className="revision-note-label"><label htmlFor="revision-note-text">修改意见</label><button className="link" disabled={!data.loaded || !current.url} onPointerDown={event => { if (document.activeElement === textarea.current) event.preventDefault(); }} onClick={insertTime}>插入时间</button><button className="link" disabled={!data.loaded || !text} onClick={() => editNote(data.url, { ...identity, text: '', fileRevision })}>清空</button></div>
      <div className="revision-note-status" role="status"><span className="revision-note-state" data-state={statusKind}>{data.error ? '读取失败' : data.loading ? '正在读取…' : status}</span>{note && <span className="muted">更新于 {new Date(note.updatedAt).toLocaleString('zh-CN')}</span>}{draft?.status === 'error' && <button onClick={() => { void saveNote(data.url, key); }}>重试保存</button>}</div>
    </div>
    <textarea ref={textarea} id="revision-note-text" placeholder="填写修改意见..." maxLength={20000} disabled={!data.loaded} value={text}
      onChange={event => editNote(data.url, { ...identity, text: event.target.value, fileRevision })} onBlur={() => { void saveNote(data.url, key); }} />

    {draft?.error && <FloatingMessage tone="error">{draft.error}</FloatingMessage>}
    {note && note.fileRevision !== fileRevision && <p className="muted">该意见记录于此版本更新前。</p>}
  </div>;
}

export type ReviewVersions = Record<string, Pick<SegmentVideo, 'stage' | 'run' | 'key'> | null>;
type ExportMode = 'round' | 'history';
type ExportNote = NoteInput & { key: string; title: string; original: string };
type ExportOverall = { number: number; text: string; original: string };
type ExportDraft = { notes: ExportNote[]; rounds: ExportOverall[]; roundKeys: string[]; number?: number; label: string; scope: NoteScope; url: string };

export function useRevisionNotesExport(scope: NoteScope, segments: { id: string; videos: SegmentVideo[] }[], review: { stage: string; label?: string; number?: number; versions: ReviewVersions } | null, loadHistorySegments?: () => Promise<{ id: string; videos: SegmentVideo[] }[]>) {
  const data = useSceneNotes(scope.project, scope.episode, scope.scene);
  const [draft, setDraft] = useState<ExportDraft | null>(null);
  const [mode, setMode] = useState<ExportMode>('round');
  const [confirmClose, setConfirmClose] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const notify = useNotify();
  const [exportError, setExportError] = useState('');
  const changed = draft !== null && [...draft.notes, ...draft.rounds].some(item => item.text !== item.original);
  useEffect(() => {
    if (!changed) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [changed]);
  const close = () => { if (saving) return; if (changed) setConfirmClose(true); else setDraft(null); };
  const exportNotes = async () => {
    setExporting(true);
    setExportError('');
    try {
      const [saved, exportSegments] = await Promise.all([prepareNotesExport(data.url), loadHistorySegments ? loadHistorySegments() : Promise.resolve(segments)]);
      const values: Record<string, NoteInput> = { ...saved.notes };
      const roundKeys: string[] = [];
      for (const [segment, version] of Object.entries(review?.versions || {})) {
        if (!version) continue;
        const key = noteKey({ segment, ...version });
        roundKeys.push(key);
      }
      const ids = exportSegments.map(segment => segment.id);
      const order = (id: string) => { const index = ids.indexOf(id); return index < 0 ? ids.length + Number(id.slice(1)) : index; };
      const notes = Object.values(values).filter(note => note.text.trim()).sort((a, b) => order(a.segment) - order(b.segment) || ['一采', '二采', '后处理'].indexOf(a.stage) - ['一采', '二采', '后处理'].indexOf(b.stage) || Number(b.run.slice(1)) - Number(a.run.slice(1))).map(note => {
        const video = exportSegments.find(item => item.id === note.segment)?.videos.find(item => item.stage === note.stage && item.run === note.run);
        const label = video ? (video.approved ? '正式版' : candidateLabel(video.candidateNumber)) : '';
        return { ...note, key: noteKey(note), title: `${note.segment} / ${note.stage} / ${note.run}${label ? ' / ' + label : ''}`, original: note.text };
      });
      const rounds: ExportOverall[] = Object.values(saved.rounds).map(item => ({ number: item.number, text: item.text, original: item.text }));
      if (review?.number && !rounds.some(item => item.number === review.number)) rounds.push({ number: review.number, text: '', original: '' });
      rounds.sort((a, b) => a.number - b.number);
      setDraft({ notes, rounds, roundKeys, number: review?.number, label: review?.label || '浏览片单', scope: { ...scope }, url: data.url });
      setMode('round');
      setConfirmClose(false);
      setMessage('');
    } catch (error) {
      setExportError(String(error));
    } finally {
      setExporting(false);
    }
  };
  const visibleNotes = draft?.notes.filter(item => mode === 'history' || draft.roundKeys.includes(item.key)) || [];
  const visibleRounds = draft?.rounds.filter(item => mode === 'history' || item.number === draft.number) || [];
  const text = draft ? `${draft.scope.project} / ${draft.scope.episode} / ${draft.scope.scene} ${mode === 'round' ? draft.label + '审看意见' : '全部历史意见'}\n\n` + [
    ...visibleNotes.filter(item => item.text.trim()).map(item => `【${item.title}】\n${item.text}`),
    ...visibleRounds.filter(item => item.text.trim()).map(item => `【第${item.number}轮 · 整场总体意见】\n${item.text}`),
  ].join('\n\n') : '';
  const save = async () => {
    const opened = draft!;
    setSaving(true);
    setConfirmClose(false);
    setMessage('');
    try {
      await saveNotesExport(opened.url, {
        notes: opened.notes.filter(item => item.text !== item.original).map(({ segment, stage, run, text, fileRevision, original }) => ({ segment, stage, run, text, fileRevision, expectedText: original })),
        rounds: opened.rounds.filter(item => item.text !== item.original).map(({ number, text, original }) => ({ number, text, expectedText: original })),
      });
      setDraft({ ...opened, notes: opened.notes.map(item => ({ ...item, original: item.text })), rounds: opened.rounds.map(item => ({ ...item, original: item.text })) });
      notify('已保存。');
      setConfirmClose(false);
    } catch (error) {
      setMessage(`未保存：${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setSaving(false);
    }
  };
  return { control: <><button disabled={!data.loaded || exporting} onClick={() => { void exportNotes(); }}>{exporting ? '正在读取意见…' : '导出修改意见'}</button>
    {exportError && <FloatingMessage tone="error">导出资料读取失败：{exportError}</FloatingMessage>}
    {data.error && <FloatingMessage tone="error">修改意见读取失败：{data.error}<button onClick={() => { void loadNotes(data.url); }}>重试</button></FloatingMessage>}</>,
    dialog: draft !== null && <Dialog title={`${draft.scope.episode} · ${draft.scope.scene} 导出修改意见`} close={close} headerActions={confirmClose ? <div className="revision-export-close-actions"><button autoFocus onClick={() => setConfirmClose(false)}>继续编辑</button><button className="revision-export-discard" onClick={() => { setDraft(null); setConfirmClose(false); }}>放弃修改并关闭</button></div> : undefined}>
      <TabNav compact label="意见导出范围" items={[{ value: 'round', label: '本轮意见' }, { value: 'history', label: '全部历史意见' }]} selected={mode} onChange={value => { setMode(value as ExportMode); setConfirmClose(false); }} />
      {confirmClose && <p className="notice" role="alert">尚有未保存的修改。放弃修改并关闭后，这些修改不会保留。</p>}
      <div className="revision-export-structured">
        <fieldset disabled={saving} className="revision-export-fields">
          {visibleNotes.map(item => <section className="revision-export-note" key={item.key}>
            <label><strong>{item.title}</strong><textarea aria-label={`${item.title} 修改意见`} maxLength={20000} value={item.text} onChange={event => { setDraft({ ...draft, notes: draft.notes.map(note => note.key === item.key ? { ...note, text: event.target.value } : note) }); setConfirmClose(false); setMessage(''); }} /></label>
          </section>)}
          {!visibleNotes.length && <p className="muted">{mode === 'round' ? '本轮暂无可编辑的分段意见。' : '暂无分段意见。'}</p>}
          <section className="revision-export-overall" aria-label="整场总体意见">
            {visibleRounds.map(item => <label key={item.number}><strong>第{item.number}轮 · 整场总体意见</strong><textarea aria-label={`第${item.number}轮 整场总体意见`} placeholder="填写整场共用的意见…" maxLength={20000} value={item.text} onChange={event => { setDraft({ ...draft, rounds: draft.rounds.map(note => note.number === item.number ? { ...note, text: event.target.value } : note) }); setConfirmClose(false); setMessage(''); }} /></label>)}
            {!visibleRounds.length && <p className="muted">{mode === 'round' ? '整场总体意见按已登记的场次轮次保存；请先选择本场次的修改轮次。' : '暂无按轮次保存的整场总体意见。'}</p>}
          </section>
        </fieldset>
        <footer className="revision-export-save"><button disabled={!changed || saving} onClick={() => { void save(); }}>{saving ? '保存中…' : '保存'}</button><button disabled={!changed || saving} onClick={() => { setDraft({ ...draft, notes: draft.notes.map(item => ({ ...item, text: item.original })), rounds: draft.rounds.map(item => ({ ...item, text: item.original })) }); setConfirmClose(false); setMessage(''); }}>还原</button><div className="revision-export-toolbar"><CopyButton label="复制" text={text} successMessage={changed ? '已复制；有未保存的修改' : '已复制'} /></div><span role="status" className="muted">{changed ? '有未保存的修改' : ''}</span>{message && <FloatingMessage tone="error">{message}</FloatingMessage>}</footer>
      </div>
    </Dialog> };
}
