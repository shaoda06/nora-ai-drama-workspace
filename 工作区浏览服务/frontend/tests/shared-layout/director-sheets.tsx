import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { EpisodeProduction } from '../../src/components/EpisodeProduction';
import type { DirectorSheets, FileItem, SceneRound } from '../../src/api';
import { Preview, PreviewContext } from '../../src/components';
import { SceneDirectorSheets } from '../../src/components/SceneDirectorSheets';

const image = (page: number, version = 'v02', sourceVersion = 'v07', candidateNumber = 2, adopted = false) => ({
  kind: 'image', name: `EP001-C001-手绘导演分镜表-${version}-第${String(page).padStart(2, '0')}页.png`,
  key: `${version}-${page}`, url: '/component-samples/image.svg', page, version, sourceVersion, candidateNumber, adopted,
});
const sheets: DirectorSheets = { formal: [image(1), image(2), image(3)],
  candidates: [image(1, 'v01', 'v07', 1), image(3, 'v01', 'v07', 1),
    image(1, 'v02', 'v07', 2, true), image(2, 'v02', 'v07', 2, true), image(3, 'v02', 'v07', 2, true), image(1, 'v03', 'v08', 1)],
  record: { kind: 'document', name: '导演表生成与审阅记录', doc: { html: '<p>隔离示例审阅记录</p>' } } };

export function DirectorSheetsFixture() {
  const client = useQueryClient();
  const [mode, setMode] = useState('formal');
  const [preview, setPreview] = useState<FileItem | null>(null);
  const version = mode === 'old' ? 'v01' : mode === 'other' ? 'v08' : 'v07';
  const data = mode === 'seven' ? { ...sheets, formal: [], candidates: Array.from({ length: 7 }, (_, index) => image(index + 1)) } : mode === 'empty' ? undefined : mode === 'candidate' ? { ...sheets, formal: [], candidates: sheets.candidates.map(item => ({ ...item, adopted: false })) } : sheets;
  const rounds: SceneRound[] = [1, 2].map(number => ({ number, created_at: '', script: null,
    storyboard: { kind: 'document', name: '分镜', version: number === 1 ? 'v01' : 'v07' }, issues: [], segments: [{ id: 'P001', duration: 1, stage: '一采', run: 'R001' }] }));
  const episode = ['C001', 'C002', 'C003', 'C004'].map((id, index) => ({ id, rounds,
    storyboardVersion: 'v07',
    sheets: { formal: [] as DirectorSheets['formal'], candidates: (index === 1 ? [image(3, 'v01', 'v07', 1), image(1, 'v01', 'v07', 1), image(2, 'v01', 'v07', 1), image(1, 'v02', 'v07', 2)] : [image(1, 'v01', 'v07', 1)])
      .map(item => ({ ...item, name: item.name.replace('C001', id), adopted: index === 1 && item.version === 'v01' })),
      record: { kind: 'document', name: id + '审阅记录', doc: { html: '<p>' + id + '记录正文</p>' } } } }));
  episode[1].sheets.formal = episode[1].sheets.candidates.filter(item => item.adopted);
  const openEpisode = () => {
    client.setQueryDefaults(['episode', 'director-fixture'], { staleTime: Infinity });
    client.setQueryData(['episode', 'director-fixture', 'EP001', 1], {
      name: 'EP001', scenes: episode.map(item => item.id),
      segments: Object.fromEntries(episode.map(item => [item.id, [{ id: 'P001', duration: 1, videos: [] }]])),
      sceneRounds: Object.fromEntries(episode.map(item => [item.id, rounds])),
      directorSheets: Object.fromEntries(episode.map(item => [item.id, item.sheets])),
    });
    setMode('episode');
  };
  return <section data-testid="director-sheets" className="panel">
    <h2>导演分镜表隔离检查</h2>
    <button onClick={openEpisode}>模拟整集六页</button>
    <button onClick={() => setMode('seven')}>模拟七页候选</button>
    <button onClick={() => setMode('candidate')}>模拟仅候选</button>
    <button onClick={() => setMode('empty')}>模拟空场次</button>
    <button onClick={() => setMode('old')}>模拟无图旧版分镜</button>
    <button onClick={() => setMode('other')}>模拟其他来源分镜</button>
    <button onClick={() => client.setQueryData<FileItem>(['episode', 'director-fixture', 'EP001', 1], data => ({ ...data!,
      sceneRounds: { ...data!.sceneRounds, C003: [{ ...rounds[1], storyboard: { kind: 'document', name: '分镜', version: 'v08' } }] },
    }))}>模拟其他场次最新轮次无图</button>
    <PreviewContext.Provider value={setPreview}>
      {mode === 'episode' ? <EpisodeProduction project="director-fixture" selected="EP001" onSelect={() => {}} revision={1}
        items={[{ kind: 'group', name: 'EP001' }]} statistics={{ total: 1, completed: 0, running: 1, notStarted: 0 }} />
        : <div className="episode-scene-content"><SceneDirectorSheets key={mode} sheets={data} storyboardVersion={version} revision={1} /></div>}

      {preview && <Preview project="fixture-only" item={preview} revision={1} close={() => setPreview(null)} />}
    </PreviewContext.Provider>
  </section>;
}
