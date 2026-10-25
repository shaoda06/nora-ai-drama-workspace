import { useContext, useState } from 'react';
import type { DirectorSheets, SceneRound } from '../api';
import { Dialog, PreviewContext } from '../components';
import { FileActions } from './FileActions';
import { Pagination } from './Pagination';
import { TabNav } from './TabNav';
import { TabSelect } from './TabSelect';
import './SceneDirectorSheets.css';

export interface DirectorSheetScene {
  id: string;
  sheets?: DirectorSheets;
  storyboardVersion: string;
  rounds?: SceneRound[];
  selectedRound?: number;
}

export function SceneDirectorSheets({ sheets, storyboardVersion = '', scenes, onRoundChange, revision }: {
  sheets?: DirectorSheets; storyboardVersion?: string; scenes?: DirectorSheetScene[];
  onRoundChange?: (scene: string, round: number) => void; revision: number;
}) {
  const preview = useContext(PreviewContext);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [pageKey, setPageKey] = useState('');
  const [fullscreen, setFullscreen] = useState(false);
  const groups = (scenes || [{ id: '', sheets, storyboardVersion }]).map(scene => {
    const sourceKey = `${scene.id}/${scene.storyboardVersion}`;
    const candidates = scene.sheets?.candidates.filter(item => item.sourceVersion === scene.storyboardVersion && item.candidateNumber) || [];
    const versions = [...new Set(candidates.map(item => item.version))].sort((a, b) =>
      candidates.find(item => item.version === b)!.candidateNumber! - candidates.find(item => item.version === a)!.candidateNumber!);
    const options = versions.map(version => {
      const pages = candidates.filter(item => item.version === version);
      const adopted = pages.filter(item => item.adopted).length;
      return { value: version, label: `候选${pages[0].candidateNumber}（${pages.length}张）`,
        badge: adopted === pages.length ? '已采用' : adopted ? '部分已采用' : undefined };
    });
    const selected = options.some(item => item.value === choices[sourceKey]) ? choices[sourceKey]
      : options.find(item => item.badge)?.value || options[0]?.value || '';
    const images = candidates.filter(item => item.version === selected).sort((a, b) => a.page - b.page).map(item =>
      item.adopted ? scene.sheets!.formal.find(formal => formal.sourceVersion === scene.storyboardVersion
        && formal.version === item.version && formal.page === item.page)! : item);
    return { ...scene, sourceKey, options, selected, images };
  });
  const pages = groups.flatMap(group => group.images.map((image, index) => ({
    key: `${group.id}/${image.page}`, image, group, index,
  })));
  const exactIndex = pages.findIndex(item => item.key === pageKey);
  const pageIndex = exactIndex >= 0 ? exactIndex : Math.max(0, pages.findIndex(item => item.group.id === pageKey.split('/')[0]));
  const current = pages[pageIndex];
  const active = current?.group || groups[0];
  const selectPage = (page: number) => setPageKey(pages[page - 1].key);
  const count = `${scenes ? '整集' : ''}第${pageIndex + 1}页 / 共${pages.length}页`;
  const sceneCount = current && scenes ? ` · ${current.group.id} 第${current.index + 1}页 / 共${current.group.images.length}页` : '';
  const roundSelector = (group: typeof groups[number]) => !!group.rounds?.length && onRoundChange && <TabSelect size="toolbar" highlightSelected
    label={`${group.id} 修改轮次`} selected={String(group.selectedRound)} onChange={value => { setPageKey(`${group.id}/`); onRoundChange(group.id, Number(value)); }}
    items={[...group.rounds].reverse().map(round => ({ value: String(round.number), label: `第${round.number}轮：剧本${round.script?.version || '缺失'} · 分镜${round.storyboard?.version || '缺失'}` }))} />;
  const emptyMessage = (group: typeof groups[number]) => <p className="muted">
    {scenes && `场次 ${group.id}：`}{!group.storyboardVersion ? '该轮缺少来源分镜版本，无法关联导演分镜表。' : `分镜 ${group.storyboardVersion} 尚未制作导演分镜表。`}
    {group.sheets?.candidates.some(item => !item.sourceVersion || !item.candidateNumber) && '本场有图片尚未登记来源或候选编号，请查看生成与审阅记录。'}
  </p>;
  return <section aria-label={scenes ? '整集导演分镜表' : '本场导演分镜表'}>
    {scenes && <h3>整集导演分镜表</h3>}
    {active && <div className="toolbar director-sheet-toolbar">
      <div className="director-sheet-choice">{scenes && <span className="director-sheet-source">场次 {active.id}</span>}
        {roundSelector(active)}
        {active.options.length > 0 && <TabSelect highlightSelected label="导演分镜表候选" selected={active.selected} onChange={value => {
          setChoices(previous => ({ ...previous, [active.sourceKey]: value })); setPageKey(`${active.id}/`);
        }} items={active.options} />}</div>
      {current && <div className="director-sheet-pages"><TabNav compact scrollable label="导演分镜表页码"
        items={pages.map((item, index) => ({ value: item.key, label: String(index + 1) }))}
        selected={current.key} onChange={setPageKey} /></div>}
      {active.sheets?.record && <div className="director-sheet-record"><button className="link" onClick={() => preview(active.sheets!.record!)}>查看导演表生成与审阅记录</button></div>}
    </div>}
    {current ? <>
      <div className="director-sheet-viewer">
        <button className="director-sheet-image" aria-label={`全屏查看第${String(pageIndex + 1).padStart(2, '0')}页导演分镜表`} onClick={() => setFullscreen(true)}>
          <img src={current.image.url + `?v=${revision}`} alt={current.image.name} />
        </button>
        <Pagination variant="arrows" page={pageIndex + 1} total={pages.length} pageSize={1} change={selectPage} />
      </div>
      <div className="director-sheet-footer">
        <p className="director-sheet-page-count" aria-live="polite">{count}{sceneCount}</p>
        <div className="director-sheet-file-actions"><FileActions url={current.image.url} viewLabel="查看原图" downloadLabel="下载原图" /></div>
      </div>
      {fullscreen && <Dialog size="fullscreen" showHeader={false} title={`导演分镜表 · ${count}${sceneCount}`} close={() => setFullscreen(false)}>
        <div className="director-sheet-fullscreen">
          <button className="director-sheet-fullscreen-image" aria-label="退出全屏看图" onClick={() => setFullscreen(false)}><img src={current.image.url + `?v=${revision}`} alt={current.image.name} /></button>
          <Pagination variant="arrows" page={pageIndex + 1} total={pages.length} pageSize={1} change={selectPage} />
        </div>
      </Dialog>}
    </> : active && emptyMessage(active)}
    {scenes && groups.filter(group => !group.images.length && group !== active).map(group => <div key={group.id}>
      {emptyMessage(group)}{roundSelector(group)}
      {group.sheets?.record && <button className="link" onClick={() => preview(group.sheets!.record!)}>查看 {group.id} 生成与审阅记录</button>}
    </div>)}
  </section>;
}
