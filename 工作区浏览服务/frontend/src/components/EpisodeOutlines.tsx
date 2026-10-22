import { TabSelect } from './TabSelect';
import { useContext, useState } from 'react';
import type { FileItem, RecordData } from '../api';
import { FileTree, Groups, PreviewContext } from '../components';
import { EpisodeButton } from './EpisodeButton';
import { Pagination } from './Pagination';
import { SearchField } from './SearchField';

export function EpisodeOutlines({ value }: { value: RecordData }) {
  const preview = useContext(PreviewContext);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [page, setPage] = useState(1);
  const items: FileItem[] = value.children;
  const outlines = items.filter(item => item.kind === 'outline');
  const categories = Array.from(new Set(outlines.map(item => item.category).filter((value): value is string => !!value)));
  const matched = outlines.filter(item => (!category || item.category === category) && `${item.name} ${item.title || ''} ${item.summary || ''}`.toLowerCase().includes(search.toLowerCase()));
  return <>
    <p className="muted">{value.note}</p>
    <div className="toolbar"><SearchField label="搜索分集大纲" placeholder="搜索集号、题名、概要" value={search} onChange={value => { setSearch(value); setPage(1); }} />{categories.length > 0 && <TabSelect label="大纲故事阶段" selected={category} onChange={value => { setCategory(value); setPage(1); }} items={[{ value: '', label: '全部分类' }, ...categories.map((value) => ({ value, label: value }))]} />}</div>
    <div className="episode-grid">{matched.slice((page - 1) * 36, page * 36).map(item => <EpisodeButton key={item.key} item={item} onSelect={() => preview({ kind: 'markdown', name: item.name, key: item.key, url: item.url })} />)}</div>
    {!matched.length && <p className="muted">暂无匹配的分集大纲。</p>}
    <Pagination page={page} total={matched.length} change={setPage} />
    <FileTree items={items.filter(item => item.kind !== 'outline')} /><Groups groups={value.groups} />
  </>;
}
