import { useContext } from 'react';
import type { RecordData } from '../api';
import { PreviewContext, Rich } from '../components';

export function AssetMediaCard({ title, items, revision, formal = false }: { title: string; items: RecordData[]; revision: number; formal?: boolean }) {
  const preview = useContext(PreviewContext);
  return <article className="asset-media-card">
    <h3>{title}（{items.length}）</h3>
    {items.map((item, index) => {
      const recordLink = item.recordUrl ? <a href={item.recordUrl} onClick={event => {
        event.preventDefault();
        preview({ kind: 'markdown', name: item.generation || '生成记录', key: decodeURIComponent(item.recordUrl.split('/files/')[1]), url: item.recordUrl });
      }}>{formal ? '生成记录' : item.generation}</a> : null;
      return <div className="asset-media-item" key={item.media?.key || item.generation || index}>
      {item.media ? <button className="cover" onClick={() => preview(item.media)}><img className="reference" loading="lazy" src={item.media.url + `?v=${revision}`} alt={item.media.name} /></button> : <p className="muted">已登记，图片文件缺失。</p>}
      {formal && item.version && <p className="asset-media-field"><span className="field-label">采用版本</span>{item.version.match(/v\d+(?:\.\d+)*/i)?.[0] || '未记录'}</p>}
      {Object.entries(item).filter(([key, content]) => key.endsWith('Html') && !(formal && key === 'versionHtml') && typeof content === 'string' && content).map(([key, content]) => <div key={key} className="asset-media-html-field"><p className="field-label">{({ statusHtml: '状态', sourceHtml: '来源', fileCheckHtml: '文件核对', visionScopeHtml: '看图授权及范围', visionFindingsHtml: '授权查看的发现', userHtml: '用户决定', agentHtml: '历史初审', technicalHtml: '技术审查', contentHtml: '内容审查', contentFindingsHtml: '审查发现', versionHtml: '采用版本' } as Record<string, string>)[key] || key.replace('Html', '')}</p><Rich html={String(content)} /></div>)}
      {(formal ? ['scope'] : ['version', 'scope', 'retentionPurpose', 'pendingLabel', 'userState']).map(key => item[key] && <p key={key} className={`asset-media-field${key === 'scope' ? ' asset-media-scope' : ''}`}><span className="field-label">{({ version: '版本', scope: '适用范围', retentionPurpose: '留存用途', pendingLabel: '留存状态', userState: '用户决定' } as Record<string, string>)[key]}</span>{item[key]}</p>)}
      {!formal && item.generation && <p className="asset-media-field"><span className="field-label">生成记录</span>{recordLink || item.generation}</p>}
      {formal && recordLink && <div className="asset-media-footer">{recordLink}</div>}
    </div>;
    })}
  </article>;
}
