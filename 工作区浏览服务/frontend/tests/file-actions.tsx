import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Document, FileTree, Preview, PreviewContext } from '../src/components';
import type { FileItem } from '../src/api';
import { AssetMedia } from '../src/components/AssetMedia';
import { CoverLibrary } from '../src/components/CoverLibrary';
import '../src/style.css';

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
const files = new URLSearchParams(window.location.search).get('files') || '';
const media = (name: string) => ({ kind: 'image', name: name + '.png', key: name + '.png', url: files + '/fixture/' + name + '.png' });
function Demo() {
  const [preview, setPreview] = useState<FileItem | null>(null);
  return <PreviewContext.Provider value={setPreview}><main>
    <h1>共用文件操作测试</h1>
    {['人物', '场景', '道具'].map(name => <section aria-label={name} key={name}>
      <h2>{name}</h2><AssetMedia formal revision={1} items={[{ media: media(name), type: name + '参考图', version: 'v01' }]} />
      <AssetMedia revision={1} items={[{ media: media(name + '候选'), type: name + '候选', version: 'v02' }]} />
      <FileTree items={[{ kind: 'markdown', name: name + '-资料卡.md', key: name + '.md', url: files + '/fixture/' + name + '.md?revision=7#章节' }]} />
    </section>)}
    <section aria-label="正文"><Document value={{ html: '<h2>资料卡正文</h2>', url: '/fixture/正文.md' }} /></section>
    <section aria-label="封面"><CoverLibrary revision={1} value={{ items: [{ name: '封面', setName: '测试套组', platforms: ['通用'], media: { ...media('成品'), width: 4, height: 3, ratio: '4:3' }, original: { ...media('原图'), width: 8, height: 6, ratio: '4:3' }, targetSize: '4×3', targetRatio: '4:3', scope: '通用', layout: '横版', version: 'v01' }], candidates: [], groups: [] }} /></section>
    {preview && <Preview key={preview.key} project="文件测试" item={preview} revision={1} close={() => setPreview(null)} />}
  </main></PreviewContext.Provider>;
}
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><Demo /></QueryClientProvider>);
