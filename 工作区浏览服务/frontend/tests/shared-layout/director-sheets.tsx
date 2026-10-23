import { useState } from 'react';
import type { DirectorSheets, FileItem } from '../../src/api';
import { Preview, PreviewContext } from '../../src/components';
import { SceneDirectorSheets } from '../../src/components/SceneDirectorSheets';

const image = (page: number, version = '') => ({
  kind: 'image', name: `EP001-C001-手绘导演分镜表${version ? '-' + version : ''}-第${String(page).padStart(2, '0')}页.png`,
  key: `${version || 'formal'}-${page}`, url: '/component-samples/image.svg', page, version,
});
const sheets: DirectorSheets = { formal: [image(1), image(2), image(3)],
  candidates: [image(1, 'v01'), image(1, 'v02'), image(2, 'v02')], record: null };

export function DirectorSheetsFixture() {
  const [mode, setMode] = useState('formal');
  const [preview, setPreview] = useState<FileItem | null>(null);
  return <section data-testid="director-sheets" className="panel">
    <h2>导演分镜表隔离检查</h2>
    <button onClick={() => setMode('candidate')}>模拟仅候选</button>
    <button onClick={() => setMode('empty')}>模拟空场次</button>
    <PreviewContext.Provider value={setPreview}>
      <SceneDirectorSheets key={mode} sheets={mode === 'empty' ? undefined : mode === 'candidate' ? { ...sheets, formal: [] } : sheets} revision={1} />
      {preview && <Preview project="fixture-only" item={preview} revision={1} close={() => setPreview(null)} />}
    </PreviewContext.Provider>
  </section>;
}
