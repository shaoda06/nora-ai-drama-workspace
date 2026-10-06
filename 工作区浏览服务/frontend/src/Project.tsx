import { useContext, useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { get, projectUrl, searchTree } from './api';
import type { FileItem, RecordData } from './api';
import { Document, FileTree, Groups, Original, Preview, PreviewContext, Result, Rich } from './components';

import { PageHeader } from './components/PageHeader';
import { Breadcrumbs } from './components/Breadcrumbs';
import { TabNav } from './components/TabNav';
import { SearchField } from './components/SearchField';
import { Pagination } from './components/Pagination';
import { HeaderControlsContext } from './components/AppShell';
import { useNotify } from './components/Notifications';
import { EpisodeProduction } from './components/EpisodeProduction';

export default function Project() {
  const notify = useNotify();
  const controlsRoot = useContext(HeaderControlsContext);
  const { name = '' } = useParams();
  const [section, setSection] = useState('00-项目定位');
  const [visited, setVisited] = useState(['00-项目定位']);
  const [preview, setPreview] = useState<FileItem | null>(null);
  const [episode, setEpisode] = useState<string | null>(null);
  const status = useQuery({ queryKey: ['status', name], queryFn: async () => {
    const value = await get<RecordData>(`${projectUrl(name)}/status`);
    if (value.updating) notify('正在同步资料…');
    if (value.error) notify('资料同步未完成，当前显示上一次读取的内容。', 'error');
    return value;
  }, refetchInterval: 5000 });
  const revision = status.data?.revision || 1;
  const overview = useQuery({ queryKey: ['overview', name, revision], queryFn: () => get<RecordData>(`${projectUrl(name)}/overview`), enabled: !!status.data, placeholderData: (previous, query) => query?.queryKey[1] === name ? previous : undefined });
  return <PreviewContext.Provider value={setPreview}>
    {overview.data && (
      <div className="activity" role="region" aria-label="当前阶段">
        <div className="activity-heading"><strong>当前阶段</strong>{overview.data.active.length > 0 && <span>（<button className="link" onClick={() => setPreview({ kind: 'markdown', name: '项目进度', key: '项目进度.md', url: `${projectUrl(name)}/files/${encodeURIComponent('项目进度.md')}` })}>查看完整进度</button>）</span>}</div>
        <div className="activity-items">{overview.data.active.length ? overview.data.active.map((item: RecordData) => <div className="activity-item" key={item.name}><strong>{item.name}</strong><button className="activity-state" aria-label={`${item.name}：${item.status}，查看待决事项`} onClick={() => setPreview({ kind: 'markdown', name: `${item.name} · 待决事项与下一步`, doc: { html: item.statusHtml + '<h3>待决事项</h3><p>' + item.pendingHtml + '</p><h3>下一步</h3><p>' + item.nextHtml + '</p>' }, key: `项目进度.md#${item.anchor}`, url: `${projectUrl(name)}/files/${encodeURIComponent('项目进度.md')}#${item.anchor}` })}><Rich html={item.statusHtml} /></button></div>) : <span className="muted">未记录进行中或待确认阶段</span>}</div>
      </div>
    )}
    <PageHeader title={overview.data?.positionTitle && overview.data.positionTitle !== '未记录' ? overview.data.positionTitle : name}>
      <div className="muted">上次同步：{status.data?.updated ? new Date(status.data.updated).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).replaceAll('/', '-') : '—'}</div>
      <Breadcrumbs items={[name, overview.data?.directories.find((dir: RecordData) => dir.name === section)?.label || section.replace(/^\d+-/, ''), ...(section === '09-剧集制作' && episode ? [episode] : [])]} />
    </PageHeader>
    <Result page loading={status.isPending || overview.isPending} error={status.error || overview.error} />
    {overview.data && <>
      {overview.data.warnings.length > 0 && <details className="notice"><summary>资料提示（{overview.data.warnings.length}）</summary>{overview.data.warnings.map((warning: string) => <p key={warning}>{warning}</p>)}</details>}
      {controlsRoot && createPortal(<TabNav label="项目栏目" groups={[{ label: '相关资料', values: ['03-人物资料', '04-场景资料', '05-道具资料'] }, { label: '参考素材', values: ['07-参考音频', '08-参考视频'] }]} items={overview.data.directories.map((dir: RecordData) => ({ value: dir.name, label: dir.label }))} selected={section} onChange={value => { setSection(value); setVisited(old => old.includes(value) ? old : [...old, value]); }} />, controlsRoot)}
      {visited.map(label => <SectionPane key={name + '/' + label} project={name} section={label} revision={revision} active={label === section} episode={episode} onEpisodeChange={setEpisode} />)}
    </>}
    {preview && <Preview key={preview.key || preview.url} project={name} item={preview} revision={revision} close={() => setPreview(null)} />}
  </PreviewContext.Provider>;
}
function SectionPane({ project, section, revision, active, episode, onEpisodeChange }: { project: string; section: string; revision: number; active: boolean; episode: string | null; onEpisodeChange: (episode: string | null) => void }) {
  const query = useQuery({ queryKey: ['section', project, section, revision], queryFn: () => get<RecordData>(`${projectUrl(project)}/sections/${encodeURIComponent(section)}`), enabled: active, placeholderData: previous => previous });
  const title = section === '00-项目定位' ? '项目定位' : query.data?.title && query.data.title !== '未记录' ? query.data.title : section.replace(/^\d+-/, '');
  const statistics = section === '09-剧集制作' ? query.data?.statistics : undefined;
  return <section className="panel" hidden={!active}><div className={statistics ? 'production-heading' : undefined}><h2>{title}</h2>{statistics && <div className="production-statistics" aria-label="剧集制作统计"><span>共 <strong>{statistics.total}</strong> 集</span><span>已完成 <strong>{statistics.completed}</strong> 集</span><span>未完成 <strong>{statistics.remaining}</strong> 集</span><span>进行中 <strong>{statistics.running}</strong> 集</span></div>}</div><Result page loading={active && query.isPending} error={query.error} />{query.data && <Section value={query.data} project={project} section={section} revision={revision} episode={episode} onEpisodeChange={onEpisodeChange} />}</section>;
}
function Section({ value, project, section, revision, episode, onEpisodeChange }: { value: RecordData; project: string; section: string; revision: number; episode: string | null; onEpisodeChange: (episode: string | null) => void }) {
  if (section === '09-剧集制作') return <EpisodeProduction items={value.children} selected={episode} onSelect={onEpisodeChange} />;
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
  return <>{value.note && <p className="muted">{value.note}</p>}<div className="toolbar"><SearchField label="搜索目录" placeholder="搜索名称、概要" value={search} onChange={value => { setSearch(value); setPage(1); }} />{categories.length > 0 && <select aria-label="目录分类" value={category} onChange={event => { setCategory(event.target.value); setPage(1); }}><option value="">全部分类</option>{categories.map(item => <option key={item}>{item}</option>)}</select>}</div>
    {!all.length && <p className="muted">暂无资料。</p>}<FileTree key={section} items={matched.slice((page - 1) * 36, page * 36)} />
    <Pagination page={page} total={matched.length} change={setPage} /><Groups groups={value.groups} /></>;
}
function Assets({ value, project, revision }: { value: RecordData; project: string; revision: number }) {
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState('资料卡');
  const detail = useQuery({ queryKey: ['asset', project, value.kind, selected, revision], queryFn: () => get<RecordData>(`${projectUrl(project)}/assets/${value.kind}/${encodeURIComponent(selected!)}`), enabled: !!selected, placeholderData: (previous, query) => query?.queryKey[3] === selected ? previous : undefined });
  const matched = value.items.filter((item: RecordData) => `${item.id} ${item.name} ${item.role}`.toLowerCase().includes(search.toLowerCase()));
  return <>
    <div hidden={!!selected}><div className="toolbar"><SearchField label="搜索资料" placeholder="搜索编号、名称" value={search} onChange={setSearch} /><span className="muted">共{matched.length}项</span></div>
      <div className="grid">{matched.map((item: RecordData) => <article className="asset-card" key={item.id}>
        <button className="cover" onClick={() => { setSelected(item.id); setTab('资料卡'); }}>{item.cover?.media ? <img loading="lazy" src={item.cover.media.url + `?v=${revision}`} alt={item.name} /> : <span>{item.id}</span>}</button>
        <h3>{item.id} · {item.name}</h3><p>{item.role}</p><Rich html={item.statusHtml} /><p className="muted">正式参考图 {item.formalCount} · 候选 {item.candidateCount}</p>
        <button onClick={() => { setSelected(item.id); setTab('资料卡'); }}>查看详情</button> {item.pendingCount > 0 && <button className="pending" onClick={() => { setSelected(item.id); setTab('候选与审阅'); }}>留存待确认／待审核 {item.pendingCount}</button>}
      </article>)}</div><Groups groups={value.groups} /></div>
    {selected && <><button onClick={() => setSelected(null)}>← 返回列表</button><Result loading={detail.isPending} error={detail.error} />{detail.data && <><h2>{detail.data.id} · {detail.data.name}</h2><TabNav label="资产详情" items={['资料卡', '正式参考图', '候选与审阅', '相关记录'].map(label => ({ value: label, label }))} selected={tab} onChange={setTab} />
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
