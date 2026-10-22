import { FloatingMessage } from './components/Notifications';
import { PageCheckStatus } from './components/PageCheckStatus';
import { TabSelect } from './components/TabSelect';
import { useContext, useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { get, styleUrl } from './api';
import type { RecordData } from './api';
import { Dialog, Original, Result } from './components';
import { Pagination } from './components/Pagination';
import { PageHeader } from './components/PageHeader';
import { SearchField } from './components/SearchField';
import { CopyButton } from './components/CopyButton';
import { HeaderControlsContext } from './components/AppShell';

export default function Krea() {
  const controlsRoot = useContext(HeaderControlsContext);
  const [search, setSearch] = useState('');
  const [library, setLibrary] = useState('');
  const [category, setCategory] = useState('');
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const [manage, setManage] = useState(false);
  const state = useQuery({ queryKey: ['krea-state'], queryFn: () => get<RecordData>('/api/krea2/state'), refetchInterval: 5000 });
  const version = JSON.stringify(state.data?.sources && Object.fromEntries(Object.entries(state.data.sources).map(([key, value]) => [key, (value as RecordData).local])));
  const catalogue = useQuery({ queryKey: ['krea', search, library, category, page, version], queryFn: () => get<RecordData>(`/api/krea2/catalog?${new URLSearchParams({ q: search, library, category, page: String(page) })}`), placeholderData: previous => previous });
  return <>
    <PageCheckStatus queries={[state, catalogue]} />
    <PageHeader eyebrow="跨项目视觉参考" eyebrowInline title="Krea2 风格库" description="浏览预览、查看提示词，保留来源与版本。" actions={<button onClick={() => setManage(true)}>资源与更新管理</button>} />
    {controlsRoot && createPortal(<div className="toolbar"><SearchField label="搜索风格" placeholder="搜索风格名称、分类" value={search} onChange={value => { setSearch(value); setPage(1); }} />
      <TabSelect label="资源库" selected={library} onChange={value => { setLibrary(value); setCategory(''); setPage(1); }} items={[{ value: '', label: '全部资源库' }, { value: 'krea2_styles', label: '风格库' }, { value: 'Krea2_moodboard', label: '灵感库' }]} />
      <TabSelect label="风格分类" selected={category} onChange={value => { setCategory(value); setPage(1); }} items={[{ value: '', label: '全部分类' }, ...(catalogue.data?.categories || []).map((value: string) => ({ value, label: value }))]} /><span className="muted">{catalogue.data?.total ?? '…'} 个风格</span>
    </div>, controlsRoot)}<Result page loading={catalogue.isPending} error={catalogue.error} retry={catalogue.refetch} retrying={catalogue.isFetching} />
    <div className="style-grid">{catalogue.data?.items.map((item: RecordData) => <button className="style-card" key={item.id} onClick={() => setSelected(item.id)}>{item.image ? <img loading="lazy" src={styleUrl(item.image)} alt={item.name_cn || item.name} /> : <div className="cover">图片缺失</div>}<span><strong>{item.name_cn || item.name}</strong><small>{item.name}</small><small>{item.category_name}</small></span></button>)}</div>
    <Pagination page={page} total={catalogue.data?.total || 0} change={setPage} />
    {selected && <Style identity={selected} version={version} close={() => setSelected(null)} />}
    {manage && <UpdateManagement state={state.data} error={state.error} retry={state.refetch} retrying={state.isFetching} close={() => setManage(false)} />}
  </>;
}
function Style({ identity, version, close }: { identity: string; version: string; close: () => void }) {
  const detail = useQuery({ queryKey: ['style', identity, version], queryFn: () => get<RecordData>(`/api/krea2/styles/${encodeURIComponent(identity)}`) });
  const item = detail.data;
  return <Dialog title={item?.name_cn || '风格详情'} close={close}><Result loading={detail.isPending} error={detail.error} retry={detail.refetch} retrying={detail.isFetching} />{item && <>
    <div className="style-detail">{item.image && <img className="preview-image" src={styleUrl(item.image)} alt={item.name} />}<div><h3>{item.name}</h3><p>{item.category_name}</p><p>来源：<Original url={item.source} label={item.library === 'krea2_styles' ? '风格库（Clio）' : '灵感库（Ray）'} /></p><p className="muted">版本：{item.source_revision}</p>
      <CopyButton label="复制发给 AI" text={`我选择了 Krea2 风格“${item.name_cn || item.name}”（${item.name}）。请读取工作区目录：工作区浏览服务/Krea2风格库/Krea2_风格资源/${item.folder}，查看预览图与正负面提示词，再帮我分析和应用。`} />
    </div></div><h3>正面提示词</h3><pre>{item.prompt}</pre><CopyButton label="复制正面提示词" text={item.prompt} /> <Original url={styleUrl(item.folder + '/positive.txt')} label="下载 TXT" />
    <h3>负面提示词</h3><pre>{item.negative_prompt || '原资源未提供负面提示词。'}</pre>{item.negative_prompt && <CopyButton label="复制负面提示词" text={item.negative_prompt} />} <Original url={styleUrl(item.folder + '/negative.txt')} label="下载 TXT" />
  </>}</Dialog>;
}
function UpdateManagement({ state, error, retry, retrying, close }: { state?: RecordData; error: Error | null; retry: () => unknown; retrying: boolean; close: () => void }) {
  const client = useQueryClient();
  const [actionError, setActionError] = useState('');
  const run = async (source: string, action: string) => {
    setActionError('');
    try {
      const response = await fetch('/api/krea2/action', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Krea-Token': state!.token }, body: JSON.stringify({ source, action }) });
      if (!response.ok) throw new Error(await response.text());
      await client.invalidateQueries({ queryKey: ['krea-state'] });
    } catch (error) { setActionError(String(error)); }
  };
  return <Dialog title="资源与更新管理" close={close}><Result loading={!state} error={error} retry={retry} retrying={retrying} />
    {state && <>{!state.canManage && <p className="notice">更新管理仅支持本机或局域网地址，请通过对应地址打开。</p>}
      {actionError && <FloatingMessage tone="error">{actionError}</FloatingMessage>}{Object.entries(state.sources).map(([source, raw]) => {
        const data = raw as RecordData;
        const disabled = !state.canManage || state.job.running;
        return <article key={source}><h3>{source === 'clio' ? '风格库（Clio）' : '灵感库（Ray）'}</h3><p>本地 {data.count} 个风格 · {data.local?.label || '版本未记录'}</p>{data.local?.date && <p className="muted">来源日期：{data.local.date}</p>}<p role="status">{data.status.message}</p>{data.status.error && <FloatingMessage tone="error">{source === 'clio' ? '风格库（Clio）' : '灵感库（Ray）'}：{data.status.error}</FloatingMessage>}
          {data.status.download && <p>已下载 {(data.status.download.received / 1_000_000).toFixed(1)} MB{data.status.download.total ? ` / ${(data.status.download.total / 1_000_000).toFixed(1)} MB` : ''}</p>}
          {data.remote && <details><summary>上游版本</summary><p>{data.remote.label}</p><p>{data.remote.date}</p><p>{data.remote.note}</p><Original url={data.remote.url} label="发布页面" /></details>}
          <div className="toolbar"><button disabled={disabled} onClick={() => run(source, 'check')}>检查更新</button><button disabled={disabled} onClick={() => run(source, 'prepare')}>下载并准备更新</button><button disabled={disabled || !data.restore} onClick={() => run(source, 'restore')}>恢复上一版</button></div>
          {data.plan?.changes && <div className="notice"><h4>待应用更新：{data.plan.count} 个风格</h4>{Object.entries(data.plan.changes).map(([key, items]) => <details key={key}><summary>{({ added: '新增', removed: '移除', prompts: '提示词变化', images: '图片变化', metadata: '信息变化' } as Record<string, string>)[key]}（{(items as string[]).length}）</summary><ul>{(items as string[]).map(name => <li key={name}>{name}</li>)}</ul></details>)}<button disabled={disabled} onClick={() => run(source, 'apply')}>应用这份更新</button> <button disabled={disabled} onClick={() => run(source, 'discard')}>放弃准备</button></div>}
        </article>;
      })}</>}
  </Dialog>;
}
