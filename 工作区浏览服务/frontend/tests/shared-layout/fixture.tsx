import { ReviewRevisionFixture } from './review-revision';
import { DownloadsFixture } from './downloads';
import { InputsFixture } from './inputs';
import { NavigationFixture } from './navigation';
import { FeedbackFixture } from './feedback';
import { DirectorSheetsFixture } from './director-sheets';
import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Notifications } from '../../src/components/Notifications';
import { ComponentShowcase } from '../../src/components/ComponentShowcase';
import { SegmentWorkspace } from '../../src/components/SegmentWorkspace';
import type { SegmentVideo } from '../../src/api';
import '../../src/style.css';
// Include page CSS too, so page-qualified leaks are exercised rather than omitted.
import.meta.glob('../../src/**/*.css', { eager: true });

const videos: SegmentVideo[] = [1, 2].map(candidateNumber => ({
  key: `fixture-${candidateNumber}`, stage: '一采', run: `R00${candidateNumber}`,
  candidateNumber, approved: candidateNumber === 1, url: '/component-samples/video.webm',
  products: candidateNumber === 2 ? [
    { id: 'final', label: '透明 MOV', default: true, key: 'fixture-final.mov', url: '/component-samples/video.webm?final=1', previewUrl: '/component-samples/video.webm?preview=1', fileRevision: 'final', previewRevision: 'preview', previewNote: '示例透明预览。' },
    { id: 'process', label: '绿底 MP4', default: false, key: 'fixture-process.mp4', url: '/component-samples/video.webm?process=1', fileRevision: 'process' },
  ] : undefined,
  fileRevision: 'fixture', deliveryStatus: '已取回', taskStatus: '已完成', checkedAt: '',
  context: { scriptHtml: '<p>自动检查模拟分镜</p>', shots: [], issues: [],
    prompts: { english: 'Fixture only.', chinese: '仅供自动检查。' }, references: { common: [], segment: [] } },
}));
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
function Fixture() {
  const [wide, setWide] = useState(false);
  const [continuous, setContinuous] = useState(false);
  const [ended, setEnded] = useState(0);
  const [selection, setSelection] = useState({ stage: '一采', key: videos[0].key });
  return <div className="workspace-with-tasks"><main className="project-page">
    <ReviewRevisionFixture />
    <DownloadsFixture />
    <FeedbackFixture />
    <DirectorSheetsFixture />
    <NavigationFixture />
    <InputsFixture />
    <section data-testid="showcase"><ComponentShowcase onImplementation={() => {}} /></section>
    <section data-testid="business" className="panel episode-detail"><div className="episode-scene-content">
      <SegmentWorkspace scope={{ project: 'fixture-only', episode: 'EP001', scene: 'C001' }}
        segment="P001" revision={0} items={videos} selection={selection} onSelectionChange={setSelection}
        tab="script" onTabChange={() => {}} notesExportControl={null}
        segmentNavigation={<span>P001</span>} autoPlay={false} onVideoEnded={() => setEnded(value => value + 1)} onVideoError={() => {}}
        cachedSources={{}} retainSource={() => () => {}} wideVideo={wide}
        onToggleWide={() => setWide(value => !value)} continuous={continuous}
        continuousControl={<label className="scene-continuous"><input type="checkbox" checked={continuous} onChange={event => setContinuous(event.target.checked)} />连续播放</label>} />
      <output aria-label="播放结束次数">{ended}</output>
    </div></section>
  </main></div>;
}
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><MemoryRouter><Notifications><Fixture /></Notifications></MemoryRouter></QueryClientProvider>);
