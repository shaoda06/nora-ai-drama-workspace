import { useContext, useEffect, useRef, useState } from 'react';
import type { FileItem } from '../api';
import { PreviewContext } from '../components';
import { TabNav } from './TabNav';
import { Pagination } from './Pagination';
import { EpisodeButton } from './EpisodeButton';
import { SceneWorkspace } from './SceneWorkspace';

export function EpisodeProduction({ project, items, selected, onSelect, revision }: { project: string; items: FileItem[]; selected: string | null; onSelect: (episode: string | null) => void; revision: number }) {
  const preview = useContext(PreviewContext);
  const [scene, setScene] = useState('');
  const [page, setPage] = useState(1);
  const cards = useRef<HTMLDivElement>(null);
  const previousEpisode = useRef(selected);
  useEffect(() => {
    if (!selected && previousEpisode.current) cards.current!.querySelector<HTMLButtonElement>(`[data-episode="${previousEpisode.current}"]`)!.focus();
    previousEpisode.current = selected;
  }, [selected]);
  const current = items.find(item => item.name === selected);
  const script = current?.children?.find(item => item.name === '02-剧集剧本')?.children?.find(item => item.name === `${current.name}-本集剧本.md`);
  const scenes = current?.scenes || [];
  const selectedScene = scene || scenes[0] || '';
  const segments = current?.segments?.[selectedScene] || [];
  const open = (name: string) => {
    setScene('');
    onSelect(name);
  };
  return current ? <div className="episode-detail">
    <div className="episode-scene-header">
      {scenes.length > 0 && <TabNav label="本集场次" items={scenes.map(id => ({ value: id, label: '场次 ' + id }))} selected={selectedScene} onChange={setScene} />}
      <button className="link episode-script-link" disabled={!script} title={script ? undefined : '本集剧本尚未建立'} onClick={() => preview(script!)}>查看本集剧本</button>
    </div>
    <SceneWorkspace key={current.name + '/' + selectedScene} scope={{ project, episode: current.name, scene: selectedScene }} segments={segments} revision={revision} />
  </div> : <>
    <div ref={cards} className="episode-grid">{items.slice((page - 1) * 36, page * 36).map(item => <EpisodeButton key={item.key} item={item} onSelect={open} />)}</div>
    {!items.length && <p className="muted">尚无剧集制作目录。</p>}
    <Pagination page={page} total={items.length} change={setPage} />
  </>;
}
