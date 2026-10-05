import { useContext, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useParams, Link } from 'react-router-dom';
import { get, projectUrl, searchTree } from './api';
import type { FileItem, RecordData } from './api';
import { Document, FileTree, Groups, Original, Preview, PreviewContext, Result, Rich } from './components';

export default function Project() {
  const { name = '' } = useParams();
  const [section, setSection] = useState('00-项目定位');
  const [visited, setVisited] = useState(['00-项目定位']);
  const [preview, setPreview] = useState<FileItem | null>(null);
  const status = useQuery({ queryKey: ['status', name], queryFn: () => get<RecordData>(`${projectUrl(name)}/status`), refetchInterval: 5000 });
  const revision = status.data?.revision || 1;
  const overview = useQuery({ queryKey: ['overview', name, revision], queryFn: () => get<RecordData>(`${projectUrl(name)}/overview`), enabled: !!status.data, placeholderData: previous => previous });
  return <PreviewContext.Provider value={setPreview}>
    <div className="breadcrumbs"><Link to="/">工作区</Link><span> / {name}</span></div>
    <div className="page-heading"><div><p className="eyebrow">项目浏览</p><h1>{name}</h1></div><span className="muted">{status.data?.updating ? '正在同步资料…' : `资料读取：${status.data?.updated || '读取中'}`}</span></div>
    <Result loading={status.isPending || overview.isPending} error={status.error || overview.error} />
    {status.data?.error && <p className="error">同步失败，保留上一份可读资料：{status.data.error}</p>}
    {overview.data && <>
      <details className="activity" open><summary>当前阶段与待处理事项</summary><div className="grid">{overview.data.active.map((item: RecordData) => <article key={item.name}><h3>{item.name}</h3><Rich html={item.statusHtml} /><Rich html={item.pendingHtml} /><Rich html={item.nextHtml} /></article>)}</div></details>
      {overview.data.warnings.length > 0 && <details className="notice"><summary>资料提示（{overview.data.warnings.length}）</summary>{overview.data.warnings.map((warning: string) => <p key={warning}>{warning}</p>)}</details>}
      <nav className="section-tabs" aria-label="项目栏目">{overview.data.directories.map((dir: RecordData) => <button key={dir.name} aria-current={section === dir.name ? 'page' : undefined} onClick={() => { setSection(dir.name); setVisited(old => old.includes(dir.name) ? old : [...old, dir.name]); }}>{dir.label}</button>)}</nav>
      {visited.map(label => <SectionPane key={label} project={name} section={label} revision={revision} active={label === section} />)}
    </>}
    {preview && <Preview key={preview.key || preview.url} project={name} item={preview} revision={revision} close={() => setPreview(null)} />}
  </PreviewContext.Provider>;
}
function SectionPane({ project, section, revision, active }: { project: string; section: string; revision: number; active: boolean }) {
  const query = useQuery({ queryKey: ['section', project, section, revision], queryFn: () => get<RecordData>(`${projectUrl(project)}/sections/${encodeURIComponent(section)}`), enabled: active, placeholderData: previous => previous });
  return <section className="panel" hidden={!active}><h2>{section.replace(/^\d+-/, '')}</h2><Result loading={query.isPending} error={query.error} />{query.data && <Section value={query.data} project={project} section={section} revision={revision} />}</section>;
}
function Section({ value, project, section, revision }: { value: RecordData; project: string; section: string; revision: number }) {
  if (value.kind === 'people' || value.kind === 'scenes' || value.kind === 'props') return <Assets value={value} project={project} revision={revision} />;
  if ('exists' in value) return value.exists ? <Document value={value} /> : <><p className="muted">尚无正式文档。</p><Groups groups={value.groups} /></>;
  return <Catalogue value={value} section={section} />;
}
function Catalogue({ value, section }: { value: RecordData; section: string }) {
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [page, setPage] = useState(1);
  const all: FileItem[] = value.children || value.items || value.files || [];
  const categories = Array.from(new Set(all.map(item => item.category).filter(Boolean)));
  const matched = searchTree(all.filter(item => !category || item.category === category), search);
  return <><div className="toolbar"><input aria-label="搜索目录" placeholder="搜索名称、概要" value={search} onChange={event => { setSearch(event.target.value); setPage(1); }} />{categories.length > 0 && <select aria-label="目录分类" value={category} onChange={event => { setCategory(event.target.value); setPage(1); }}><option value="">全部分类</option>{categories.map(item => <option key={item}>{item}</option>)}</select>}</div>
    {!all.length && <p className="muted">暂无资料。</p>}<FileTree key={section} items={matched.slice((page - 1) * 36, page * 36)} />
    <Pagination page={page} total={matched.length} change={setPage} /><Groups groups={value.groups} /></>;
}
export function Pagination({ page, total, change }: { page: number; total: number; change: (n: number) => void }) {
  const last = Math.max(1, Math.ceil(total / 36));
  return total > 36 ? <div className="pagination"><button disabled={page <= 1} onClick={() => change(page - 1)}>上一页</button><span>{page} / {last} · 共{total}项</span><button disabled={page >= last} onClick={() => change(page + 1)}>下一页</button></div> : null;
}
function Assets({ value, project, revision }: { value: RecordData; project: string; revision: number }) {
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState('资料卡');
  const detail = useQuery({ queryKey: ['asset', project, value.kind, selected, revision], queryFn: () => get<RecordData>(`${projectUrl(project)}/assets/${value.kind}/${encodeURIComponent(selected!)}`), enabled: !!selected, placeholderData: (previous, query) => query?.queryKey[3] === selected ? previous : undefined });
  const matched = value.items.filter((item: RecordData) => `${item.id} ${item.name} ${item.role}`.toLowerCase().includes(search.toLowerCase()));
  return <>
    <div hidden={!!selected}><div className="toolbar"><input aria-label="搜索资料" placeholder="搜索编号、名称" value={search} onChange={event => setSearch(event.target.value)} /><span className="muted">共{matched.length}项</span></div>
      <div className="grid">{matched.map((item: RecordData) => <article className="asset-card" key={item.id}>
        <button className="cover" onClick={() => { setSelected(item.id); setTab('资料卡'); }}>{item.cover?.media ? <img loading="lazy" src={item.cover.media.url + `?v=${revision}`} alt={item.name} /> : <span>{item.id}</span>}</button>
        <h3>{item.id} · {item.name}</h3><p>{item.role}</p><Rich html={item.statusHtml} /><p className="muted">正式参考图 {item.formalCount} · 候选 {item.candidateCount}</p>
        <button onClick={() => { setSelected(item.id); setTab('资料卡'); }}>查看详情</button> {item.pendingCount > 0 && <button className="pending" onClick={() => { setSelected(item.id); setTab('候选与审阅'); }}>留存待确认／待审核 {item.pendingCount}</button>}
      </article>)}</div><Groups groups={value.groups} /></div>
    {selected && <><button onClick={() => setSelected(null)}>← 返回列表</button><Result loading={detail.isPending} error={detail.error} />{detail.data && <><h2>{detail.data.id} · {detail.data.name}</h2><nav className="detail-tabs">{['资料卡', '正式参考图', '候选与审阅', '相关记录'].map(label => <button key={label} aria-current={tab === label ? 'page' : undefined} onClick={() => setTab(label)}>{label}</button>)}</nav>
      <div hidden={tab !== '资料卡'}><Document key={detail.data.id} value={detail.data.card} /></div>
      <div hidden={tab !== '正式参考图'}><AssetMedia items={[...detail.data.formal, ...(detail.data.auxiliary || []), ...(detail.data.legacy || [])]} revision={revision} /></div>
      <div hidden={tab !== '候选与审阅'}>{tab === '候选与审阅' && <AssetMedia items={detail.data.candidates} revision={revision} />}</div>
      <div hidden={tab !== '相关记录'}>{detail.data.recordKey && <FileTree items={[{ kind: 'markdown', name: '完整生成记录', key: detail.data.recordKey, url: `${projectUrl(project)}/files/${detail.data.recordKey}` }]} />}<Groups groups={detail.data.groups} /></div>
    </>}</>}
  </>;
}
function AssetMedia({ items, revision }: { items: RecordData[]; revision: number }) {
  const preview = useContext(PreviewContext);
  const grouped: Record<string, RecordData[]> = {};
  for (const item of items) {
    const label = [item.stage, item.type, item.state, item.costume].filter(Boolean).join(' · ') || '参考图';
    (grouped[label] ||= []).push(item);
  }
  return items.length ? <div>{Object.entries(grouped).map(([name, assets]) => <details key={name} open><summary>{name}（{assets.length}）</summary><div className="grid">{assets.map((item, index) => <article key={item.media?.key || item.generation || index}>
    {item.media ? <><button className="cover" onClick={() => preview(item.media)}><img className="reference" loading="lazy" src={item.media.url + `?v=${revision}`} alt={item.media.name} /></button><Original url={item.media.url} label="原图" /></> : <p className="muted">已登记，图片文件缺失。</p>}
    {Object.entries(item).filter(([key, content]) => key.endsWith('Html') && typeof content === 'string' && content).map(([key, content]) => <div key={key}><p className="field-label">{({ statusHtml: '状态', sourceHtml: '来源', fileCheckHtml: '文件核对', visionScopeHtml: '看图授权及范围', visionFindingsHtml: '授权查看的发现', userHtml: '用户决定', agentHtml: '历史初审', technicalHtml: '技术审查', contentHtml: '内容审查', contentFindingsHtml: '审查发现', versionHtml: '采用版本' } as Record<string, string>)[key] || key.replace('Html', '')}</p><Rich html={String(content)} /></div>)}
    {['version', 'scope', 'retentionPurpose', 'applicability', 'pendingLabel', 'userState', 'generation'].map(key => item[key] && <p key={key}>{({ version: '版本', scope: '适用范围', retentionPurpose: '留存用途', applicability: '适用条件', pendingLabel: '留存状态', userState: '用户决定', generation: '生成记录' } as Record<string, string>)[key]}：{item[key]}</p>)}
    <Original url={item.recordUrl} label="生成记录" /> {item.reviews?.map((review: FileItem) => <FileTree key={review.key} items={[{ ...review, kind: 'markdown' }]} />)}
  </article>)}</div></details>)}</div> : <p className="muted">暂无已登记图片。</p>;
}
