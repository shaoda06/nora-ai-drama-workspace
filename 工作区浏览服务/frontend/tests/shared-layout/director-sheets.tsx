import { useState } from 'react';
import type { DirectorSheets, FileItem } from '../../src/api';
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
  const [mode, setMode] = useState('formal');
  const [preview, setPreview] = useState<FileItem | null>(null);
  const version = mode === 'old' ? 'v01' : mode === 'other' ? 'v08' : 'v07';
  const data = mode === 'seven' ? { ...sheets, formal: [], candidates: Array.from({ length: 7 }, (_, index) => image(index + 1)) } : mode === 'empty' ? undefined : mode === 'candidate' ? { ...sheets, formal: [], candidates: sheets.candidates.map(item => ({ ...item, adopted: false })) } : sheets;
  return <section data-testid="director-sheets" className="panel">
    <h2>导演分镜表隔离检查</h2>
    <button onClick={() => setMode('seven')}>模拟七页候选</button>
    <button onClick={() => setMode('candidate')}>模拟仅候选</button>
    <button onClick={() => setMode('empty')}>模拟空场次</button>
    <button onClick={() => setMode('old')}>模拟无图旧版分镜</button>
    <button onClick={() => setMode('other')}>模拟其他来源分镜</button>
    <PreviewContext.Provider value={setPreview}>
      <div className="episode-scene-content"><SceneDirectorSheets key={mode} sheets={data} storyboardVersion={version} revision={1} /></div>
      {preview && <Preview project="fixture-only" item={preview} revision={1} close={() => setPreview(null)} />}
    </PreviewContext.Provider>
  </section>;
}
