import { PointerTooltip } from './PointerTooltip';
import { useContext, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useQuery } from '@tanstack/react-query';
import type { FileItem } from '../api';
import { PreviewContext, Result, Rich } from '../components';
import { TabNav } from './TabNav';
import { Pagination } from './Pagination';
import { EpisodeButton } from './EpisodeButton';
import { SceneWorkspace, type EpisodePlayback } from './SceneWorkspace';
import { useRefreshState } from '../refreshPosition';
import { BreadcrumbActionsContext, BreadcrumbSelectorContext } from './Breadcrumbs';
import { TabSelect } from './TabSelect';
import { get, projectUrl } from '../api';
import { DownloadButton } from './DownloadButton';
import { previousEpisodeEnding } from '../previousEpisodeEnding';
import type { EpisodeReview } from '../episodeRevisionNotes';
import { useRevisionNotesExport } from './RevisionNotes';
import './SceneDownloads.css';

export function EpisodeProduction({ project, items, statistics, selected, onSelect, revision }: { project: string; items: FileItem[]; statistics: { total: number; completed: number; notStarted: number; running: number }; selected: string | null; onSelect: (episode: string | null) => void; revision: number }) {
  const preview = useContext(PreviewContext);
  const breadcrumbActions = useContext(BreadcrumbActionsContext);
  const breadcrumbSelector = useContext(BreadcrumbSelectorContext);
  const [scene, setScene] = useRefreshState(`project/${project}/production/scene`, '');
  const [sceneView, setSceneView] = useRefreshState(`project/${project}/production/${selected || ''}/scene-view`, 'segments');
  const [integrateSheets, setIntegrateSheets] = useRefreshState(`project/${project}/production/${selected || ''}/integrate-sheets`, false);
  const [page, setPage] = useState(1);
  const [roundEntry, setRoundEntry] = useState(0);
  const [playback, setPlayback] = useState<{ episode: string; rounds: Record<string, number | undefined>; start?: EpisodePlayback['start'] } | null>(null);
  const cards = useRef<HTMLDivElement>(null);
  const previousEpisode = useRef(selected);
  useEffect(() => {
    if (!selected && previousEpisode.current) cards.current!.querySelector<HTMLButtonElement>(`[data-episode="${previousEpisode.current}"]`)?.focus();
    previousEpisode.current = selected;
  }, [selected]);
  const selectedItem = items.find(item => item.name === selected);
  const shared = items.filter(item => item.name === '片头' || item.name === '片尾');
  const episodes = items.filter(item => item.name !== '片头' && item.name !== '片尾');
  const sharedSelected = selected === '片头' || selected === '片尾';
  const contentLabel = sharedSelected ? `${selected}内容稿` : '本集剧本';
  const detail = useQuery({ queryKey: ['episode', project, selected, revision],
    queryFn: () => get<FileItem>(`${projectUrl(project)}/episodes/${selected}`), enabled: !!selectedItem,
    placeholderData: (previous, query) => query?.queryKey[2] === selected ? previous : undefined });
  const current = selectedItem && detail.data?.name === selected ? detail.data : undefined;
  useEffect(() => {
    if (selected && !selectedItem) onSelect(null);
  }, [selected, selectedItem, onSelect]);
  const [roundNumbers, setRoundNumbers] = useRefreshState<Record<string, number | null>>(`project/${project}/production/rounds`, {});
  const episodeRounds = current?.episodeRounds || [];
  const episodeChoice = current ? roundNumbers[current.name] === undefined ? episodeRounds.at(-1)?.number : roundNumbers[current.name] : undefined;
  const episodeRound = episodeRounds.find(item => item.number === episodeChoice);
  const scenes = episodeRound?.scenes || (episodeChoice === null
    ? (current?.scenes || []).filter(id => current?.sceneRounds?.[id]?.some(item => !item.episodeRound)) : current?.scenes || []);
  const selectedScene = scenes.includes(scene) ? scene : scenes[0] || '';
  const roundNumberForScene = (id: string) => {
    if (episodeRound) return episodeRound.number;
    const rounds = (current?.sceneRounds?.[id] || []).filter(item => episodeChoice !== null || !item.episodeRound);
    return rounds.find(item => item.number === roundNumbers[current!.name + '/' + id])?.number ?? rounds.at(-1)?.number;
  };
  const episodeReview: EpisodeReview | undefined = current ? {
    number: episodeRound?.number, rounds: episodeRounds.map(item => item.number),
    scenes: scenes.map(id => {
      const number = roundNumberForScene(id);
      const round = current.sceneRounds?.[id]?.find(item => item.number === number);
      return { id, number, segments: current.segments?.[id] || [], versions: round?.segments || [] };
    }),
  } : undefined;
  const episodeNotesExport = useRevisionNotesExport(current && selectedScene ? { project, episode: current.name, scene: selectedScene } : null, [], null, undefined, episodeReview);
  const directorScenes = scenes.map(id => {
    const rounds = current?.sceneRounds?.[id] || [];
    const selectedRound = episodeRound?.number ?? (id === selectedScene ? roundNumberForScene(id)
      : rounds.filter(item => episodeChoice !== null || !item.episodeRound).at(-1)?.number);
    const round = rounds.find(item => item.number === selectedRound);
    return { id, sheets: current?.directorSheets?.[id],
      storyboardVersion: round ? round.storyboard?.version || '' : current?.storyboards?.[id]?.version || '' };
  });
  const segments = current?.segments?.[selectedScene] || [];
  const sceneRounds = current?.sceneRounds?.[selectedScene] || [];
  const selectedRound = roundNumberForScene(selectedScene);
  const round = sceneRounds.find(item => item.number === selectedRound);
  const continuous = !!playback && playback.episode === current?.name;
  const nextScene = scenes[scenes.indexOf(selectedScene) + 1];
  const nextRoundNumber = continuous ? playback!.rounds[nextScene] : undefined;
  const nextRound = current?.sceneRounds?.[nextScene]?.find(item => item.number === nextRoundNumber);
  const nextEntry = nextRound?.segments[0];
  const nextVideo = nextEntry && current?.segments?.[nextScene]?.find(item => item.id === nextEntry.id)?.videos
    .find(video => video.stage === nextEntry.stage && video.run === nextEntry.run);
  const episodePlayback: EpisodePlayback = {
    continuous,
    start: continuous ? playback!.start : undefined,
    next: nextScene ? { scene: nextScene, round: nextRoundNumber, segment: nextEntry?.id, video: nextVideo } : undefined,
    onChange: checked => setPlayback(checked ? { episode: current!.name, rounds: Object.fromEntries(scenes.map(id =>
      [id, roundNumberForScene(id)])) } : null),
    onNext: () => {
      setRoundNumbers(previous => ({ ...previous, [current!.name + '/' + nextScene]: nextRoundNumber! }));
      setPlayback(previous => ({ ...previous!, start: { segment: nextEntry!.id, selection: { stage: nextVideo!.stage, key: nextVideo!.key } } }));
      setScene(nextScene);
    },
  };

  useEffect(() => {
    if (current && episodeRounds.length && roundNumbers[current.name] === undefined)
      setRoundNumbers(previous => ({ ...previous, [current.name]: episodeRounds.at(-1)!.number }));
    const key = (current?.name || '') + '/' + selectedScene;
    const fallback = episodeChoice === null ? sceneRounds.filter(item => !item.episodeRound).at(-1) : sceneRounds.at(-1);
    if (current && selectedScene && fallback && roundNumbers[key] === undefined)
      setRoundNumbers(previous => ({ ...previous, [key]: fallback.number }));
  }, [current?.name, selectedScene, sceneRounds, episodeRounds, roundNumbers, setRoundNumbers]);
  const script = round ? round.script : current?.script;
  const selectRound = (number: number) => {
    setPlayback(null);
    setRoundNumbers(previous => ({ ...previous, [current!.name + '/' + selectedScene]: number,
      ...(episodeRounds.length ? { [current!.name]: episodeRounds.some(item => item.number === number) ? number : null } : {}) }));
  };
  const openRound = (number: number) => {
    setRoundEntry(previous => previous + 1);
    selectRound(number);
  };
  const issues = (current?.productionIssues || []).filter(issue => !issue.scene || issue.scene === selectedScene);
  const episodeComplete = current?.productionComplete && !current.productionIssues?.length && scenes.length > 0 && scenes.every(id => {
    const sceneSegments = current.segments?.[id] || [];
    return sceneSegments.length > 0 && sceneSegments.every(item =>
      item.videos.filter(video => video.stage === '后处理' && video.approved).length === 1);
  });
  const segmentCount = scenes.reduce((count, id) => count + (current?.segments?.[id]?.length || 0), 0);
  const emptyMessage = issues.length > 0 ? '请先修正上方提示的文件结构，保存后页面会重新读取资料。'
    : !script ? `${contentLabel}尚未建立，请先准备内容，再整理场次分镜和分段计划。`
    : '本场尚无分段计划，请先完善本集分镜索引。';
  let directorFiles = current?.children;
  for (const folder of ['06-阶段采用视频', '01-一采', selectedScene + '-场次', '导演包']) {
    directorFiles = directorFiles?.find(item => item.name === folder)?.children;
  }
  const open = (name: string) => {
    setPlayback(null);
    setScene('');
    onSelect(name);
  };
  return <>
    {breadcrumbSelector && selectedItem && createPortal(<TabSelect iconOnly label="快速选择制作对象" selected={selected!} onChange={open}
      items={items.map(item => ({ value: item.name, label: `${item.name} · ${item.title || (item.name === '片头' || item.name === '片尾' ? '全剧通用' : '题名未记录')}${item.titleStatus ? `（${item.titleStatus}）` : ''}` }))} />, breadcrumbSelector)}
    {selectedItem && !current ? <Result page loading={detail.isPending} error={detail.error} retry={detail.refetch} retrying={detail.isFetching} /> : current ? <div className="episode-detail">
    {breadcrumbActions && episodeComplete && createPortal(<DownloadButton key={current.name} pack
      url={`${projectUrl(project)}/episodes/${current.name}/download`} label={`${sharedSelected ? current.name : '本集'}打包下载`}
      title={`下载${current.name}全部${scenes.length}个场次、${segmentCount}段后处理已采用视频`} />, breadcrumbActions)}
    <div className="episode-scene-header">
      {scenes.length > 0 && <TabNav label="本集场次" items={scenes.map(id => ({ value: id, label: '场次 ' + id }))} selected={selectedScene} onChange={value => { setPlayback(null); setScene(value); }} />}
      <div className="episode-scene-actions">
    {episodeRounds.length > 0 && <div className="scene-round-selector">
      <span className="production-latest">当前最新{selectedRound !== episodeRounds.at(-1)!.number && <>：第{episodeRounds.at(-1)!.number}轮，<button className="production-latest-link" aria-label="切换到最新修改轮次" onClick={() => openRound(episodeRounds.at(-1)!.number)}>点击切换</button></>}</span>
      <TabSelect size="toolbar" highlightSelected label="修改轮次" selected={String(selectedRound)} onChange={value => openRound(Number(value))}
        items={[...sceneRounds].reverse().map(item => ({ value: String(item.number), label: `第${item.number}轮` }))} />
    </div>}
      <PointerTooltip text={script ? undefined : `${contentLabel}尚未建立`}><button className="link episode-script-link" disabled={!script} onClick={() => preview(script!)}>查看{contentLabel}</button></PointerTooltip>
      </div>
    </div>
    {!!current.warnings?.length && <details className="notice"><summary>资料提示（{current.warnings.length}）</summary>{current.warnings.map(message => <p key={message}>{message}</p>)}</details>}
    {issues.length > 0 ? <div className="notice episode-data-issues" role="alert">
      <strong>制作资料需要修正</strong>
      <ul>{issues.map((issue, index) => <li key={index}>
        <PointerTooltip text={issue.key}><button className="link"  onClick={() => preview({ kind: 'document', key: issue.key, name: issue.key.split('/').pop()! })}>{issue.key.split('/').pop()}</button></PointerTooltip>：{issue.message}
      </li>)}</ul>
    </div> : null}
    {selectedScene ? <SceneWorkspace episodeNotesExportControl={episodeNotesExport.control} episodePlayback={episodePlayback} view={sceneView} onViewChange={setSceneView} key={current.name + '/' + selectedScene + (episodeRounds.length ? '/' + roundEntry : '')} scope={{ project, episode: current.name, scene: selectedScene }} segments={segments} sceneRounds={sceneRounds} selectedRound={selectedRound} onRoundChange={selectRound} showRoundSelector={!episodeRounds.length} previousEnding={previousEpisodeEnding(current.previousEpisode ? [current.previousEpisode] : [], current.name)} emptyMessage={emptyMessage} revision={revision} directorFiles={directorFiles || []} directorScenes={directorScenes} integrateSheets={integrateSheets} onIntegrateSheetsChange={setIntegrateSheets} storyboardVersion={round ? round.storyboard?.version || '' : current.storyboards?.[selectedScene]?.version || ''} storyboardDocument={round ? round.storyboard?.doc : current.storyboards?.[selectedScene]?.doc} />
      : <div className="scene-empty" role="status"><h3>暂无可显示的场次</h3><p className="muted">{emptyMessage}</p></div>}
    {episodeNotesExport.dialog}
    {!!current.materials?.length && <details className="asset-candidate-type production-materials"><summary>专用素材与图片候选（{current.materials.length}）</summary>
      {current.materialRecord && <p><button className="link" onClick={() => preview(current.materialRecord!)}>查看素材生成与审阅记录</button></p>}
      {(['pending', 'revision', 'adopted', 'unknown', 'history'] as const).map(group => {
        const images = current.materials!.filter(file => (file.materialGroup || 'unknown') === group)
          .sort((a, b) => b.name.replace(/\.[^.]+$/, '').localeCompare(a.name.replace(/\.[^.]+$/, ''), 'zh-CN', { numeric: true }));
        const label = { pending: '待审核', revision: '待修改', adopted: '当前采用', unknown: '状态待核对', history: '旧版留档与已采用源图' }[group];
        return images.length || group === 'adopted' ? <details key={group} className="asset-candidate-type" data-material-group={group} open={group !== 'history'}>
          <summary>{label}（{images.length}）</summary>
          {!images.length && <p className="muted">暂无适用于当前制作的已采用专用图；项目人物、场景和道具资产仍按素材索引引用。</p>}
          <div className="asset-media-grid">{images.map(file => <article className="asset-media-card" key={file.key}>
            <h3>{file.name}</h3>
            <p><span className={`status-badge status-${group === 'adopted' ? 'green' : group === 'history' ? 'gray' : 'orange'}`}>{file.materialStatus || '状态待核对'}</span></p>
            {file.approvalHtml && <div className="asset-media-field"><span className="field-label">审核决定：</span><Rich html={file.approvalHtml} /></div>}
            <p className="asset-media-field">{file.materialNote}</p>
            <button className="production-image-preview" onClick={() => preview(file)} aria-label={`查看${file.name}`}><img loading="lazy" src={file.url} alt={file.name} /></button>
            <div className="asset-media-footer"><DownloadButton url={file.url!} label="下载原图" title={`下载${file.name}`} />
              {file.materialReview && <button className="link" onClick={() => preview(file.materialReview!)}>查看审阅记录</button>}
            </div>
          </article>)}</div>
        </details> : null;
      })}
    </details>}
  </div> : <>
    <div ref={cards}>
      <section aria-label="片头与片尾"><h2>片头与片尾</h2><div className="episode-grid">{shared.map(item => <EpisodeButton key={item.key} item={item} onSelect={open} />)}</div>
        {!shared.length && <p className="muted">片头、片尾尚未开始制作。</p>}</section>
      <section aria-label="剧集制作"><h2>剧集制作</h2>
        <div className="production-statistics" aria-label="剧集制作统计"><span>共 <strong>{statistics.total}</strong> 集</span><span>未开始 <strong>{statistics.notStarted}</strong> 集</span><span>进行中 <strong>{statistics.running}</strong> 集</span><span>已完成 <strong>{statistics.completed}</strong> 集</span></div>
        <div className="episode-grid">{episodes.slice((page - 1) * 36, page * 36).map(item => <EpisodeButton key={item.key} item={item} onSelect={open} />)}</div>
        {!episodes.length && <p className="muted">尚无剧集制作目录。</p>}
        <Pagination page={page} total={episodes.length} change={setPage} />
      </section>
    </div>
  </>}</>;
}
