import { PageCheckStatus } from './components/PageCheckStatus';
import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Dialog, Rich } from './components';
import { SearchField } from './components/SearchField';
import { useBlocker } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { PageHeader } from './components/PageHeader';
import { CopyButton } from './components/CopyButton';
import { TabSelect } from './components/TabSelect';
import { Switch } from './components/Switch';
import { FloatingMessage, useNotify } from './components/Notifications';
import './Prompts.css';

type Category = { path: string; revision: string };
type Prompt = { path: string; title: string; category: string; modified: number; revision: string; local_only: boolean; snippet?: string };
type Document = Prompt & { body: string };
type Trash = { id: string; original: string; deleted: string; revision: string; local_only: boolean; body?: string };
type Snapshot = { categories: Category[]; prompts: Prompt[] };
type Draft = { title: string; body: string; category: string; local_only: boolean };
const parentOf = (path: string) => path.split('/').slice(0, -1).join('/');
const nameOf = (path: string) => path.split('/').at(-1)!;
const titleOf = (path: string) => nameOf(path).slice(0, -3);
async function api<T>(url: string, method = 'GET', data?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/prompts${url}`, { method, signal, headers: data === undefined ? undefined : { 'Content-Type': 'application/json' }, body: data === undefined ? undefined : JSON.stringify(data) });
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '提交内容不符合要求，请检查名称与正文。');
  return result;
}
export default function Prompts() {
  const client = useQueryClient();
  const notify = useNotify();
  const [category, setCategory] = useState('');
  const [expandedPath, setExpandedPath] = useState('');
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [scope, setScope] = useState('all');
  const [view, setView] = useState<'library' | 'trash'>('library');
  const [step, setStep] = useState<'categories' | 'detail'>('categories');
  const [saved, setSaved] = useState<Document | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [deleted, setDeleted] = useState<Trash | null>(null);
  const [mode, setMode] = useState<'text' | 'preview'>('preview');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<(() => void) | null>(null);
  const [categoryEdit, setCategoryEdit] = useState<{ source: Category | null; name: string; parent: string } | null>(null);
  const [restore, setRestore] = useState<{ item: Trash; title: string; category: string } | null>(null);
  const [confirm, setConfirm] = useState<{ title: string; text: string; action: () => Promise<void> } | null>(null);
  const [modalError, setModalError] = useState('');
  const [categoryDelete, setCategoryDelete] = useState(false);
  const opening = useRef(0);
  const latestSaved = useRef<Document | null>(null);
  const dirty = draft !== null && (!saved || draft.title !== saved.title || draft.body !== saved.body || draft.category !== saved.category || draft.local_only !== saved.local_only);
  const blocker = useBlocker(({ currentLocation, nextLocation }) => (dirty || busy) && currentLocation.pathname !== nextLocation.pathname);
  const snapshot = useQuery({ queryKey: ['prompts'], queryFn: ({ signal }) => api<Snapshot>('', 'GET', undefined, signal), refetchInterval: 5000, refetchOnWindowFocus: true });
  const trash = useQuery({ queryKey: ['prompt-trash'], queryFn: ({ signal }) => api<Trash[]>('/trash', 'GET', undefined, signal), enabled: view === 'trash', refetchInterval: 5000, refetchOnWindowFocus: true });
  const results = useQuery({ queryKey: ['prompt-search', query, scope === 'all' ? '' : category], queryFn: ({ signal }) => api<Prompt[]>(`/search?q=${encodeURIComponent(query)}&category=${encodeURIComponent(scope === 'all' ? '' : category)}`, 'GET', undefined, signal), enabled: !!query && view === 'library', refetchInterval: 5000, refetchOnWindowFocus: true });
  const preview = useQuery({ queryKey: ['prompt-preview', mode === 'preview' ? draft?.body : null], queryFn: ({ signal }) => api<{ html: string }>('/preview', 'POST', { body: draft!.body }, signal), enabled: !!draft && mode === 'preview', retry: false });
  const categories = snapshot.data?.categories || [];
  const prompts = snapshot.data?.prompts || [];
  const items = results.data || [];
  const categoryCounts = new Map<string, number>();
  for (const prompt of prompts) {
    for (let path = prompt.category; path; path = parentOf(path)) categoryCounts.set(path, (categoryCounts.get(path) || 0) + 1);
  }
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
    setBusy(true); setError(''); setModalError('');
    try { await action(); }
    catch (failure) { (modal ? setModalError : setError)((failure as Error).message); }
    finally { setBusy(false); }
  }
  function accept(doc: Document, resetMode = false) { latestSaved.current = doc; setSaved(doc); setDraft({ title: doc.title, body: doc.body, category: doc.category, local_only: doc.local_only }); setDeleted(null); if (resetMode) setMode('preview'); setStep('detail'); }
  function guard(action: () => void) { if (busy) return; if (dirty) setPending(() => action); else action(); }
  function clearSelection() { opening.current++; setSaved(null); setDraft(null); setDeleted(null); setMode('preview'); }
  function selectCategory(path: string) { guard(() => { clearSelection(); setCategory(path); setSearch(''); setView('library'); setStep('categories'); setError(''); }); }
  function openDocument(path: string, fromTree = false) {
    guard(() => { const sequence = ++opening.current; void run(async () => { const doc = await api<Document>(`/document?path=${encodeURIComponent(path)}`); if (opening.current === sequence) { accept(doc, true); if (fromTree) { setCategory(doc.category); setView('library'); setSearch(''); } } }); });
  }
  async function save(): Promise<boolean> {
    if (!draft) return true;
    setBusy(true); setError('');
    try {
      const doc = await api<Document>('/document', 'POST', { ...draft, source: saved?.path ?? null, revision: saved?.revision ?? null });
      accept(doc); setCategory(doc.category); notify('已保存'); await refresh(); return true;
    } catch (failure) { setError((failure as Error).message); return false; }
    finally { setBusy(false); }
  }
  const unsavedOpen = !!pending || blocker.state === 'blocked';
  function proceed() { const next = pending; setPending(null); if (blocker.state === 'blocked') blocker.proceed(); else next?.(); }
  function cancelPending() { setPending(null); if (blocker.state === 'blocked') blocker.reset(); }
  function categoryOptions(exclude?: string) { return [{ value: '', label: '主目录' }, ...categories.filter(item => !exclude || (item.path !== exclude && !item.path.startsWith(exclude + '/'))).map(item => ({ value: item.path, label: item.path }))]; }
  function openCategoryEdit(edit: NonNullable<typeof categoryEdit>) { guard(() => {
    setModalError(''); setCategoryDelete(false);
    if (edit.source) {
      const source = client.getQueryData<Snapshot>(['prompts'])!.categories.find(item => item.path === edit.source!.path);
      if (!source) { setError('分类已在外部移动或删除，请重新选择。'); return; }
      setCategoryEdit({ ...edit, source });
    } else setCategoryEdit(edit);
  }); }
  function ask(title: string, text: string, action: () => Promise<void>) { setModalError(''); setConfirm({ title, text, action }); }
  function categoryTree(parent: string): ReactNode { return <>
    {categories.filter(item => parentOf(item.path) === parent).map(item => {
      const expanded = expandedPath === item.path || expandedPath.startsWith(item.path + '/');
      return <li key={item.path}>
        <div className="prompt-tree-row"><button disabled={busy} aria-expanded={expanded} aria-current={view === 'library' && category === item.path ? 'page' : undefined} title={item.path} onClick={() => guard(() => {
          setExpandedPath(expanded ? parentOf(item.path) : item.path); clearSelection(); setCategory(item.path); setView('library'); setStep('categories'); setError('');
        })}><svg className="prompt-tree-chevron" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d={expanded ? 'm4 6 4 4 4-4' : 'm6 4 4 4-4 4'} /></svg><svg className="prompt-folder-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z" /></svg><span>{nameOf(item.path)} ({categoryCounts.get(item.path) || 0})</span></button>
        <button className="prompt-category-edit" type="button" aria-label={`修改分类：${item.path}`} title={`修改分类：${item.path}`} disabled={busy} onClick={() => openCategoryEdit({ source: item, name: nameOf(item.path), parent: parentOf(item.path) })}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m16 3 5 5M4 20l5-1L21 7a2 2 0 0 0-5-5L4 14l-1 7Z" /></svg></button></div>
        {expanded && <ul>{categoryTree(item.path)}</ul>}
      </li>;
    })}
    {prompts.filter(item => item.category === parent).map(item => <li key={item.path}><button className="prompt-tree-file" disabled={busy} aria-label={item.title} title={item.path} aria-current={view === 'library' && saved?.path === item.path ? 'page' : undefined} onClick={() => openDocument(item.path, true)}><svg className="prompt-folder-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9Z M14 3v6h6 M8 13h8 M8 17h6" /></svg><span>{item.title}</span><small>{item.local_only ? '隐私' : '公开'}</small></button></li>)}
  </>; }
  const loadError = snapshot.error || (view === 'trash' ? trash.error : query ? results.error : null);
  return <div className="prompt-page" data-prompt-unsaved={dirty || busy}>
    <PageCheckStatus queries={[snapshot, ...(view === 'trash' ? [trash] : query ? [results] : [])]} />
    <PageHeader title="提示词管理" actions={<button className="prompt-trash-toggle" disabled={busy} onClick={() => guard(() => { clearSelection(); setView(view === 'trash' ? 'library' : 'trash'); setStep('categories'); })}>{view !== 'trash' && <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7" /></svg>}{view === 'trash' ? '返回提示词库' : '回收站'}</button>} />
    {loadError && <FloatingMessage tone="error">{loadError.message}<button onClick={() => void refresh()}>重试</button></FloatingMessage>}
    {error && <FloatingMessage tone="error">{error}</FloatingMessage>}
    <div className="prompt-toolbar"><SearchField label="搜索提示词" placeholder="搜索标题或正文…" value={search} disabled={view === 'trash'} onChange={value => { setSearch(value); setStep('categories'); }} /><TabSelect label="搜索范围" selected={scope} disabled={view === 'trash'} onChange={setScope} items={[{ value: 'all', label: '全库搜索' }, { value: 'category', label: '当前分类及子分类' }]} />
      <button disabled={busy || view === 'trash' || categoryMissing} onClick={() => guard(() => { clearSelection(); setDraft({ title: '', body: '', category, local_only: false }); setStep('detail'); setError(''); })}>＋ 新建提示词</button></div>
    <div className="prompt-layout" data-step={step}>
      <aside className="prompt-categories" aria-label="主目录">
        <div className="prompt-panel-heading"><h2><button className="prompt-root-heading" disabled={busy} onClick={() => selectCategory('')}>主目录 ({prompts.length})</button></h2>{view === 'library' && <button disabled={busy || categoryMissing} onClick={() => openCategoryEdit({ source: null, name: '', parent: category })}>新建分类</button>}</div>
        {categoryMissing && view === 'library' && <FloatingMessage>当前分类已被移动或删除。<button onClick={() => selectCategory('')}>返回主目录</button></FloatingMessage>}
        {(snapshot.isPending || (view === 'trash' && trash.isPending) || (view === 'library' && query && results.isPending)) && <p role="status">正在读取…</p>}
        {view === 'trash' ? <section aria-label="回收站列表">
          <h3>回收站 ({trash.data?.length || 0})</h3>
          {trash.data?.map(item => <button className="prompt-list-item" key={item.id} disabled={busy} aria-current={deleted?.id === item.id ? 'page' : undefined} onClick={() => void run(async () => { const doc = await api<Trash>(`/trash/document?id=${item.id}`); clearSelection(); setDeleted(doc); setStep('detail'); })}><strong>{titleOf(item.original)}</strong><small>{parentOf(item.original) || '主目录'}</small><small>删除于 {new Date(item.deleted).toLocaleString('zh-CN')}</small></button>)}
          {trash.data?.length === 0 && <p className="prompt-empty">回收站是空的。</p>}
        </section> : query ? <section aria-label="搜索结果">
          <h3>搜索结果 ({items.length})</h3>
          {items.map(item => <button key={item.path} className="prompt-list-item prompt-title-item" aria-label={item.title} title={item.path} disabled={busy} aria-current={saved?.path === item.path ? 'page' : undefined} onClick={() => openDocument(item.path)}><strong>{item.title}</strong><small>{item.local_only ? '隐私' : '公开'}</small></button>)}
          {!results.isPending && !items.length && <p className="prompt-empty">没有找到匹配的提示词。</p>}
        </section> : <>
          <ul className="prompt-tree">{categoryTree('')}</ul>
          {!snapshot.isPending && categories.length === 0 && !prompts.length && <p className="muted">还没有提示词。可以直接新建提示词，也可以创建自己的分类。</p>}
        </>}
      </aside>
      <section className="prompt-detail" aria-label="提示词详情">
        <button className="prompt-mobile" disabled={busy} onClick={() => guard(() => { clearSelection(); setStep('categories'); })}>‹ {view === 'trash' ? '回收站' : query ? '搜索结果' : '主目录'}</button>
        {draft ? <>
          {changed && <FloatingMessage>这份提示词已在外部修改、移动或删除。当前内容已保留。<button disabled={busy} onClick={() => openDocument(saved!.path)}>重新载入</button></FloatingMessage>}
          <label className="prompt-form-field"><span>标题</span><input aria-label="提示词标题" value={draft.title} disabled={busy} onChange={e => setDraft({ ...draft, title: e.target.value })} placeholder="为提示词起个名字" /></label>
          <div className="prompt-form-field"><span>所在分类</span><TabSelect variant="field" label="提示词所在分类" selected={draft.category} disabled={busy} onChange={category => setDraft({ ...draft, category })} items={[
            { value: '', label: '主目录' }, ...categories.map(item => ({ value: item.path, label: item.path })),
            ...(draft.category && !categories.some(item => item.path === draft.category) ? [{ value: draft.category, label: `${draft.category}（已不存在）` }] : []),
          ]} /></div>
          <div className="prompt-controls">
            <div className="prompt-edit-control"><span>编辑模式</span><Switch label="编辑模式" checked={mode === 'text'} disabled={busy} onChange={checked => setMode(checked ? 'text' : 'preview')} /></div>
            <div className="prompt-edit-control" title="打开后仅本地保存，关闭后随公共仓库分享；点击保存后生效。"><span>隐私</span><Switch label="隐私" checked={draft.local_only} disabled={busy} onChange={checked => setDraft({ ...draft, local_only: checked })} /></div>
          </div>
          {mode === 'text' ? <textarea aria-label="提示词正文" className="prompt-body" value={draft.body} disabled={busy} spellCheck={false} placeholder="输入或粘贴提示词正文…" onChange={e => setDraft({ ...draft, body: e.target.value })} /> : preview.isPending ? <p className="prompt-preview" role="status">正在生成预览…</p> : preview.error ? <div className="prompt-preview"><FloatingMessage tone="error">{preview.error.message}<button onClick={() => void preview.refetch()}>重试预览</button></FloatingMessage></div> : <article className="prompt-preview"><Rich html={preview.data.html} /></article>}
          <div className="prompt-actions"><button className="prompt-primary" disabled={busy || !draft.title.trim() || !dirty} onClick={() => void save()}>{busy ? '处理中…' : '保存'}</button><CopyButton label="复制" text={draft.body} />{saved && <button className="danger-button prompt-delete" disabled={busy} onClick={() => guard(() => { const current = latestSaved.current!; ask('移入回收站', `确定将“${current.title}”移入回收站吗？`, async () => { await api('/document', 'DELETE', { path: current.path, revision: current.revision }); clearSelection(); setConfirm(null); setStep('categories'); notify('已移入回收站'); await refresh(); }); })}>删除</button>}</div>
        </> : deleted ? <>
          <h2>{titleOf(deleted.original)}</h2><small>原位置：{deleted.original} · {deleted.local_only ? '隐私' : '公开'}</small><p className="muted">回收站内容不会自动清空。恢复时保留原来的隐私或公开属性。</p><pre className="prompt-trash-body">{deleted.body}</pre>
          <div className="prompt-actions"><button disabled={busy} onClick={() => { setModalError(''); setRestore({ item: deleted, title: titleOf(deleted.original), category: parentOf(deleted.original) }); }}>恢复提示词</button><CopyButton label="复制" text={deleted.body || ''} /><button className="danger-button prompt-delete" disabled={busy} onClick={() => ask('彻底删除提示词', `“${titleOf(deleted.original)}”将永久删除，无法从回收站恢复。`, async () => { await api('/trash', 'DELETE', { id: deleted.id, revision: deleted.revision }); clearSelection(); setConfirm(null); setStep('categories'); await refresh(); })}>彻底删除</button></div>
        </> : <div className="prompt-empty"><span className="prompt-empty-icon">▤</span><h2>你的提示词资料库</h2><p>选择一份提示词查看和编辑，<br />或新建一份，把好用的写法留下来。</p></div>}
      </section>
    </div>
    {unsavedOpen && <Dialog size="compact" closeDisabled={busy} title="修改尚未保存" close={() => { if (!busy) cancelPending(); }}><p>保存后继续，或放弃这次修改。</p><div className="prompt-actions prompt-actions-end"><button disabled={busy || !draft?.title.trim()} onClick={async () => { if (await save()) proceed(); }}>保存并继续</button><button disabled={busy} onClick={cancelPending}>继续修改</button><button className="danger-button" disabled={busy} onClick={() => { clearSelection(); proceed(); }}>放弃修改</button></div></Dialog>}
    {categoryEdit && <Dialog size="compact" closeDisabled={busy} title={categoryEdit.source ? '修改分类' : '新建分类'} close={() => { if (!busy) setCategoryEdit(null); }}><form className="prompt-form" onSubmit={event => { event.preventDefault(); void run(async () => {
      if (categoryDelete) return;
      const source = categoryEdit.source;
      const result = await api<Category>('/categories', source ? 'PUT' : 'POST', { parent: categoryEdit.parent, name: categoryEdit.name, source: source?.path || '', revision: source?.revision || '' });
      clearSelection(); setCategory(result.path); setView('library'); setStep('categories'); setCategoryEdit(null); await refresh();
    }, true); }}><label>分类名称<input autoFocus aria-label="分类名称" value={categoryEdit.name} disabled={busy || categoryDelete} onChange={e => setCategoryEdit({ ...categoryEdit, name: e.target.value })} /></label><label>上级分类<TabSelect variant="field" label="上级分类" selected={categoryEdit.parent} disabled={busy || categoryDelete} onChange={parent => setCategoryEdit({ ...categoryEdit, parent })} items={categoryOptions(categoryEdit.source?.path)} /></label>{modalError && <FloatingMessage tone="error">{modalError}</FloatingMessage>}{categoryDelete && <p className="prompt-warning">确认删除“{categoryEdit.source!.path}”？分类内有文件或子分类时不会删除。</p>}<div className="prompt-actions">{categoryDelete ? <><button className="danger-button" type="button" disabled={busy} onClick={() => void run(async () => {
      const source = categoryEdit.source!;
      await api('/categories', 'DELETE', { path: source.path, revision: source.revision });
      clearSelection(); setCategory(parentOf(source.path)); setCategoryEdit(null); setCategoryDelete(false); setStep('categories'); await refresh();
    }, true)}>确认删除分类</button><button type="button" disabled={busy} onClick={() => { setCategoryDelete(false); setModalError(''); }}>取消删除</button></> : <><button type="submit" disabled={busy || !categoryEdit.name.trim()}>保存</button>{categoryEdit.source && <button type="button" className="danger-button prompt-category-delete" disabled={busy} onClick={() => { setCategoryDelete(true); setModalError(''); }}>删除分类</button>}</>}</div></form></Dialog>}
    {restore && <Dialog size="compact" closeDisabled={busy} title="恢复提示词" close={() => { if (!busy) setRestore(null); }}><form className="prompt-form" onSubmit={event => { event.preventDefault(); void run(async () => {
      const doc = await api<Document>('/trash/restore', 'POST', { id: restore.item.id, revision: restore.item.revision, title: restore.title, category: restore.category });
      setView('library'); setCategory(doc.category); accept(doc, true); setRestore(null); notify('已恢复'); await refresh();
    }, true); }}><label>标题<input aria-label="恢复标题" value={restore.title} disabled={busy} onChange={e => setRestore({ ...restore, title: e.target.value })} /></label><label>恢复到<TabSelect variant="field" label="恢复到分类" selected={restore.category} disabled={busy} onChange={category => setRestore({ ...restore, category })} items={[...categoryOptions(), ...(restore.category && !categories.some(item => item.path === restore.category) ? [{ value: restore.category, label: `${restore.category}（重建原分类）` }] : [])]} /></label><p>原分类已不存在时，恢复会重新创建该分类。</p>{modalError && <FloatingMessage tone="error">{modalError}</FloatingMessage>}<div className="prompt-actions"><button type="submit" disabled={busy || !restore.title.trim()}>确认恢复</button><button type="button" disabled={busy} onClick={() => setRestore(null)}>取消</button></div></form></Dialog>}
    {confirm && <Dialog size="compact" closeDisabled={busy} title={confirm.title} close={() => { if (!busy) setConfirm(null); }}><p>{confirm.text}</p>{modalError && <FloatingMessage tone="error">{modalError}</FloatingMessage>}<div className="prompt-actions"><button disabled={busy} onClick={() => void run(confirm.action, true)}>确认</button><button disabled={busy} onClick={() => setConfirm(null)}>取消</button></div></Dialog>}
  </div>;
}
