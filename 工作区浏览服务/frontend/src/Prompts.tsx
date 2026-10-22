import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useBlocker } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { PageHeader } from './components/PageHeader';
import { CopyButton } from './components/CopyButton';
import './Prompts.css';

type Category = { path: string; revision: string };
type Prompt = { path: string; title: string; category: string; modified: number; revision: string; snippet?: string };
type Document = Prompt & { body: string };
type Trash = { id: string; original: string; deleted: string; revision: string; body?: string };
type Snapshot = { categories: Category[]; prompts: Prompt[] };
type Draft = { title: string; body: string; category: string };
const parentOf = (path: string) => path.split('/').slice(0, -1).join('/');
const nameOf = (path: string) => path.split('/').at(-1)!;
const titleOf = (path: string) => nameOf(path).slice(0, -3);
const formatTime = (value: number) => new Date(value * 1000).toLocaleString('zh-CN');
async function api<T>(url: string, method = 'GET', data?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/prompts${url}`, { method, signal, headers: data === undefined ? undefined : { 'Content-Type': 'application/json' }, body: data === undefined ? undefined : JSON.stringify(data) });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '提交内容不符合要求，请检查名称与正文。');
  return result;
}
function Dialog({ title, close, children }: { title: string; close: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const node = ref.current!; node.showModal(); return () => node.close(); }, []);
  return <dialog ref={ref} className="prompt-dialog" aria-label={title} onCancel={event => { event.preventDefault(); close(); }}><h2>{title}</h2>{children}</dialog>;
}

export default function Prompts() {
  const client = useQueryClient();
  const [category, setCategory] = useState('');
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState('all');
  const [view, setView] = useState<'library' | 'trash'>('library');
  const [step, setStep] = useState<'categories' | 'list' | 'detail'>('list');
  const [saved, setSaved] = useState<Document | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [deleted, setDeleted] = useState<Trash | null>(null);
  const [mode, setMode] = useState<'text' | 'preview'>('text');
  const [html, setHtml] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<(() => void) | null>(null);
  const [categoryEdit, setCategoryEdit] = useState<{ source: Category | null; name: string; parent: string } | null>(null);
  const [restore, setRestore] = useState<{ item: Trash; title: string; category: string } | null>(null);
  const [confirm, setConfirm] = useState<{ title: string; text: string; action: () => Promise<void> } | null>(null);
  const [modalError, setModalError] = useState('');
  const opening = useRef(0);
  const latestSaved = useRef<Document | null>(null);
  const dirty = draft !== null && (!saved || draft.title !== saved.title || draft.body !== saved.body || draft.category !== saved.category);
  const blocker = useBlocker(({ currentLocation, nextLocation }) => (dirty || busy) && currentLocation.pathname !== nextLocation.pathname);
  const snapshot = useQuery({ queryKey: ['prompts'], queryFn: ({ signal }) => api<Snapshot>('', 'GET', undefined, signal), refetchInterval: 5000, refetchOnWindowFocus: true });
  const trash = useQuery({ queryKey: ['prompt-trash'], queryFn: ({ signal }) => api<Trash[]>('/trash', 'GET', undefined, signal), enabled: view === 'trash', refetchInterval: 5000, refetchOnWindowFocus: true });
  const results = useQuery({ queryKey: ['prompt-search', query, scope === 'all' ? '' : category], queryFn: ({ signal }) => api<Prompt[]>(`/search?q=${encodeURIComponent(query)}&category=${encodeURIComponent(scope === 'all' ? '' : category)}`, 'GET', undefined, signal), enabled: !!query && view === 'library', refetchInterval: 5000, refetchOnWindowFocus: true });
  const categories = snapshot.data?.categories || [];
  const items = query ? results.data || [] : (snapshot.data?.prompts || []).filter(item => item.category === category);
  const changed = !!saved && !!snapshot.data && snapshot.data.prompts.find(item => item.path === saved.path)?.revision !== saved.revision;
  const categoryMissing = !!category && !!snapshot.data && !categories.some(item => item.path === category);
  useEffect(() => { const timer = setTimeout(() => setQuery(search.trim()), 250); return () => clearTimeout(timer); }, [search]);
  useEffect(() => {
    const refresh = () => { if (document.visibilityState === 'visible') void client.invalidateQueries({ predicate: q => ['prompts', 'prompt-trash', 'prompt-search'].includes(String(q.queryKey[0])) }); };
    document.addEventListener('visibilitychange', refresh);
    return () => document.removeEventListener('visibilitychange', refresh);
  }, [client]);
  useEffect(() => {
    if (!dirty && !busy) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [dirty, busy]);
  async function refresh() { await client.invalidateQueries({ predicate: q => ['prompts', 'prompt-trash', 'prompt-search'].includes(String(q.queryKey[0])) }); }
  async function run(action: () => Promise<void>, modal = false) {
    setBusy(true); setError(''); setNotice(''); setModalError('');
    try { await action(); }
    catch (failure) { (modal ? setModalError : setError)((failure as Error).message); }
    finally { setBusy(false); }
  }
  function accept(doc: Document) { latestSaved.current = doc; setSaved(doc); setDraft({ title: doc.title, body: doc.body, category: doc.category }); setDeleted(null); setMode('text'); setStep('detail'); }
  function guard(action: () => void) { if (busy) return; if (dirty) setPending(() => action); else action(); }
  function clearSelection() { opening.current++; setSaved(null); setDraft(null); setDeleted(null); setMode('text'); }
  function selectCategory(path: string) { guard(() => { clearSelection(); setCategory(path); setView('library'); setStep('list'); setError(''); }); }
  function openDocument(path: string) {
    guard(() => { const sequence = ++opening.current; void run(async () => { const doc = await api<Document>(`/document?path=${encodeURIComponent(path)}`); if (opening.current === sequence) accept(doc); }); });
  }
  async function save(): Promise<boolean> {
    if (!draft) return true;
    setBusy(true); setError(''); setNotice('');
    try {
      const doc = await api<Document>('/document', 'POST', { ...draft, source: saved?.path ?? null, revision: saved?.revision ?? null });
      accept(doc); setCategory(doc.category); setNotice('已保存'); await refresh(); return true;
    } catch (failure) { setError((failure as Error).message); return false; }
    finally { setBusy(false); }
  }
  const unsavedOpen = !!pending || blocker.state === 'blocked';
  function proceed() { const next = pending; setPending(null); if (blocker.state === 'blocked') blocker.proceed(); else next?.(); }
  function cancelPending() { setPending(null); if (blocker.state === 'blocked') blocker.reset(); }
  function categoryOptions(exclude?: string) { return <><option value="">主目录</option>{categories.filter(item => !exclude || (item.path !== exclude && !item.path.startsWith(exclude + '/'))).map(item => <option key={item.path} value={item.path}>{item.path}</option>)}</>; }
  function openCategoryEdit(edit: NonNullable<typeof categoryEdit>) { guard(() => {
    setModalError('');
    if (edit.source) {
      const source = client.getQueryData<Snapshot>(['prompts'])!.categories.find(item => item.path === edit.source!.path);
      if (!source) { setError('分类已在外部移动或删除，请重新选择。'); return; }
      setCategoryEdit({ ...edit, source });
    } else setCategoryEdit(edit);
  }); }
  function ask(title: string, text: string, action: () => Promise<void>) { setModalError(''); setConfirm({ title, text, action }); }
  function categoryTree(parent: string): ReactNode { return categories.filter(item => parentOf(item.path) === parent).map(item => <li key={item.path}>
    <button disabled={busy} aria-current={view === 'library' && category === item.path ? 'page' : undefined} title={item.path} onClick={() => selectCategory(item.path)}>▱ {nameOf(item.path)}</button>
    <ul>{categoryTree(item.path)}</ul></li>); }
  const loadError = snapshot.error || (view === 'trash' ? trash.error : query ? results.error : null);
  return <div className="prompt-page" data-prompt-unsaved={dirty || busy}>
    <PageHeader title="提示词管理" description="把常用提示词整理在一起，随时查找、修改和复制。" actions={<button disabled={busy} onClick={() => guard(() => { clearSelection(); setView(view === 'trash' ? 'library' : 'trash'); setStep('list'); })}>{view === 'trash' ? '返回提示词库' : '回收站'}</button>} />
    {loadError && <div className="error" role="alert">{loadError.message}<button onClick={() => void refresh()}>重试</button></div>}
    {error && <div className="error" role="alert">{error}</div>}{notice && <p className="notice" role="status">{notice}</p>}
    <div className="prompt-toolbar"><input type="search" aria-label="搜索提示词" placeholder="搜索标题或正文…" value={search} disabled={view === 'trash'} onChange={e => setSearch(e.target.value)} /><select aria-label="搜索范围" value={scope} disabled={view === 'trash'} onChange={e => setScope(e.target.value)}><option value="all">全库搜索</option><option value="category">当前分类及子分类</option></select>
      <button disabled={busy || view === 'trash' || categoryMissing} onClick={() => guard(() => { clearSelection(); setDraft({ title: '', body: '', category }); setStep('detail'); setError(''); })}>＋ 新建提示词</button></div>
    <div className="prompt-layout" data-step={step}>
      <aside className="prompt-categories" aria-label="分类">
        <div className="prompt-panel-heading"><h2>分类</h2><button disabled={busy || categoryMissing} onClick={() => openCategoryEdit({ source: null, name: '', parent: category })}>新建分类</button></div>
        <button className="prompt-root" disabled={busy} aria-current={!category && view === 'library' ? 'page' : undefined} onClick={() => selectCategory('')}>▱ 主目录</button>
        <ul className="prompt-tree">{categoryTree('')}</ul>
        {categories.length === 0 && <p className="muted">还没有分类。可以直接保存提示词，也可以创建自己的分类。</p>}
        {!!category && !categoryMissing && <div className="prompt-category-actions"><small>当前：{category}</small><button disabled={busy} onClick={() => openCategoryEdit({ source: categories.find(item => item.path === category)!, name: nameOf(category), parent: parentOf(category) })}>改名 / 移动分类</button><button disabled={busy} onClick={() => guard(() => ask('删除空分类', `删除“${category}”？其中有内容时不会删除。`, async () => {
          const selected = client.getQueryData<Snapshot>(['prompts'])!.categories.find(item => item.path === category);
          if (!selected) throw new Error('分类已在外部移动或删除，请重新选择。');
          await api('/categories', 'DELETE', { path: category, revision: selected.revision }); clearSelection(); setCategory(parentOf(category)); setConfirm(null); await refresh();
        }))}>删除分类</button></div>}
      </aside>
      <section className="prompt-list" aria-label={view === 'trash' ? '回收站列表' : '提示词列表'}>
        <div className="prompt-panel-heading"><button className="prompt-mobile" onClick={() => setStep('categories')}>‹ 分类</button><h2>{view === 'trash' ? '回收站' : query ? '搜索结果' : nameOf(category) || '主目录'}</h2><small>{view === 'trash' ? trash.data?.length || 0 : items.length} 份</small></div>
        {categoryMissing && view === 'library' && <p role="status">当前分类已被移动或删除。<button onClick={() => selectCategory('')}>返回主目录</button></p>}
        {(snapshot.isPending || (view === 'trash' && trash.isPending) || (query && results.isPending)) && <p role="status">正在读取…</p>}
        {view === 'library' ? items.map(item => <button key={item.path} className="prompt-list-item" disabled={busy} aria-current={saved?.path === item.path ? 'page' : undefined} onClick={() => openDocument(item.path)}><strong>{item.title}</strong><small>{item.category || '主目录'}</small>{item.snippet && <p>{item.snippet}</p>}<small>{formatTime(item.modified)}</small></button>) : trash.data?.map(item => <button className="prompt-list-item" key={item.id} disabled={busy} aria-current={deleted?.id === item.id ? 'page' : undefined} onClick={() => void run(async () => { const doc = await api<Trash>(`/trash/document?id=${item.id}`); clearSelection(); setDeleted(doc); setStep('detail'); })}><strong>{titleOf(item.original)}</strong><small>{parentOf(item.original) || '主目录'}</small><small>删除于 {new Date(item.deleted).toLocaleString('zh-CN')}</small></button>)}
        {!snapshot.isPending && view === 'library' && !items.length && <p className="prompt-empty">{query ? '没有找到匹配的提示词。' : '这里还没有提示词。点击“新建提示词”开始。'}</p>}
        {view === 'trash' && trash.data?.length === 0 && <p className="prompt-empty">回收站是空的。</p>}
      </section>
      <section className="prompt-detail" aria-label="提示词详情">
        <button className="prompt-mobile" disabled={busy} onClick={() => guard(() => { clearSelection(); setStep('list'); })}>‹ 返回列表</button>
        {draft ? <>
          <div className="prompt-detail-heading"><span>{saved ? '编辑提示词' : '新建提示词'}</span><small>{dirty ? '尚未保存' : '已保存到本地文件'}</small></div>
          {changed && <div className="prompt-warning" role="status">这份提示词已在外部修改、移动或删除。当前内容已保留。<button disabled={busy} onClick={() => openDocument(saved!.path)}>重新载入</button></div>}
          <label>标题<input aria-label="提示词标题" value={draft.title} disabled={busy} onChange={e => setDraft({ ...draft, title: e.target.value })} placeholder="为提示词起个名字" /></label>
          <label>所在分类<select aria-label="提示词所在分类" value={draft.category} disabled={busy} onChange={e => setDraft({ ...draft, category: e.target.value })}>{categoryOptions()}{draft.category && !categories.some(item => item.path === draft.category) && <option value={draft.category}>{draft.category}（已不存在）</option>}</select></label>
          <div className="prompt-editor-tabs"><button aria-pressed={mode === 'text'} disabled={busy} onClick={() => setMode('text')}>文本编辑</button><button aria-pressed={mode === 'preview'} disabled={busy} onClick={() => void run(async () => { const result = await api<{ html: string }>('/preview', 'POST', { body: draft.body }); setHtml(result.html); setMode('preview'); })}>Markdown 预览</button></div>
          {mode === 'text' ? <textarea aria-label="提示词正文" className="prompt-body" value={draft.body} disabled={busy} spellCheck={false} placeholder="输入或粘贴提示词正文…" onChange={e => setDraft({ ...draft, body: e.target.value })} /> : <article className="prompt-preview" dangerouslySetInnerHTML={{ __html: html }} />}
          <div className="prompt-actions"><button className="prompt-primary" disabled={busy || !draft.title.trim() || !dirty} onClick={() => void save()}>{busy ? '处理中…' : '保存'}</button><CopyButton label="复制正文" text={draft.body} />{saved && <button disabled={busy} onClick={() => guard(() => { const current = latestSaved.current!; ask('移入回收站', `将“${current.title}”移入回收站？之后可以恢复。`, async () => { await api('/document', 'DELETE', { path: current.path, revision: current.revision }); clearSelection(); setConfirm(null); setStep('list'); setNotice('已移入回收站'); await refresh(); }); })}>删除提示词</button>}</div>
        </> : deleted ? <>
          <h2>{titleOf(deleted.original)}</h2><small>原位置：{deleted.original}</small><p className="muted">回收站内容不会自动清空。</p><pre className="prompt-trash-body">{deleted.body}</pre>
          <div className="prompt-actions"><button disabled={busy} onClick={() => { setModalError(''); setRestore({ item: deleted, title: titleOf(deleted.original), category: parentOf(deleted.original) }); }}>恢复提示词</button><CopyButton label="复制正文" text={deleted.body || ''} /><button className="prompt-danger" disabled={busy} onClick={() => ask('彻底删除提示词', `“${titleOf(deleted.original)}”将永久删除，无法从回收站恢复。`, async () => { await api('/trash', 'DELETE', { id: deleted.id, revision: deleted.revision }); clearSelection(); setConfirm(null); setStep('list'); await refresh(); })}>彻底删除</button></div>
        </> : <div className="prompt-empty"><span className="prompt-empty-icon">▤</span><h2>你的提示词资料库</h2><p>选择一份提示词查看和编辑，<br />或新建一份，把好用的写法留下来。</p></div>}
      </section>
    </div>
    {unsavedOpen && <Dialog title="修改尚未保存" close={() => { if (!busy) cancelPending(); }}><p>保存后继续，或放弃这次修改。</p>{error && <p className="error" role="alert">{error}</p>}<div className="prompt-actions"><button disabled={busy || !draft?.title.trim()} onClick={async () => { if (await save()) proceed(); }}>保存并继续</button><button disabled={busy} onClick={() => { clearSelection(); proceed(); }}>放弃修改</button><button disabled={busy} onClick={cancelPending}>继续编辑</button></div></Dialog>}
    {categoryEdit && <Dialog title={categoryEdit.source ? '修改分类' : '新建分类'} close={() => { if (!busy) setCategoryEdit(null); }}><form onSubmit={event => { event.preventDefault(); void run(async () => {
      const source = categoryEdit.source;
      const result = await api<Category>('/categories', source ? 'PUT' : 'POST', { parent: categoryEdit.parent, name: categoryEdit.name, source: source?.path || '', revision: source?.revision || '' });
      clearSelection(); setCategory(result.path); setView('library'); setStep('list'); setCategoryEdit(null); await refresh();
    }, true); }}><label>分类名称<input autoFocus aria-label="分类名称" value={categoryEdit.name} disabled={busy} onChange={e => setCategoryEdit({ ...categoryEdit, name: e.target.value })} /></label><label>上级分类<select aria-label="上级分类" value={categoryEdit.parent} disabled={busy} onChange={e => setCategoryEdit({ ...categoryEdit, parent: e.target.value })}>{categoryOptions(categoryEdit.source?.path)}</select></label>{modalError && <p className="error" role="alert">{modalError}</p>}<div className="prompt-actions"><button type="submit" disabled={busy || !categoryEdit.name.trim()}>保存分类</button><button type="button" disabled={busy} onClick={() => setCategoryEdit(null)}>取消</button></div></form></Dialog>}
    {restore && <Dialog title="恢复提示词" close={() => { if (!busy) setRestore(null); }}><form onSubmit={event => { event.preventDefault(); void run(async () => {
      const doc = await api<Document>('/trash/restore', 'POST', { id: restore.item.id, revision: restore.item.revision, title: restore.title, category: restore.category });
      setView('library'); setCategory(doc.category); accept(doc); setRestore(null); setNotice('已恢复'); await refresh();
    }, true); }}><label>标题<input aria-label="恢复标题" value={restore.title} disabled={busy} onChange={e => setRestore({ ...restore, title: e.target.value })} /></label><label>恢复到<select aria-label="恢复到分类" value={restore.category} disabled={busy} onChange={e => setRestore({ ...restore, category: e.target.value })}>{categoryOptions()}{restore.category && !categories.some(item => item.path === restore.category) && <option value={restore.category}>{restore.category}（重建原分类）</option>}</select></label><p>原分类已不存在时，恢复会重新创建该分类。</p>{modalError && <p className="error" role="alert">{modalError}</p>}<div className="prompt-actions"><button type="submit" disabled={busy || !restore.title.trim()}>确认恢复</button><button type="button" disabled={busy} onClick={() => setRestore(null)}>取消</button></div></form></Dialog>}
    {confirm && <Dialog title={confirm.title} close={() => { if (!busy) setConfirm(null); }}><p>{confirm.text}</p>{modalError && <p className="error" role="alert">{modalError}</p>}<div className="prompt-actions"><button disabled={busy} onClick={() => void run(confirm.action, true)}>确认</button><button disabled={busy} onClick={() => setConfirm(null)}>取消</button></div></Dialog>}
  </div>;
}
