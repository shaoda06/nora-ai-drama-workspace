import { createContext, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get, projectUrl } from './api';
import type { FileItem, Group, RecordData } from './api';

export const PreviewContext = createContext<(item: FileItem) => void>(() => {});
export function Result({ loading, error }: { loading: boolean; error: Error | null }) {
  return error ? <p className="error" role="alert">{error.message}</p> : loading ? <p className="muted" role="status">正在读取资料…</p> : null;
}
export function Rich({ html = '' }: { html?: string }) {
  const preview = useContext(PreviewContext);
  return <div className="prose" onClick={event => {
    const anchor = (event.target as HTMLElement).closest<HTMLAnchorElement>('a[data-doc]');
    if (anchor && anchor.target !== '_blank') {
      event.preventDefault();
      preview({ kind: 'markdown', name: anchor.textContent || '文档', key: anchor.dataset.doc, url: anchor.href });
    }
  }} dangerouslySetInnerHTML={{ __html: html }} />;
}
export function Original({ url, label = '原文件' }: { url?: string; label?: string }) {
  return url ? <a href={url} target="_blank" rel="noopener noreferrer">{label} ↗</a> : null;
}
export function FileLink({ item }: { item: FileItem }) {
  const preview = useContext(PreviewContext);
  const target = item.kind === 'reference' && item.media ? { ...item.media, name: item.name, prompts: item.prompts } : item;
  return <div className="file"><button className="link" onClick={() => preview(target)}>{item.name}</button><Original url={target.url} /></div>;
}
export function FileTree({ items }: { items: FileItem[] }) {
  return <div className="tree">{items.map(item => item.kind === 'group' || item.children || item.files ?
    <Folder key={item.key || item.name} item={item} /> :
    <div key={item.key || item.name}><FileLink item={item} />{item.summary && <p className="muted">{item.summary}</p>}<Rich html={item.statusHtml} /><Rich html={(item as RecordData).sourceHtml} />{(item as RecordData).duration && <p className="muted">实测时长：{(item as RecordData).duration}</p>}</div>)}</div>;
}
function Folder({ item }: { item: FileItem }) {
  const [open, setOpen] = useState(false);
  return <details open={open} onToggle={event => setOpen(event.currentTarget.open)}><summary>{item.name}</summary>
    {open && <FileTree items={item.children || item.files || []} />}</details>;
}
export function Groups({ groups = [] }: { groups?: Group[] }) {
  return <div className="groups">{groups.map(group => <Folder key={group.name} item={{ kind: 'group', ...group }} />)}</div>;
}
export function Document({ value: latest }: { value: RecordData }) {
  const [value, setValue] = useState(latest);
  const changed = (value.html || value.bodyHtml) !== (latest.html || latest.bodyHtml);
  const body = value.html || value.bodyHtml || '';
  const ref = useRef<HTMLDivElement>(null);
  const [headings, setHeadings] = useState<{ id: string; text: string; level: string }[]>([]);
  useEffect(() => {
    setHeadings(Array.from(ref.current!.querySelectorAll('h2,h3')).map((heading, i) => {
      if (!heading.id) heading.id = `chapter-${i}`;
      return { id: heading.id, text: heading.textContent || '', level: heading.tagName };
    }));
  }, [body]);
  return <div className="document">
    {changed && <p className="notice document-update">本文有新版本，当前阅读位置保持不变。<button onClick={() => setValue(latest)}>读取新版本</button></p>}
    <div className="meta">{value.meta && Object.entries(value.meta).filter(([key]) => key !== '确认状态').map(([key, text]) => <span key={key}>{key}：{String(text)}</span>)}<Original url={value.url} /></div>
    <Rich html={value.confirmationHtml} /><Rich html={value.boundaryHtml} />
    {value.introHtml && <details><summary>说明与来源</summary><Rich html={value.introHtml} /></details>}
    {headings.length > 0 && <details className="chapters"><summary>章节导航</summary>{headings.map(h => <button key={h.id} className={'link ' + h.level} onClick={() => ref.current!.querySelectorAll('[id]').forEach(el => { if (el.id === h.id) { el.scrollIntoView({ behavior: 'auto', block: 'start' }); (el as HTMLElement).tabIndex = -1; (el as HTMLElement).focus({ preventScroll: true }); } })}>{h.text}</button>)}</details>}
    <div ref={ref}><Rich html={body} /></div><Groups groups={latest.groups} />
  </div>;
}
export function Dialog({ title, children, close }: { title: string; children: ReactNode; close: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const dialog = ref.current!; dialog.showModal(); return () => dialog.close(); }, []);
  return <dialog ref={ref} onCancel={close} onClick={event => { if (event.target === event.currentTarget) close(); }}><header><h2>{title}</h2><button aria-label="关闭" onClick={close}>关闭 ×</button></header><div className="dialog-body">{children}</div></dialog>;
}
export function Preview({ project, item, revision, close }: { project: string; item: FileItem; revision: number; close: () => void }) {
  // Keep the opened item and revision until the user chooses to load newer text.
  const [openedRevision, setOpenedRevision] = useState(revision);
  const [mediaError, setMediaError] = useState('');
  const kind = item.kind;
  const text = ['markdown', 'json', 'text', 'log', 'outline'].includes(kind) || /\.(md|json|txt|log)(#.*)?$/i.test(item.key || item.name);
  const key = (item.key || '').split('#')[0];
  const query = useQuery({ queryKey: ['document', project, key, openedRevision], queryFn: () => get<RecordData>(`${projectUrl(project)}/document?path=${encodeURIComponent(key)}`), enabled: text });
  useEffect(() => {
    const hash = item.key?.split('#')[1];
    if (hash && query.data) requestAnimationFrame(() => {
      document.querySelectorAll('dialog [id]').forEach(el => { if (el.id === decodeURIComponent(hash)) el.scrollIntoView(); });
    });
  }, [query.data, item.key]);
  const image = kind === 'image' || /\.(png|jpe?g|webp|gif)$/i.test(item.name);
  const video = kind === 'video' || /\.(mp4|webm|mov)$/i.test(item.name);
  const audio = kind === 'audio' || /\.(mp3|wav|ogg|flac|m4a)$/i.test(item.name);
  return <Dialog title={item.name} close={close}>
    <Original url={item.url} />
    {text && revision !== openedRevision && <p className="notice document-update">项目资料有更新。<button onClick={() => setOpenedRevision(revision)}>读取新版本</button></p>}
    {text ? <><Result loading={query.isPending} error={query.error} />{query.data && (query.data.html ? <Document value={query.data} /> : <><p>{query.data.notice}</p><pre>{query.data.text}</pre></>)}</> :
      image ? <img className="preview-image" src={item.url} alt={item.name} onError={() => setMediaError('图片无法加载，请使用原文件入口。')} /> :
      video ? <video controls preload="metadata" src={item.url} onError={() => setMediaError('视频无法加载，请使用原文件入口。')} /> :
      audio ? <audio controls preload="metadata" src={item.url} onError={() => setMediaError('音频无法加载，请使用原文件入口。')} /> : <p>此格式暂不支持页内预览，请打开原文件。</p>}
    {mediaError && <p className="error" role="alert">{mediaError}</p>}
    {item.prompts && <details><summary>对应提示词</summary><p>英文</p><pre>{item.prompts.english}</pre><p>中文</p><pre>{item.prompts.chinese}</pre></details>}
  </Dialog>;
}
