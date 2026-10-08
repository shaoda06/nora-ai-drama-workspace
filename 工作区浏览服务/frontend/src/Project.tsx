import { useContext, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { get, projectUrl, searchTree } from './api';
import type { FileItem, RecordData } from './api';
import { Document, FileTree, Groups, Preview, PreviewContext, Result, Rich } from './components';

import { PageHeader } from './components/PageHeader';
import { Breadcrumbs } from './components/Breadcrumbs';
import { TabNav } from './components/TabNav';
import { SearchField } from './components/SearchField';
import { Pagination } from './components/Pagination';
import { FooterSyncContext, HeaderControlsContext } from './components/AppShell';
import { SyncNotification } from './components/SyncNotification';
import { EpisodeProduction } from './components/EpisodeProduction';
import { AssetMediaCard } from './components/AssetMediaCard';
import { useRefreshState } from './refreshPosition';
import { useNotify } from './components/Notifications';

type AssetSelection = { id: string; name: string };
type AssetNavigation = { asset: AssetSelection | null; onAssetChange: (asset: AssetSelection | null) => void };

export default function Project() {
  const controlsRoot = useContext(HeaderControlsContext);
  const syncRoot = useContext(FooterSyncContext);
  const { name = '' } = useParams();
  const [section, setSection] = useRefreshState(`project/${name}/section`, '00-项目定位');
  const [visited, setVisited] = useState([section]);
  const [entries, setEntries] = useState<Record<string, number>>({});
  const [preview, setPreview] = useState<FileItem | null>(null);
  const [episode, setEpisode] = useRefreshState<string | null>(`project/${name}/episode`, null);
  const [asset, setAsset] = useRefreshState<AssetSelection | null>(`project/${name}/asset`, null);
  const currentPath = useRef<HTMLSpanElement>(null);
  const openSection = (value: string) => {
    setEpisode(null);
    setAsset(null);
    setSection(value);
    setVisited(old => old.includes(value) ? old : [...old, value]);
    setEntries(old => ({ ...old, [value]: (old[value] || 0) + 1 }));
    requestAnimationFrame(() => currentPath.current!.scrollIntoView({ block: 'start' }));
  };
  const status = useQuery({ queryKey: ['status', name], queryFn: () =>
    get<RecordData>(`${projectUrl(name)}/status`), refetchInterval: 5000 });
  const retryAt = status.data?.retryAt;
  const syncing = status.data?.updating;
  const { refetch } = status;
  useEffect(() => {
    if (!retryAt || syncing) return;
    const timer = window.setTimeout(() => { void refetch(); }, Math.max(0, retryAt - Date.now()));
    return () => window.clearTimeout(timer);
  }, [name, retryAt, syncing, refetch]);
  const revision = status.data?.revision || 1;
  const production = useQuery<RecordData>({ queryKey: ['section', name, '09-剧集制作', revision], enabled: false, placeholderData: (previous, query) => query?.queryKey[1] === name ? previous : undefined });
  const episodeTitle = production.data?.children.find((item: FileItem) => item.name === episode)?.title || '题名未记录';
  const overview = useQuery({ queryKey: ['overview', name, revision], queryFn: () => get<RecordData>(`${projectUrl(name)}/overview`), enabled: !!status.data, placeholderData: (previous, query) => query?.queryKey[1] === name ? previous : undefined });
  useEffect(() => {
    if (overview.data && !overview.data.directories.some((dir: RecordData) => dir.name === section)) {
      setSection('00-项目定位'); setVisited(['00-项目定位']); setEpisode(null); setAsset(null);
    }
  }, [overview.data, section, setSection, setEpisode, setAsset]);
  return <PreviewContext.Provider value={setPreview}>
    <SyncNotification key={name} error={status.data?.error} errorKind={status.data?.errorKind} retryAt={retryAt} updating={syncing} />
    {syncRoot && createPortal(<>上次同步：{status.data?.updated ? new Date(status.data.updated).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }).replaceAll('/', '-') : '—'}</>, syncRoot)}
    <PageHeader title={overview.data?.positionTitle && overview.data.positionTitle !== '未记录' ? overview.data.positionTitle : name}>
    {overview.data && (
      <div className="activity" role="region" aria-label="当前阶段">
        <div className="activity-heading"><strong>当前阶段</strong>{overview.data.active.length > 0 && <span>（<button className="link" onClick={() => setPreview({ kind: 'markdown', name: '项目进度', key: '项目进度.md', url: `${projectUrl(name)}/files/${encodeURIComponent('项目进度.md')}` })}>查看完整进度</button>）</span>}</div>
        <div className="activity-items">{overview.data.active.length ? overview.data.active.map((item: RecordData) => <div className="activity-item" key={item.name}><strong>{item.name}</strong><button className="activity-state" aria-label={`${item.name}：${item.status}，查看待决事项`} onClick={() => setPreview({ kind: 'markdown', name: `${item.name} · 待决事项与下一步`, doc: { html: item.statusHtml + '<h3>待决事项</h3><p>' + item.pendingHtml + '</p><h3>下一步</h3><p>' + item.nextHtml + '</p>' }, key: `项目进度.md#${item.anchor}`, url: `${projectUrl(name)}/files/${encodeURIComponent('项目进度.md')}#${item.anchor}` })}><Rich html={item.statusHtml} /></button></div>) : <span className="muted">未记录进行中或待确认阶段</span>}</div>
      </div>
    )}
      <Breadcrumbs currentRef={currentPath} items={[{ label: overview.data?.directories.find((dir: RecordData) => dir.name === section)?.label || section.replace(/^\d+-/, ''), href: `#/projects/${encodeURIComponent(name)}`, onClick: () => openSection(section) }, ...(section === '09-剧集制作' && episode ? [{ label: `${episode} · ${episodeTitle}` }] : asset ? [{ label: `${asset.id} · ${asset.name}` }] : [])]} />
    </PageHeader>
    <Result page loading={status.isPending || overview.isPending} error={status.error || overview.error} retry={status.error ? status.refetch : overview.refetch} retrying={status.isFetching || overview.isFetching} />
    {overview.data && <>
      {overview.data.warnings.length > 0 && <details className="notice"><summary>资料提示（{overview.data.warnings.length}）</summary>{overview.data.warnings.map((warning: string) => <p key={warning}>{warning}</p>)}</details>}
      {controlsRoot && createPortal(<TabNav label="项目栏目" groups={[{ label: '相关资料', values: ['03-人物资料', '04-场景资料', '05-道具资料'] }, { label: '参考素材', values: ['07-参考音频', '08-参考视频'] }]} items={overview.data.directories.map((dir: RecordData) => ({ value: dir.name, label: dir.label }))} selected={section} onChange={openSection} />, controlsRoot)}
      {visited.map(label => <SectionPane key={name + '/' + label + '/' + (entries[label] || 0)} project={name} section={label} revision={revision} active={label === section} asset={label === section ? asset : null} onAssetChange={value => { setAsset(value); if (value) requestAnimationFrame(() => { currentPath.current!.scrollIntoView({ block: 'start' }); currentPath.current!.focus({ preventScroll: true }); }); }} episode={episode} onEpisodeChange={value => { setEpisode(value); if (value) requestAnimationFrame(() => { currentPath.current!.scrollIntoView({ block: 'start' }); currentPath.current!.focus({ preventScroll: true }); }); }} />)}
    </>}
    {preview && <Preview key={preview.key || preview.url} project={name} item={preview} revision={revision} close={() => setPreview(null)} />}
  </PreviewContext.Provider>;
}
function SectionPane({ project, section, revision, active, episode, onEpisodeChange, asset, onAssetChange }: { project: string; section: string; revision: number; active: boolean; episode: string | null; onEpisodeChange: (episode: string | null) => void } & AssetNavigation) {
  const query = useQuery({ queryKey: ['section', project, section, revision], queryFn: () => get<RecordData>(`${projectUrl(project)}/sections/${encodeURIComponent(section)}`), enabled: active, placeholderData: previous => previous });
  const statistics = section === '09-剧集制作' && !episode ? query.data?.statistics : undefined;
  return <section className="panel" hidden={!active}>{statistics && <div className="production-statistics" aria-label="剧集制作统计"><span>共 <strong>{statistics.total}</strong> 集</span><span>未开始 <strong>{statistics.notStarted}</strong> 集</span><span>进行中 <strong>{statistics.running}</strong> 集</span><span>已完成 <strong>{statistics.completed}</strong> 集</span></div>}<Result page loading={active && query.isPending} error={query.error} retry={query.refetch} retrying={query.isFetching} />{query.data && (section !== '09-剧集制作' || active) && <Section value={query.data} project={project} section={section} revision={revision} active={active} asset={asset} onAssetChange={onAssetChange} episode={episode} onEpisodeChange={onEpisodeChange} />}</section>;
}
function Section({ value, project, section, revision, active, episode, onEpisodeChange, asset, onAssetChange }: { value: RecordData; project: string; section: string; revision: number; active: boolean; episode: string | null; onEpisodeChange: (episode: string | null) => void } & AssetNavigation) {
  if (section === '09-剧集制作') return <EpisodeProduction project={project} items={value.children} selected={episode} onSelect={onEpisodeChange} revision={revision} />;
  if (value.kind === 'people' || value.kind === 'scenes' || value.kind === 'props') return <Assets value={value} project={project} revision={revision} active={active} asset={asset} onAssetChange={onAssetChange} />;
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
function Assets({ value, project, revision, active, asset, onAssetChange }: { value: RecordData; project: string; revision: number; active: boolean } & AssetNavigation) {
  const [search, setSearch] = useState('');
  const selected = asset?.id || null;
  const [tab, setTab] = useState('资料卡');
  const audio = useRef<HTMLAudioElement>(null);
  const voiceId = useRef<string | null>(null);
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [voiceProgress, setVoiceProgress] = useState(0);
  const notify = useNotify();
  useEffect(() => {
    if (!active || selected) audio.current?.pause();
    return () => { audio.current?.pause(); };
  }, [active, selected]);
  const playVoice = (item: RecordData) => {
    const player = audio.current!;
    if (voiceId.current === item.id && !player.paused) { player.pause(); return; }
    player.pause();
    if (voiceId.current !== item.id || player.ended) {
      voiceId.current = item.id;
      setVoiceProgress(0);
      player.src = item.voice.url + `?v=${revision}`;
    }
    void player.play().catch(error => {
      if (error.name !== 'AbortError') notify('音色播放失败，请稍后重试。', 'error');
    });
  };
  const detail = useQuery({ queryKey: ['asset', project, value.kind, selected, revision], queryFn: () => get<RecordData>(`${projectUrl(project)}/assets/${value.kind}/${encodeURIComponent(selected!)}`), enabled: !!selected, placeholderData: (previous, query) => query?.queryKey[3] === selected ? previous : undefined });
  const matched = value.items.filter((item: RecordData) => `${item.id} ${item.name} ${item.role}`.toLowerCase().includes(search.toLowerCase()));
  return <>
    {value.kind === 'people' && <audio ref={audio} preload="none" onPlay={() => setPlayingId(voiceId.current)} onPause={() => setPlayingId(null)} onTimeUpdate={event => { const player = event.currentTarget; if (player.duration > 0) setVoiceProgress(player.currentTime / player.duration); }} onEnded={() => { setPlayingId(null); setVoiceProgress(0); }} />}
    <div hidden={!!selected}><div className="toolbar"><SearchField label="搜索资料" placeholder="搜索编号、名称" value={search} onChange={setSearch} /><span className="muted">共{matched.length}项</span></div>
      <div className="grid asset-list-grid">{matched.map((item: RecordData) => <article className="asset-card" key={item.id}>
        <button className={value.kind === 'people' && item.cover?.media ? 'cover character-cover-image' : 'cover'} onClick={() => { onAssetChange({ id: item.id, name: item.name }); setTab('资料卡'); }}>{item.cover?.media ? <img loading="lazy" src={item.cover.media.url + `?v=${revision}`} alt={item.name} /> : <span>{item.id}</span>}</button>
        <div className="asset-card-heading"><h3 title={`${item.id} · ${item.name}`}>{item.id} · {item.name}</h3>{value.kind === 'people' && <button className="voice-preview" disabled={!item.voice} aria-label={!item.voice ? `${item.name}暂无音色` : `${playingId === item.id ? '暂停' : '播放'}${item.name}音色`} title={!item.voice ? '暂无音色' : playingId === item.id ? '暂停音色' : '试听音色'} aria-pressed={playingId === item.id} onClick={() => playVoice(item)}>{playingId === item.id ? 'Ⅱ' : '▶'}<svg className="voice-progress" viewBox="0 0 28 28" aria-hidden="true"><rect x="1" y="1" width="26" height="26" rx="6" pathLength="100" strokeDasharray="100" strokeDashoffset={100 * (1 - (voiceId.current === item.id ? voiceProgress : 0))} /></svg></button>}</div>
        <p className="asset-card-role" title={item.role}>{item.role}</p>
        <div className="asset-card-footer"><div className="asset-card-status"><span>资料卡状态：</span><Rich html={item.statusHtml} /></div><p className="muted">正式参考图 {item.formalCount} · 候选 {item.candidateCount}</p>
        <button onClick={() => { onAssetChange({ id: item.id, name: item.name }); setTab('资料卡'); }}>查看详情</button></div> {item.pendingCount > 0 && <button className="pending" onClick={() => { onAssetChange({ id: item.id, name: item.name }); setTab('候选与审阅'); }}>留存待确认／待审核 {item.pendingCount}</button>}
      </article>)}</div><Groups groups={value.groups} /></div>
    {selected && <><button onClick={() => onAssetChange(null)}>← 返回列表</button><Result loading={detail.isPending} error={detail.error} retry={detail.refetch} retrying={detail.isFetching} />{detail.data && <><h2>{detail.data.id} · {detail.data.name}</h2><TabNav label="资产详情" items={['资料卡', '正式参考图', '候选与审阅', '相关文件'].map(label => ({ value: label, label }))} selected={tab} onChange={setTab} />
      <div hidden={tab !== '资料卡'}><Document key={detail.data.id} value={detail.data.card} /></div>
      <div hidden={tab !== '正式参考图'}><AssetMedia items={[...detail.data.formal, ...(detail.data.auxiliary || []), ...(detail.data.legacy || [])]} revision={revision} formal wide={value.kind !== 'people'} /></div>
      <div hidden={tab !== '候选与审阅'}>{tab === '候选与审阅' && <CandidateMedia key={selected} items={detail.data.candidates} revision={revision} wide={value.kind !== 'people'} />}</div>
      <div hidden={tab !== '相关文件'}>{detail.data.recordKey && !detail.data.groups.some((group: RecordData) => group.files.some((file: FileItem) => file.key === detail.data.recordKey)) && <FileTree items={[{ kind: 'markdown', name: '完整生成记录', key: detail.data.recordKey, url: `${projectUrl(project)}/files/${detail.data.recordKey}` }]} />}<FileTree items={detail.data.groups.map((group: RecordData) => ({ kind: 'group', ...group }))} /></div>
    </>}</>}
  </>;
}
function CandidateMedia({ items, revision, wide }: { items: RecordData[]; revision: number; wide: boolean }) {
  const grouped = new Map<string, RecordData[]>();
  for (const item of items) {
    const type = item.type === '人物多视角参考图（人物本体六视图）' ? '人物多视角参考图' : item.type || '未填写图片类型';
    if (!grouped.has(type)) grouped.set(type, []);
    grouped.get(type)!.push(item);
  }
  const order = ['人物上半身正面肖像图', '人物多视角参考图', '服装参考图', '角色多视角参考图'];
  const types = [...order.filter(type => grouped.has(type)), ...[...grouped.keys()].filter(type => !order.includes(type))];
  return items.length ? <div className="asset-candidate-types">{types.map(type => <CandidateTypeGroup key={type} type={type} items={[...grouped.get(type)!].reverse()} revision={revision} wide={wide} />)}</div> : <p className="muted">暂无已登记图片。</p>;
}
function CandidateTypeGroup({ type, items, revision, wide }: { type: string; items: RecordData[]; revision: number; wide: boolean }) {
  const [open, setOpen] = useState(false);
  return <details className="asset-candidate-type" name="asset-candidate-type" open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>{type}<span className="muted">（{items.length}张）</span></summary>
    {open && <AssetMedia items={items} revision={revision} wide={wide} />}
  </details>;
}
function AssetMedia({ items, revision, formal = false, wide = false }: { items: RecordData[]; revision: number; formal?: boolean; wide?: boolean }) {
  return items.length ? <div className={`asset-media-grid${wide ? ' asset-media-grid-wide' : ''}`}>{items.map(item => <AssetMediaCard key={item.media?.key || item.recordUrl} title={[item.stage, item.type, item.state, item.costume].filter(Boolean).join(' · ') || '参考图'} item={item} revision={revision} formal={formal} />)}</div> : <p className="muted">暂无已登记图片。</p>;
}
