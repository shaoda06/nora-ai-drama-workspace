import { useRef, useState } from 'react';
import { SegmentVideo } from '../../src/components/SegmentVideo';
import type { SegmentVideoHandle } from '../../src/components/SegmentVideo';

function RevisionPlayer({ product }: { product: boolean }) {
  const [revision, setRevision] = useState('old');
  const [observed, setObserved] = useState('');
  const player = useRef<SegmentVideoHandle>(null);
  return <section data-testid={product ? 'product-revision' : 'single-revision'}>
    <button onClick={() => setRevision('new')}>更新测试文件</button>
    <output aria-label="已加载审阅版本">{observed}</output>
    <SegmentVideo current={{ key: 'review-fixture', stage: '后处理', run: 'R001', candidateNumber: 1, approved: false,
      url: '/component-samples/video.webm?revision=' + revision, fileRevision: 'media-' + revision,
      reviewFileRevision: product ? 'source-' + revision : undefined,
      deliveryStatus: '已取回', taskStatus: '已完成', checkedAt: '' }}
      playerRef={player} onTimeChange={() => {}} onFileRevision={setObserved} wide={false}
      onToggleWide={() => {}} continuousControl={null} retainSource={() => () => {}} />
  </section>;
}
export function ReviewRevisionFixture() {
  return <><RevisionPlayer product={false} /><RevisionPlayer product /></>;
}
