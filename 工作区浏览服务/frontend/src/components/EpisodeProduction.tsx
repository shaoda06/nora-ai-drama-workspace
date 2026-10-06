import { useRef, useState } from 'react';
import type { FileItem } from '../api';
import { searchTree } from '../api';
import { FileTree, Rich } from '../components';
import { SearchField } from './SearchField';
import { Pagination } from './Pagination';
import { EpisodeButton } from './EpisodeButton';

export function EpisodeProduction({ items, selected, onSelect }: { items: FileItem[]; selected: string | null; onSelect: (episode: string | null) => void }) {
  const [fileSearch, setFileSearch] = useState('');
  const [page, setPage] = useState(1);
  const heading = useRef<HTMLHeadingElement>(null);
  const cards = useRef<HTMLDivElement>(null);
  const current = items.find(item => item.name === selected);
  const files = searchTree(current?.children || [], fileSearch);
  const open = (name: string) => {
    setFileSearch('');
    onSelect(name);
    requestAnimationFrame(() => { heading.current!.scrollIntoView({ block: 'start' }); heading.current!.focus({ preventScroll: true }); });
  };
  const back = () => {
    onSelect(null);
    requestAnimationFrame(() => cards.current!.querySelector<HTMLButtonElement>(`[data-episode="${selected}"]`)!.focus());
  };
  return current ? <div className="episode-detail">
    <button onClick={back}>← 返回选集列表</button>
    <h3 ref={heading} tabIndex={-1}>{current.name} · {current.title || '题名未记录'}</h3>
    <Rich html={current.statusHtml} />
    <div className="toolbar"><SearchField label="搜索本集文件" placeholder="搜索本集目录、文件" value={fileSearch} onChange={setFileSearch} /></div>
    <FileTree key={current.key} items={files} />
    {!current.children?.length && <p className="muted">本集暂无文件。</p>}
    {fileSearch && !files.length && <p className="muted">没有找到匹配的目录或文件。</p>}
  </div> : <>
    <div ref={cards} className="episode-grid">{items.slice((page - 1) * 36, page * 36).map(item => <EpisodeButton key={item.key} item={item} onSelect={open} />)}</div>
    {!items.length && <p className="muted">尚无剧集制作目录。</p>}
    <Pagination page={page} total={items.length} change={setPage} />
  </>;
}
