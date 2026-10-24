import { useContext, useState } from 'react';
import type { DirectorSheets } from '../api';
import { Dialog, PreviewContext } from '../components';
import { FileActions } from './FileActions';
import { Pagination } from './Pagination';
import { TabNav } from './TabNav';
import { TabSelect } from './TabSelect';
import './SceneDirectorSheets.css';

export function SceneDirectorSheets({ sheets, storyboardVersion, revision }: { sheets?: DirectorSheets; storyboardVersion: string; revision: number }) {
  const preview = useContext(PreviewContext);
  const [choice, setChoice] = useState('');
  const [pageKey, setPageKey] = useState('');
  const [fullscreen, setFullscreen] = useState(false);
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
      {current && <div className="director-sheet-pages"><TabNav compact scrollable label="导演分镜表页码"
        items={images.map((item, index) => ({ value: String(item.page), label: String(index + 1) }))}
        selected={String(current.page)} onChange={setPageKey} /></div>}
      {sheets?.record && <div className="director-sheet-record"><button className="link" onClick={() => preview(sheets.record!)}>查看导演表生成与审阅记录</button></div>}
    </div>
    {current ? <>
      <div className="director-sheet-viewer">
        <button className="director-sheet-image" aria-label={`全屏查看第${String(current.page).padStart(2, '0')}页导演分镜表`} onClick={() => setFullscreen(true)}>
          <img src={current.url + `?v=${revision}`} alt={current.name} />
        </button>
        <Pagination variant="arrows" page={pageIndex + 1} total={images.length} pageSize={1} change={page => setPageKey(String(images[page - 1].page))} />
      </div>
      <div className="director-sheet-footer">
        <p className="director-sheet-page-count" aria-live="polite">第{pageIndex + 1}页 / 共{images.length}页</p>
        <div className="director-sheet-file-actions"><FileActions url={current.url} viewLabel="查看原图" downloadLabel="下载原图" /></div>
      </div>
      {fullscreen && <Dialog size="fullscreen" showHeader={false} title={`导演分镜表 · 第${pageIndex + 1}页 / 共${images.length}页`} close={() => setFullscreen(false)}>
        <div className="director-sheet-fullscreen">
          <button className="director-sheet-fullscreen-image" aria-label="退出全屏看图" onClick={() => setFullscreen(false)}><img src={current.url + `?v=${revision}`} alt={current.name} /></button>
          <Pagination variant="arrows" page={pageIndex + 1} total={images.length} pageSize={1} change={page => setPageKey(String(images[page - 1].page))} />
        </div>
      </Dialog>}
    </>
      : <p className="muted">{!storyboardVersion ? '该轮缺少来源分镜版本，无法关联导演分镜表。' : `分镜 ${storyboardVersion} 尚未制作导演分镜表。`}{sheets?.candidates.some(item => !item.sourceVersion || !item.candidateNumber) && '本场有图片尚未登记来源或候选编号，请查看生成与审阅记录。'}</p>}
  </section>;
}
