import { PageCheckStatus } from './components/PageCheckStatus';
import { TabSelect } from './components/TabSelect';
import { PointerTooltip } from './components/PointerTooltip';
import { useContext, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { get, projectUrl, searchTree } from './api';
import type { FileItem, RecordData } from './api';
import { Document, FileTree, Groups, Preview, PreviewContext, Result, Rich } from './components';

import { PageHeader } from './components/PageHeader';
import { Breadcrumbs, BreadcrumbActionsContext, BreadcrumbSelectorContext } from './components/Breadcrumbs';
import { TabNav } from './components/TabNav';
import { SearchField } from './components/SearchField';
import { Pagination } from './components/Pagination';
import { HeaderControlsContext } from './components/AppShell';
import { SyncNotification } from './components/SyncNotification';
import { EpisodeProduction } from './components/EpisodeProduction';
import { EpisodeOutlines } from './components/EpisodeOutlines';
import { AssetMedia } from './components/AssetMedia';
import { AssetCandidateMedia } from './components/AssetCandidateMedia';
import { PersonImages, personImageCategory, personImageTabs } from './components/PersonImages';
import { useRefreshState } from './refreshPosition';
import { AudioPreviewButton, useAudioPreview } from './components/AudioPreviewButton';
import { ReferenceLibrary } from './components/ReferenceLibrary';
import { CoverLibrary } from './components/CoverLibrary';
import { AccountLibrary } from './components/AccountLibrary';

type AssetSelection = { id: string; name: string };
type AssetNavigation = { asset: AssetSelection | null; onAssetChange: (asset: AssetSelection | null) => void };

export default function Project() {
  const controlsRoot = useContext(HeaderControlsContext);
  const { name = '' } = useParams();
  const [section, setSection] = useRefreshState(`project/${name}/section`, '00-项目定位');
  const [visited, setVisited] = useState([section]);
  const [entries, setEntries] = useState<Record<string, number>>({});
  const [preview, setPreview] = useState<FileItem | null>(null);
  const [episode, setEpisode] = useRefreshState<string | null>(`project/${name}/episode`, null);
  const [asset, setAsset] = useRefreshState<AssetSelection | null>(`project/${name}/asset`, null);
  const currentPath = useRef<HTMLSpanElement>(null);
  const [breadcrumbActions, setBreadcrumbActions] = useState<HTMLDivElement | null>(null);
  const [breadcrumbSelector, setBreadcrumbSelector] = useState<HTMLSpanElement | null>(null);
  const openSection = (value: string) => {
    setEpisode(null);
    setAsset(null);
    setSection(value);
    setVisited(old => old.includes(value) ? old : [...old, value]);
    setEntries(old => ({ ...old, [value]: (old[value] || 0) + 1 }));
    requestAnimationFrame(() => currentPath.current!.scrollIntoView({ block: 'start' }));
  };
  const status = useQuery({ queryKey: ['status', name], queryFn: () =>
    get<RecordData>(`${projectUrl(name)}/status`), refetchInterval: query => query.state.data?.checking ? 200 : 5000 });
  const retryAt = status.data?.retryAt;
  const syncing = status.data?.updating;
  const { refetch } = status;
  useEffect(() => {
    if (!retryAt || syncing) return;
    const timer = window.setTimeout(() => { void refetch(); }, Math.max(0, retryAt - Date.now()));
    return () => window.clearTimeout(timer);
  }, [name, retryAt, syncing, refetch]);
  const revision = status.data?.revision || 1;
  const production = useQuery<RecordData>({ queryKey: ['section', name, section, revision], enabled: false, placeholderData: (previous, query) => query?.queryKey[1] === name ? previous : undefined });
  const episodeItem = production.data?.children?.find((item: FileItem) => item.name === episode);
  const episodeTitle = (episodeItem?.title || (episode === '片头' || episode === '片尾' ? '全剧通用' : '题名未记录')) + (episodeItem?.titleStatus ? `（${episodeItem.titleStatus === '工作集名' ? '工作集名，未最终定名' : episodeItem.titleStatus}）` : '');
  const overview = useQuery({ queryKey: ['overview', name, revision], queryFn: () => get<RecordData>(`${projectUrl(name)}/overview`), enabled: !!status.data, placeholderData: (previous, query) => query?.queryKey[1] === name ? previous : undefined });
  const warnings = [...new Set<string>([...(overview.data?.warnings || []), ...(production.data?.warnings || [])])];
  useEffect(() => {
    if (overview.data && !overview.data.directories.some((dir: RecordData) => dir.name === section)) {
      setSection('00-项目定位'); setVisited(['00-项目定位']); setEpisode(null); setAsset(null);
    }
  }, [overview.data, section, setSection, setEpisode, setAsset]);
  return <BreadcrumbSelectorContext.Provider value={breadcrumbSelector}><BreadcrumbActionsContext.Provider value={breadcrumbActions}><PreviewContext.Provider value={setPreview}>
    <SyncNotification key={name} error={status.data?.error} errorKind={status.data?.errorKind} retryAt={retryAt} updating={syncing} />
    <PageCheckStatus queries={[status, overview]} />
    <PageHeader stacked title={overview.data?.positionTitle && overview.data.positionTitle !== '未记录' ? overview.data.positionTitle : name}>
    {overview.data && (
      <div className="activity" role="region" aria-label="当前阶段">
        <div className="activity-heading"><strong>当前阶段</strong>{overview.data.active.length > 0 && <span>（<button className="link" onClick={() => setPreview({ kind: 'markdown', name: '项目进度', key: '项目进度.md', url: `${projectUrl(name)}/files/${encodeURIComponent('项目进度.md')}` })}>查看完整进度</button>）</span>}</div>
        <div className="activity-items">{overview.data.active.length ? overview.data.active.map((item: RecordData) => <div className="activity-item" key={item.name}><strong>{item.name}</strong><button className="activity-state" aria-label={`${item.name}：${item.status}，查看待决事项`} onClick={() => setPreview({ kind: 'progress', name: `${item.name} · 待决事项与下一步`, doc: { statusHtml: item.statusHtml, html: '<h3>待决事项</h3>' + item.pendingHtml + '<h3>下一步</h3>' + item.nextHtml }, key: `项目进度.md#${item.anchor}`, url: `${projectUrl(name)}/files/${encodeURIComponent('项目进度.md')}#${item.anchor}` })}><Rich html={item.statusHtml} /></button></div>) : <span className="muted">未记录进行中或待确认阶段</span>}</div>
      </div>
    )}
      <Breadcrumbs currentRef={currentPath} actionsRef={setBreadcrumbActions} selectorRef={section === '09-剧集制作' && episode ? setBreadcrumbSelector : undefined} items={[{ label: overview.data?.directories.find((dir: RecordData) => dir.name === section)?.label || section.replace(/^\d+-/, ''), href: `#/projects/${encodeURIComponent(name)}`, onClick: () => openSection(section) }, ...(section === '09-剧集制作' && episode ? [{ label: `${episode} · ${episodeTitle}` }] : asset ? [{ label: `${asset.id} · ${asset.name}` }] : [])]} />
    </PageHeader>
    <Result page loading={status.isPending || overview.isPending} error={status.error || overview.error} retry={status.error ? status.refetch : overview.refetch} retrying={status.isFetching || overview.isFetching} />
    {overview.data && <>
      {warnings.length > 0 && <details className="notice"><summary>资料提示（{warnings.length}）</summary>{warnings.map((warning: string) => <p key={warning}>{warning}</p>)}</details>}
      {controlsRoot && createPortal(<TabNav wide label="项目栏目" groups={[{ label: '相关资料', values: ['03-人物资料', '04-场景资料', '05-道具资料', '10-封面资料', '11-社交媒体资料'] }, { label: '参考素材', values: ['07-参考音频', '08-参考视频'] }]} items={[...overview.data.directories].sort((a: RecordData, b: RecordData) => Number(['07-参考音频', '08-参考视频'].includes(a.name)) - Number(['07-参考音频', '08-参考视频'].includes(b.name))).map((dir: RecordData) => ({ value: dir.name, label: dir.label }))} selected={section} onChange={openSection} />, controlsRoot)}
      {visited.filter(label => overview.data.directories.some((dir: RecordData) => dir.name === label)).map(label => <SectionPane key={name + '/' + label + '/' + (entries[label] || 0)} project={name} section={label} revision={revision} active={label === section} asset={label === section ? asset : null} onAssetChange={value => { setAsset(value); if (value) requestAnimationFrame(() => { currentPath.current!.scrollIntoView({ block: 'start' }); currentPath.current!.focus({ preventScroll: true }); }); }} episode={episode} onEpisodeChange={value => { setEpisode(value); if (value) requestAnimationFrame(() => { currentPath.current!.scrollIntoView({ block: 'start' }); currentPath.current!.focus({ preventScroll: true }); }); }} />)}
    </>}
    {preview && <Preview key={preview.key || preview.url} project={name} item={preview} revision={revision} close={() => setPreview(null)} />}
  </PreviewContext.Provider></BreadcrumbActionsContext.Provider></BreadcrumbSelectorContext.Provider>;
}
function SectionPane({ project, section, revision, active, episode, onEpisodeChange, asset, onAssetChange }: { project: string; section: string; revision: number; active: boolean; episode: string | null; onEpisodeChange: (episode: string | null) => void } & AssetNavigation) {
  const query = useQuery({ queryKey: ['section', project, section, revision], queryFn: () => get<RecordData>(`${projectUrl(project)}/sections/${encodeURIComponent(section)}`), enabled: active, placeholderData: previous => previous });
  return <section className="panel" hidden={!active}><Result page loading={active && query.isPending} error={query.error} retry={query.refetch} retrying={query.isFetching} />{query.data && (section !== '09-剧集制作' || active) && <Section value={query.data} project={project} section={section} revision={revision} active={active} asset={asset} onAssetChange={onAssetChange} episode={episode} onEpisodeChange={onEpisodeChange} />}</section>;
}
function Section({ value, project, section, revision, active, episode, onEpisodeChange, asset, onAssetChange }: { value: RecordData; project: string; section: string; revision: number; active: boolean; episode: string | null; onEpisodeChange: (episode: string | null) => void } & AssetNavigation) {
  if (section === '09-剧集制作') return <EpisodeProduction project={project} statistics={value.statistics} items={value.children} selected={episode} onSelect={onEpisodeChange} revision={revision} />;
  if (value.kind === 'covers') return <CoverLibrary value={value} revision={revision} />;
  if (value.kind === 'accounts') return <AccountLibrary value={value} revision={revision} />;
  if (section === '06-分集大纲') return <EpisodeOutlines value={value} />;
  if (value.kind === 'people' || value.kind === 'scenes' || value.kind === 'props') return <Assets value={value} project={project} revision={revision} active={active} asset={asset} onAssetChange={onAssetChange} />;
  if (section === '07-参考音频' || section === '08-参考视频') return <ReferenceLibrary value={value} revision={revision} active={active} asset={asset} onAssetChange={onAssetChange} />;
  if ('exists' in value) return value.exists ? <Document value={value} /> : <><p className="muted">尚无正式文档。</p><Groups groups={value.groups} /></>;
  return <Catalogue value={value} section={section} />;
}
function Catalogue({ value, section }: { value: RecordData; section: string }) {
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [page, setPage] = useState(1);
  const all: FileItem[] = value.children || value.items || value.files || [];
  const categories = Array.from(new Set(all.map(item => item.category).filter((value): value is string => !!value)));
  const matched = searchTree(all.filter(item => !category || item.category === category), search);
  return <>{value.note && <p className="muted">{value.note}</p>}<div className="toolbar"><SearchField label="搜索目录" placeholder="搜索名称、概要" value={search} onChange={value => { setSearch(value); setPage(1); }} />{categories.length > 0 && <TabSelect label="目录分类" selected={category} onChange={value => { setCategory(value); setPage(1); }} items={[{ value: '', label: '全部分类' }, ...categories.map((value) => ({ value, label: value }))]} />}</div>
    {!all.length && <p className="muted">暂无资料。</p>}<FileTree key={section} items={matched.slice((page - 1) * 36, page * 36)} />
    <Pagination page={page} total={matched.length} change={setPage} /><Groups groups={value.groups} /></>;
}
function Assets({ value, project, revision, active, asset, onAssetChange }: { value: RecordData; project: string; revision: number; active: boolean } & AssetNavigation) {
  const [search, setSearch] = useState('');
  const selected = asset?.id || null;
  const [tab, setTab] = useState('资料卡');
  const voice = useAudioPreview(active, selected, revision);
  const voiceButton = (item: RecordData) => <AudioPreviewButton name={`${item.name}音色`} enabled={!!item.voice} playing={voice.playingId === item.id} progress={voice.currentId === item.id ? voice.progress : 0} onClick={() => voice.toggle(item.id, item.voice.url)} />;
  const detail = useQuery({ queryKey: ['asset', project, value.kind, selected, revision], queryFn: () => get<RecordData>(`${projectUrl(project)}/assets/${value.kind}/${encodeURIComponent(selected!)}`), enabled: !!selected, placeholderData: (previous, query) => query?.queryKey[3] === selected ? previous : undefined });
  const person = value.kind === 'people';
  const activeTab = person && tab === '候选与审阅' ? personImageCategory(detail.data?.candidates.find((item: RecordData) => item.pending) || {}) : tab;
  const tabs = person ? ['资料卡', ...personImageTabs, '相关文件'] : ['资料卡', '正式参考图', '候选与审阅', '相关文件'];
  const matched = value.items.filter((item: RecordData) => `${item.id} ${item.name} ${item.role}`.toLowerCase().includes(search.toLowerCase()));
  return <>
    {value.kind === 'people' && voice.player}
    <div hidden={!!selected}><div className="toolbar"><SearchField label="搜索资料" placeholder="搜索编号、名称" value={search} onChange={setSearch} /><span className="muted">共{matched.length}项</span></div>
      <div className="grid asset-list-grid">{matched.map((item: RecordData) => <article className="asset-card" key={item.id}>
        <button className={value.kind === 'people' && item.cover?.media ? 'cover character-cover-image' : 'cover'} onClick={() => { onAssetChange({ id: item.id, name: item.name }); setTab('资料卡'); }}>{item.cover?.media ? <img loading="lazy" src={item.cover.media.url + `?v=${revision}`} alt={item.name} /> : <span>{item.id}</span>}</button>
        <div className="asset-card-heading"><PointerTooltip text={`${item.id} · ${item.name}`}><h3 >{item.id} · {item.name}</h3></PointerTooltip>{value.kind === 'people' && voiceButton(item)}</div>
        <PointerTooltip text={item.role}><p className="asset-card-role" ><span className="field-label">{({ people: '人物定位', scenes: '场景类型', props: '道具类别' } as Record<string, string>)[value.kind]}：</span>{item.role}</p></PointerTooltip>
        <div className="asset-card-footer"><div className="asset-card-status"><span>资料卡状态：</span><Rich html={item.statusHtml} /></div><p className="muted">正式参考图 {item.formalCount} · 候选 {item.candidateCount}</p>
        <button onClick={() => { onAssetChange({ id: item.id, name: item.name }); setTab('资料卡'); }}>查看详情</button></div> {item.pendingCount > 0 && <button className="pending" onClick={() => { onAssetChange({ id: item.id, name: item.name }); setTab('候选与审阅'); }}>留存待确认／待审核 {item.pendingCount}</button>}
      </article>)}</div><Groups groups={value.groups} /></div>
    {selected && <><Result loading={detail.isPending} error={detail.error} retry={detail.refetch} retrying={detail.isFetching} />{detail.data && <><div className="asset-detail-heading"><h2>{detail.data.id} · {detail.data.name}</h2>{value.kind === 'people' && voiceButton(detail.data)}</div><TabNav label="资产详情" items={tabs.map(label => ({ value: label, label }))} selected={activeTab} onChange={setTab} />
      <div hidden={tab !== '资料卡'}><Document key={detail.data.id} value={detail.data.card} /></div>
      {person ? personImageTabs.includes(activeTab) && <PersonImages key={`${selected}-${activeTab}`} detail={detail.data} category={activeTab} revision={revision} /> : <><div hidden={tab !== '正式参考图'}><AssetMedia items={[...detail.data.formal, ...(detail.data.auxiliary || []), ...(detail.data.legacy || [])]} revision={revision} formal /></div>
      <div hidden={tab !== '候选与审阅'}>{tab === '候选与审阅' && <AssetCandidateMedia key={selected} items={detail.data.candidates} revision={revision} />}</div></>}
      <div hidden={tab !== '相关文件'}>{detail.data.recordKey && !detail.data.groups.some((group: RecordData) => group.files.some((file: FileItem) => file.key === detail.data.recordKey)) && <FileTree items={[{ kind: 'markdown', name: '完整生成记录', key: detail.data.recordKey, url: `${projectUrl(project)}/files/${detail.data.recordKey}` }]} />}<FileTree items={detail.data.groups.map((group: RecordData) => ({ kind: 'group', ...group }))} /></div>
    </>}</>}
  </>;
}
