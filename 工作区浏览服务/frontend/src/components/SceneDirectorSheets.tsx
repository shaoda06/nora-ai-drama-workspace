import { useContext, useState } from 'react';
import type { DirectorSheets } from '../api';
import { PreviewContext } from '../components';
import { AssetMediaCard } from './AssetMediaCard';
import { TabSelect } from './TabSelect';

export function SceneDirectorSheets({ sheets, revision }: { sheets?: DirectorSheets; revision: number }) {
  const preview = useContext(PreviewContext);
  const [choice, setChoice] = useState('formal');
  if (!sheets) return <p className="muted">本场尚无导演分镜表。需要制作时，以场次分镜为依据另行安排。</p>;
  const versions = [...new Set(sheets.candidates.map(item => item.version))].sort((a, b) => Number(b.slice(1)) - Number(a.slice(1)));
  const options = [{ value: 'formal', label: `已采用（${sheets.formal.length}张）` },
    ...versions.map(version => ({ value: version, label: `候选与历史 ${version}（${sheets.candidates.filter(item => item.version === version).length}张）` }))];
  const selected = options.some(item => item.value === choice) ? choice : 'formal';
  const formal = selected === 'formal';
  const images = formal ? sheets.formal : sheets.candidates.filter(item => item.version === selected);
  return <section aria-label="本场导演分镜表">
    <div className="toolbar">
      <TabSelect label="导演分镜表版本" selected={selected} onChange={setChoice} items={options} />
      {sheets.record && <button className="link" onClick={() => preview(sheets.record!)}>查看导演表生成与审阅记录</button>}
    </div>
    <p className="muted">{formal ? '当前已采用的正式图片，按页码排列。' : '保留的生成候选与历史试稿；本组不代表当前正式采用。'}点击图片可放大查看。</p>
    {images.length ? <div className="asset-media-grid">{images.map(item => <AssetMediaCard
      key={item.key} title={`第${String(item.page).padStart(2, '0')}页`} formal={formal} revision={revision}
      item={{ media: item, version: item.version }} />)}</div>
      : <p className="muted">本场尚无已采用的正式导演分镜表，可切换查看已有候选。</p>}
  </section>;
}
