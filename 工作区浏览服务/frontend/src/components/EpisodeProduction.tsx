import { useRef, useState } from 'react';
import type { FileItem } from '../api';
import { searchTree } from '../api';
import { FileTree, Rich } from '../components';
import { SearchField } from './SearchField';
import { Pagination } from './Pagination';

export function EpisodeProduction({ items, selected, onSelect }: { items: FileItem[]; selected: string | null; onSelect: (episode: string | null) => void }) {
  const [search, setSearch] = useState('');
  const [fileSearch, setFileSearch] = useState('');
  const [page, setPage] = useState(1);
  const heading = useRef<HTMLHeadingElement>(null);
  const cards = useRef<HTMLDivElement>(null);
  const current = items.find(item => item.name === selected);
  const files = searchTree(current?.children || [], fileSearch);
  const matched = items.filter(item => `${item.name} ${item.title || ''}`.toLowerCase().includes(search.toLowerCase()));
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
    <div className="toolbar"><SearchField label="搜索剧集" placeholder="搜索集号、题名" value={search} onChange={value => { setSearch(value); setPage(1); }} /><span className="muted">共 {matched.length} 集</span></div>
    <div ref={cards} className="episode-grid">{matched.slice((page - 1) * 36, page * 36).map(item => <button className="episode-card" data-episode={item.name} key={item.key} onClick={() => open(item.name)}>
      <span className="episode-card-heading"><strong>{item.name}</strong><Rich html={item.statusHtml} /></span>
      <span className="episode-title">{item.title || '题名未记录'}</span>
      <span className="muted">{item.summary} · {item.children?.length || 0} 个目录／文件入口</span>
    </button>)}</div>
    {!matched.length && <p className="muted">{items.length ? '没有找到匹配的剧集。' : '尚无剧集制作目录。'}</p>}
    <Pagination page={page} total={matched.length} change={setPage} />
  </>;
}
