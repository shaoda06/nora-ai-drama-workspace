import { PointerTooltip } from './PointerTooltip';
import { useContext, useState } from 'react';
import type { RecordData } from '../api';
import { PreviewContext, Rich } from '../components';
import { FileActions } from './FileActions';

export function AssetMediaCard({ title, item, revision, formal = false, onDetails }: { title: string; item: RecordData; revision: number; formal?: boolean; onDetails?: () => void }) {
  const preview = useContext(PreviewContext);
  const [dimensions, setDimensions] = useState('');
  const recordLink = item.recordUrl ? <a href={item.recordUrl} onClick={event => {
        event.preventDefault();
        preview({ kind: 'markdown', name: item.generation || '生成记录', key: decodeURIComponent(item.recordUrl.split('/files/')[1]), url: item.recordUrl });
      }}>{formal ? '生成记录' : item.generation}</a> : null;
  const version = formal ? item.version?.match(/v\d+(?:\.\d+)*/i)?.[0] : item.version || item.media?.key.match(/(?:候选|草稿)-(v\d+(?:\.\d+)*)/i)?.[1];
  return <article className="asset-media-card">
    <PointerTooltip text={title}><h3 >{title}</h3></PointerTooltip>
    <div className="asset-media-item">
      {item.media ? <button className="cover" onClick={() => preview(item.media)}><img className="reference" loading="lazy" src={item.media.url + `?v=${revision}`} alt={item.media.name} onLoad={event => {
        const { naturalWidth: width, naturalHeight: height } = event.currentTarget;
        let divisor = width, remainder = height;
        while (remainder) [divisor, remainder] = [remainder, divisor % remainder];
        setDimensions(`${width} × ${height}（${width / divisor}:${height / divisor}）`);
      }} /></button> : <p className="muted">已登记，图片文件缺失。</p>}
      {item.media && <p className="asset-media-field"><span className="field-label">尺寸：</span>{dimensions || '读取中'}</p>}
      {item.media && !onDetails && <div className="asset-media-field file-entry-main"><span className="field-label">文件：</span><FileActions url={item.media.url} /></div>}
      {version ? <p className="asset-media-field"><span className="field-label">{formal ? '采用版本' : '版本'}：</span>{version}</p> : null}
      {Object.entries(item).filter(([key, content]) => key.endsWith('Html') && !['fileCheckHtml', 'visionScopeHtml', 'visionFindingsHtml'].includes(key) && (!formal || key === 'statusHtml') && typeof content === 'string' && content).map(([key, content]) => <div key={key} className="asset-media-html-field"><p className="field-label">{({ statusHtml: '状态', sourceHtml: '来源', userHtml: '用户决定', userReasonHtml: '原因与依据', agentHtml: '历史初审', technicalHtml: '技术审查', contentHtml: '内容审查', contentFindingsHtml: '审查发现', versionHtml: '采用版本' } as Record<string, string>)[key] || key.replace('Html', '')}：</p><Rich html={String(content)} /></div>)}
      {(formal ? ['scope'] : ['scope', 'retentionPurpose', 'pendingLabel', 'userState']).map(key => item[key] && <p key={key} className={`asset-media-field${key === 'scope' ? ' asset-media-scope' : ''}`}><span className="field-label">{({ scope: '适用范围', retentionPurpose: '留存用途', pendingLabel: '留存状态', userState: '用户决定' } as Record<string, string>)[key]}：</span>{item[key]}</p>)}
      {!formal && item.generation && <p className="asset-media-field"><span className="field-label">生成记录：</span>{recordLink || item.generation}</p>}
      {((formal && recordLink) || onDetails) && <div className="asset-media-footer">{formal && recordLink}{onDetails && <button onClick={onDetails}>查看详情</button>}</div>}
    </div>
  </article>;
}
