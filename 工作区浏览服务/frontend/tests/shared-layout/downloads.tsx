import { DownloadButton } from '../../src/components/DownloadButton';
import { DownloadControl } from '../../src/components/DownloadControl';
import { FileActions } from '../../src/components/FileActions';

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
  </section>;
}
