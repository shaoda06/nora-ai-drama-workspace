import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Preview, PreviewContext } from '../src/components';
import type { FileItem } from '../src/api';
import { AssetMediaCard } from '../src/components/AssetMediaCard';
import { FileActions } from '../src/components/FileActions';
import { Notifications } from '../src/components/Notifications';
import { TabSelect } from '../src/components/TabSelect';
import '../src/style.css';
import.meta.glob('../src/**/*.css', { eager: true });

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
const images = [['人物示例', 'landscape'], ['场景示例', 'portrait'], ['道具示例', 'square'], ['封面示例', 'wide']];
function Fixture() {
  const [preview, setPreview] = useState<FileItem | null>(null);
  const [selected, setSelected] = useState('one');
  return <PreviewContext.Provider value={setPreview}><main>
    <h1>公共菜单与图片预览检查</h1>
    <div className="toolbar">
      <TabSelect size="small" label="候选选择" selected={selected} onChange={setSelected} items={[{ value: 'one', label: '候选一', badge: '已采用' }, { value: 'two', label: '候选二' }]} />
      <TabSelect label="短菜单" selected="" onChange={() => {}} items={[{ value: 'one', label: '一' }, { value: 'two', label: '二' }]} />
      <TabSelect label="长内容菜单" selected="" onChange={() => {}} items={[{ value: 'one', label: '这是一条需要自然展开而不固定最大宽度的较长选项名称' }]} />
      <TabSelect iconOnly label="纯图标菜单" selected="" onChange={() => {}} items={[{ value: 'one', label: '项目切换示例名称' }]} />
      <output aria-label="候选值">{selected}</output>
    </div>
    <div className="asset-media-grid">{images.map(([name, file]) => <AssetMediaCard key={file} title={name} revision={1} formal item={{ width: 1, height: 2, ratio: '1:2', media: { kind: 'image', name, key: file + '.svg', url: '/fixture/' + file + '.svg' } }} />)}</div>
    <section aria-label="原文件操作默认行为"><FileActions url="/fixture/readme.txt" /></section>
    <button onClick={() => setPreview({ kind: 'video', name: '视频示例', url: '/component-samples/video.webm' })}>视频预览</button>
    <button onClick={() => setPreview({ kind: 'audio', name: '音频示例', url: '/component-samples/tone.wav' })}>音频预览</button>
    <button onClick={() => setPreview({ kind: 'text', name: '文档示例', url: '/fixture/readme.txt', doc: { html: '<p>只读示例正文</p>' } })}>文档预览</button>
    {preview && <Preview project="fixture-only" item={preview} revision={1} close={() => setPreview(null)} />}
  </main></PreviewContext.Provider>;
}
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><Notifications><Fixture /></Notifications></QueryClientProvider>);
