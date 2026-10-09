import { useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import type { FileItem } from '../api';
import { Dialog, Rich } from '../components';
import { CopyButton } from './CopyButton';
import type { NoteScope } from './RevisionNotes';

type Row = { key: string; kind: 'segment' | 'shot' | 'field' | 'separator' | 'text'; html: string; text: string; label?: string; editable?: boolean; segmentIndex?: number };

function StoryboardField({ row, value, onChange }: { row: Row; value: string; onChange: (text: string) => void }) {
  const input = useRef<HTMLSpanElement>(null);
  const name = `${row.key.split('/').slice(0, 2).join(' ')} ${row.label || '正文'}`;
  useLayoutEffect(() => {
    if (input.current!.innerText !== value) input.current!.textContent = value;
  }, [value]);
  return <div className="scene-revision-editor" onClick={event => {
    if (event.target === event.currentTarget || (event.target as HTMLElement).tagName === 'STRONG') input.current!.focus();
  }}>
    {value !== row.text && <button className="scene-revision-restore" aria-label={`还原 ${name}`} onClick={() => onChange(row.text)}>还原</button>}
    {row.label && <><strong>{row.label}</strong>：</>}
    <span ref={input} className="scene-revision-input" role="textbox" aria-label={name} aria-multiline="true" contentEditable="plaintext-only" suppressContentEditableWarning onInput={event => onChange(event.currentTarget.innerText)} />
  </div>;
}

function inlineMarkdown(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return node.textContent!;
  const text = Array.from(node.childNodes).map(inlineMarkdown).join('');
  if (!(node instanceof Element)) return text;
  if (node.tagName === 'A') return `[${text}](${node.getAttribute('href')})`;
  if (node.tagName === 'STRONG') return `**${text}**`;
  if (node.tagName === 'EM') return `*${text}*`;
  if (node.tagName === 'CODE') return '`' + text + '`';
  if (node.tagName === 'BR') return '\n';
  return text;
}

export function SceneStoryboardEditor({ scope, segments }: { scope: NoteScope; segments: NonNullable<FileItem['segments']>[string] }) {
  const rows = useMemo(() => segments.flatMap((segment, segmentIndex) => {
    const document = new DOMParser().parseFromString(segment.scriptHtml, 'text/html');
    const elements = Array.from(document.body.children);
    let shot = '';
    return [{ key: segment.id, kind: 'segment', html: '', text: `分段 ${segment.id}`, segmentIndex } as Row, ...elements.flatMap((element, index): Row[] => {
      if (element.tagName === 'TABLE') return [];
      if (element.tagName === 'HR') return index === elements.length - 1 ? [] : [{ key: `${segment.id}/${index}`, kind: 'separator', html: '', text: '' }];
      if (element.tagName === 'H4') {
        shot = element.textContent!.trim();
        return [{ key: `${segment.id}/${shot}`, kind: 'shot', html: element.outerHTML, text: shot }];
      }
      const label = element.tagName === 'P' ? element.querySelector(':scope > strong:first-child') : null;
      if (label) {
        const field = label.textContent!.replace(/[：:]$/, '').trim();
        const value = element.cloneNode(true) as HTMLElement;
        value.querySelector('strong')!.remove();
        return [{ key: `${segment.id}/${shot}/${field}/${index}`, kind: 'field', html: element.outerHTML, label: field,
          text: inlineMarkdown(value).replace(/^\s*[：:]\s*/, '').trim(), editable: field !== '时间' && field !== '时长' }];
      }
      return [{ key: `${segment.id}/${shot}/${index}`, kind: 'text', html: element.outerHTML, text: inlineMarkdown(element), editable: true }];
    })];
  }), [segments]);
  const storageKey = `nora-storyboard-draft/${scope.project}/${scope.episode}/${scope.scene}`;
  const [draft, setDraft] = useState<Record<string, string>>(() => JSON.parse(sessionStorage.getItem(storageKey) || '{}'));
  const [exportText, setExportText] = useState<string | null>(null);
  const edit = (row: Row, text: string) => {
    const next = { ...draft };
    if (text === row.text) delete next[row.key]; else next[row.key] = text;
    sessionStorage.setItem(storageKey, JSON.stringify(next));
    setDraft(next);
  };
  const changed = rows.some(row => row.editable && draft[row.key] !== undefined && draft[row.key] !== row.text);
  const exportStoryboard = () => {
    const content: string[] = [];
    let segment = '', shot = '', writtenSegment = '', writtenShot = '';
    for (const row of rows) {
      if (row.kind === 'segment') segment = row.text;
      if (row.kind === 'shot') shot = row.text;
      if (!row.editable || draft[row.key] === undefined || draft[row.key] === row.text) continue;
      if (segment !== writtenSegment) { content.push(segment); writtenSegment = segment; }
      if (shot !== writtenShot) { content.push(shot); writtenShot = shot; }
      content.push(row.label ? `${row.label}：${draft[row.key].trimEnd()}` : draft[row.key].trimEnd());
    }
    setExportText(`以下是我对${scope.episode}-${scope.scene}-场次分镜的修改意见：\n\`\`\`\n${content.join('\n\n').replace(/\n{3,}/g, '\n\n')}\n\`\`\``);
  };
  const download = () => {
    const url = URL.createObjectURL(new Blob([exportText!], { type: 'text/markdown;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url;
    link.download = `${scope.episode}-${scope.scene}-场次分镜-修改意见.md`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <>
    <div className="scene-revision-layout" style={{ '--revision-rows': rows.length + 1 } as CSSProperties}>
      {[false, true].map(editable => <section className="scene-revision-pane" aria-label={editable ? '修改场次分镜正文' : '当前场次分镜正文'} key={String(editable)}>
        <div className="scene-revision-heading"><strong>{editable ? '修改内容' : '原文'}</strong>{editable && <button disabled={!changed} onClick={exportStoryboard}>导出分镜</button>}</div>
        {rows.map(row => <div className={`scene-revision-row scene-revision-${row.kind}${row.editable ? ' scene-revision-editable' : ''}`} key={row.key} style={row.kind === 'segment' ? { '--segment-index': row.segmentIndex } as CSSProperties : undefined}>
          {row.kind === 'segment' ? <h3>{row.text}</h3> : row.kind === 'separator' ? <hr /> : editable && row.editable ? <StoryboardField row={row} value={draft[row.key] ?? row.text} onChange={text => edit(row, text)} /> : <Rich html={row.html} />}
        </div>)}
      </section>)}
    </div>
    {exportText !== null && <Dialog title={`${scope.episode} · ${scope.scene} 导出分镜`} close={() => setExportText(null)}>
      <div className="revision-export-actions"><CopyButton label="复制" text={exportText} /><button onClick={download}>下载 Markdown</button></div>
      <textarea className="revision-notes-export scene-revision-export" aria-label="导出分镜文本" readOnly value={exportText} />
    </Dialog>}
  </>;
}
