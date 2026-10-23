import type { RecordData } from '../api';
import { FileTree } from '../components';
import { AssetMediaCard } from './AssetMediaCard';

export function AccountLibrary({ value, revision }: { value: RecordData; revision: number }) {
  const records = [
    ...(value.index ? [value.index] : []),
    ...value.groups.map((group: RecordData) => ({ kind: 'group', ...group })),
  ];
  return <>
    <h2>当前采用</h2>
    <div className="asset-media-grid">{value.items.map((item: RecordData) =>
      <AssetMediaCard key={`${item.platform}/${item.purpose}`} title={item.name} item={item} revision={revision} formal />
    )}</div>
    {value.items.length === 0 ? <p className="muted">尚无已登记的采用头像或主页背景图，可在制作记录中查看现有资料。</p> : null}
    <FileTree items={[{ kind: 'group', name: '制作记录', children: records }]} />
    {value.issues.map((issue: string) => <p className="muted" key={issue}>{issue}</p>)}
  </>;
}
