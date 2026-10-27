import { DownloadButton } from '../../src/components/DownloadButton';
import { DownloadControl } from '../../src/components/DownloadControl';
import { FileActions } from '../../src/components/FileActions';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SceneDownloads } from '../../src/components/SceneDownloads';

const downloadClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
downloadClient.setQueryData(['episode-downloads', 'fixture-only', '片头', 'C002', 0],
  Object.fromEntries(['后处理', '二采', '一采'].map(stage => [stage, {
    videos: { count: stage === '后处理' ? 1 : 0,
      url: stage === '后处理' ? '/component-samples/native-pack?scene=C002' : null, files: [] },
    director: { count: 0, url: null, files: [] }, canvas: { count: 0, url: null, files: [] },
  }])));

export function DownloadsFixture() {
  return <section data-testid="downloads" className="panel">
    <h2>下载组件检查</h2>
    <div className="breadcrumbs"><div className="breadcrumb-actions"><DownloadButton url={null}
      file={{ text: '本地下载检查', name: 'download-local.md', type: 'text/markdown;charset=utf-8' }} label="下载检查" title="本地导出" /></div></div>
    <div className="workflow-downloads"><DownloadControl label="下载检查" href="/component-samples/image.svg" />
      <DownloadControl label="下载 API 版" disabled /></div>
    <div className="prose"><FileActions url="/component-samples/image.svg?revision=7#chapter" downloadLabel="下载检查" /></div>
    <div style={{ maxWidth: 220 }}><DownloadControl label={'很长的下载文件名LongFilename'.repeat(6)} disabled /></div>
    <DownloadButton url="/component-samples/download-check.txt" label="打包检查" title="模拟资源" pack />
    <QueryClientProvider client={downloadClient}>
      <SceneDownloads project="fixture-only" episode="片头" scene="C002" revision={0} />
    </QueryClientProvider>
  </section>;
}
