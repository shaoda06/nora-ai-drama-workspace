import { useContext } from 'react';
import type { FileItem, RecordData } from '../api';
import { FileTree, Original, PreviewContext, Rich } from '../components';

export function AssetMediaCard({ title, items, revision }: { title: string; items: RecordData[]; revision: number }) {
  const preview = useContext(PreviewContext);
  return <article className="asset-media-card">
    <h3>{title}（{items.length}）</h3>
    {items.map((item, index) => <div className="asset-media-item" key={item.media?.key || item.generation || index}>
      {item.media ? <button className="cover" onClick={() => preview(item.media)}><img className="reference" loading="lazy" src={item.media.url + `?v=${revision}`} alt={item.media.name} /></button> : <p className="muted">已登记，图片文件缺失。</p>}
      {Object.entries(item).filter(([key, content]) => key.endsWith('Html') && typeof content === 'string' && content).map(([key, content]) => <div key={key} className={key === 'statusHtml' ? 'asset-media-status' : undefined}><p className="field-label">{({ statusHtml: '状态', sourceHtml: '来源', fileCheckHtml: '文件核对', visionScopeHtml: '看图授权及范围', visionFindingsHtml: '授权查看的发现', userHtml: '用户决定', agentHtml: '历史初审', technicalHtml: '技术审查', contentHtml: '内容审查', contentFindingsHtml: '审查发现', versionHtml: '采用版本' } as Record<string, string>)[key] || key.replace('Html', '')}</p><Rich html={String(content)} /></div>)}
      {['version', 'scope', 'retentionPurpose', 'pendingLabel', 'userState', 'generation'].map(key => item[key] && <p key={key}>{({ version: '版本', scope: '适用范围', retentionPurpose: '留存用途', pendingLabel: '留存状态', userState: '用户决定', generation: '生成记录' } as Record<string, string>)[key]}：{item[key]}</p>)}
      <Original url={item.recordUrl} label="生成记录" /> {item.reviews?.map((review: FileItem) => <FileTree key={review.key} showOriginal={false} items={[{ ...review, kind: 'markdown' }]} />)}
    </div>)}
  </article>;
}
