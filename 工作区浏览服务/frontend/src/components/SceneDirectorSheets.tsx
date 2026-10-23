import { useContext, useState } from 'react';
import type { DirectorSheets } from '../api';
import { PreviewContext } from '../components';
import { FileActions } from './FileActions';
import { Pagination } from './Pagination';
import { TabSelect } from './TabSelect';
import './SceneDirectorSheets.css';

export function SceneDirectorSheets({ sheets, storyboardVersion, revision }: { sheets?: DirectorSheets; storyboardVersion: string; revision: number }) {
  const preview = useContext(PreviewContext);
  const [choice, setChoice] = useState('');
  const [pageKey, setPageKey] = useState('');
  const candidates = sheets?.candidates.filter(item => item.sourceVersion === storyboardVersion && item.candidateNumber) || [];
  const versions = [...new Set(candidates.map(item => item.version))].sort((a, b) =>
    candidates.find(item => item.version === b)!.candidateNumber! - candidates.find(item => item.version === a)!.candidateNumber!);
  const options = versions.map(version => {
    const pages = candidates.filter(item => item.version === version);
    const adopted = pages.filter(item => item.adopted).length;
    return { value: version, label: `候选${pages[0].candidateNumber}（${pages.length}张）`,
      badge: adopted === pages.length ? '已采用' : adopted ? '部分已采用' : undefined };
  });
  const selected = options.some(item => item.value === choice) ? choice
    : options.find(item => item.badge)?.value || options[0]?.value || '';
  const images = candidates.filter(item => item.version === selected).map(item =>
    item.adopted ? sheets!.formal.find(formal => formal.sourceVersion === storyboardVersion
      && formal.version === item.version && formal.page === item.page)! : item);
  const pageIndex = Math.max(0, images.findIndex(item => String(item.page) === pageKey));
  const current = images[pageIndex];
  return <section aria-label="本场导演分镜表">
    <div className="toolbar director-sheet-toolbar">
      <div className="director-sheet-choice"><span className="director-sheet-source">{storyboardVersion ? `场次分镜：${storyboardVersion.toUpperCase()}` : '未确定来源分镜版本'}</span>
        {options.length > 0 && <TabSelect highlightSelected label="导演分镜表候选" selected={selected} onChange={value => { setChoice(value); setPageKey(''); }} items={options} />}</div>
      {sheets?.record && <div className="director-sheet-record"><button className="link" onClick={() => preview(sheets.record!)}>查看导演表生成与审阅记录</button></div>}
    </div>
    {current ? <>
      <div className="director-sheet-viewer">
        <button className="director-sheet-image" aria-label={`放大第${String(current.page).padStart(2, '0')}页导演分镜表`} onClick={() => preview(current)}>
          <img src={current.url + `?v=${revision}`} alt={current.name} />
        </button>
        <Pagination variant="arrows" page={pageIndex + 1} total={images.length} pageSize={1} change={page => setPageKey(String(images[page - 1].page))} />
      </div>
      <div className="director-sheet-files"><FileActions url={current.url} /></div>
      {images.length === 1 ? <p className="director-sheet-single-page">第1页 / 共1页</p>
        : <Pagination page={pageIndex + 1} total={images.length} pageSize={1} showItemCount={false} change={page => setPageKey(String(images[page - 1].page))} />}
    </>
      : <p className="muted">{!storyboardVersion ? '该轮缺少来源分镜版本，无法关联导演分镜表。' : `分镜 ${storyboardVersion} 尚未制作导演分镜表。`}{sheets?.candidates.some(item => !item.sourceVersion || !item.candidateNumber) && '本场有图片尚未登记来源或候选编号，请查看生成与审阅记录。'}</p>}
  </section>;
}
