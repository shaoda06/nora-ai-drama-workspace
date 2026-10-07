import { useEffect, useState } from 'react';
import type { SegmentVideo } from '../api';
import { Dialog } from '../components';
import { editNote, loadNotes, noteKey, saveNote, useSceneNotes } from '../revisionNotes';
import { CopyButton } from './CopyButton';
import { candidateLabel } from './SegmentVideo';

export interface NoteScope { project: string; episode: string; scene: string }
export function RevisionNoteEditor({ scope, segment, current, fileRevision }: { scope: NoteScope; segment: string; current: SegmentVideo; fileRevision: string }) {
  const data = useSceneNotes(scope.project, scope.episode, scope.scene);
  const identity = { segment, stage: current.stage, run: current.run };
  const key = noteKey(identity);
  const draft = data.drafts[key];
  const note = data.notes[key];
  useEffect(() => () => { void saveNote(data.url, key); }, [data.url, key]);
  const status = draft ? { waiting: '等待保存', saving: '保存中…', saved: '已保存', error: '未保存' }[draft.status] : note ? '已保存' : '尚未填写';
  return <div className="revision-note-editor">
    <p className="revision-note-identity">{scope.project} / {scope.episode} / {scope.scene} / {segment} / {current.stage} / {current.approved ? '正式版' : candidateLabel(current.candidateNumber)} · {current.run}</p>
    {data.error && <p className="error" role="alert">修改意见读取失败：{data.error}<button onClick={() => { void loadNotes(data.url); }}>重试读取</button></p>}
    <label htmlFor="revision-note-text">修改意见</label>
    <textarea id="revision-note-text" placeholder="填写此画质、此轮次的修改意见…" maxLength={20000} disabled={!data.loaded} value={draft?.value.text ?? note?.text ?? ''}
      onChange={event => editNote(data.url, { ...identity, text: event.target.value, fileRevision })} onBlur={() => { void saveNote(data.url, key); }} />
    <div className="revision-note-status" role="status"><span>{data.loading ? '正在读取…' : status}</span>{draft?.status === 'error' && <button onClick={() => { void saveNote(data.url, key); }}>重试保存</button>}</div>
    {draft?.error && <p className="error">{draft.error}</p>}
    {note && <p className="muted">更新于 {new Date(note.updatedAt).toLocaleString('zh-CN')}{note.fileRevision !== fileRevision ? '；该意见记录于此版本更新前。' : ''}</p>}
  </div>;
}

export function useRevisionNotesExport(scope: NoteScope, segments: { id: string; videos: SegmentVideo[] }[]) {
  const data = useSceneNotes(scope.project, scope.episode, scope.scene);
  const [text, setText] = useState<string | null>(null);
  const exportNotes = () => {
    const values = { ...data.notes, ...Object.fromEntries(Object.entries(data.drafts).map(([key, draft]) => [key, draft.value])) };
    const notes = Object.values(values).filter(note => note.text.trim()).sort((a, b) => {
      const order = (id: string) => { const index = segments.findIndex(segment => segment.id === id); return index < 0 ? segments.length + Number(id.slice(1)) : index; };
      return order(a.segment) - order(b.segment) || ['一采', '二采', '后处理'].indexOf(a.stage) - ['一采', '二采', '后处理'].indexOf(b.stage) || Number(b.run.slice(1)) - Number(a.run.slice(1));
    });
    setText(`${scope.project} / ${scope.episode} / ${scope.scene} 修改意见\n\n` + (notes.length ? notes.map(note => {
      const video = segments.find(segment => segment.id === note.segment)?.videos.find(video => video.stage === note.stage && video.run === note.run);
      const label = video ? (video.approved ? '正式版' : candidateLabel(video.candidateNumber)) : '';
      const status = data.drafts[noteKey(note)]?.status;
      return `【${note.segment} / ${note.stage} / ${note.run}${label ? ' / ' + label : ''}${status && status !== 'saved' ? ' / 未保存草稿' : ''}】\n${note.text}`;
    }).join('\n\n') : '本场次暂无修改意见。'));
  };
  return { control: <><button disabled={!data.loaded} onClick={exportNotes}>导出修改意见</button>
    {data.error && <span className="error">意见读取失败<button onClick={() => { void loadNotes(data.url); }}>重试</button></span>}</>,
    dialog: text !== null && <Dialog title={`${scope.episode} · ${scope.scene} 导出修改意见`} close={() => setText(null)}>
      <p className="muted">本场次全部画质、全部版本中已填写的意见。此处编辑只影响本次导出稿。</p>
      <textarea className="revision-notes-export" aria-label="导出修改意见文本" value={text} onChange={event => setText(event.target.value)} />
      <CopyButton label="复制" text={text} />
    </Dialog> };
}
