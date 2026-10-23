import { useContext, useState } from 'react';
import type { DirectorSheets } from '../api';
import { PreviewContext } from '../components';
import { FileActions } from './FileActions';
import { Pagination } from './Pagination';
import { TabNav } from './TabNav';
import { TabSelect } from './TabSelect';
import './SceneDirectorSheets.css';

export function SceneDirectorSheets({ sheets, revision }: { sheets?: DirectorSheets; revision: number }) {
  const preview = useContext(PreviewContext);
  const [choice, setChoice] = useState('formal');
  const [pageKey, setPageKey] = useState('');
  if (!sheets) return <p className="muted">本场尚无导演分镜表。需要制作时，以场次分镜为依据另行安排。</p>;
  const versions = [...new Set(sheets.candidates.map(item => item.version))].sort((a, b) => Number(b.slice(1)) - Number(a.slice(1)));
  const options = [{ value: 'formal', label: `已采用（${sheets.formal.length}张）` },
    ...versions.map(version => ({ value: version, label: `候选与历史 ${version}（${sheets.candidates.filter(item => item.version === version).length}张）` }))];
  const selected = options.some(item => item.value === choice) ? choice : 'formal';
  const formal = selected === 'formal';
  const images = formal ? sheets.formal : sheets.candidates.filter(item => item.version === selected);
  const pageIndex = Math.max(0, images.findIndex(item => String(item.page) === pageKey));
  const current = images[pageIndex];
  return <section aria-label="本场导演分镜表">
    <div className="toolbar director-sheet-toolbar">
      <TabSelect label="导演分镜表版本" selected={selected} onChange={value => { setChoice(value); setPageKey(''); }} items={options} />
      {sheets.record && <div className="director-sheet-record"><button className="link" onClick={() => preview(sheets.record!)}>查看导演表生成与审阅记录</button></div>}
    </div>
    {current ? <>
      <TabNav label="导演分镜表页码" selected={String(current.page)} onChange={setPageKey}
        items={images.map(item => ({ value: String(item.page), label: `第${String(item.page).padStart(2, '0')}页` }))} />
      <button className="director-sheet-image" aria-label={`放大第${String(current.page).padStart(2, '0')}页导演分镜表`} onClick={() => preview(current)}>
        <img src={current.url + `?v=${revision}`} alt={current.name} />
      </button>
      <div className="director-sheet-files"><FileActions url={current.url} /></div>
      {images.length === 1 ? <p className="director-sheet-single-page">第1页 / 共1页</p>
        : <Pagination page={pageIndex + 1} total={images.length} pageSize={1} showItemCount={false} change={page => setPageKey(String(images[page - 1].page))} />}
    </>
      : <p className="muted">本场尚无已采用的正式导演分镜表，可切换查看已有候选。</p>}
  </section>;
}
