import './CoverLibrary.css';
import { useContext, useState } from 'react';
import type { RecordData } from '../api';
import { Groups, Original, PreviewContext, Rich } from '../components';

export function CoverLibrary({ value, revision }: { value: RecordData; revision: number }) {
  const preview = useContext(PreviewContext);
  const [historyOpen, setHistoryOpen] = useState(false);
  return <>
    <div className="toolbar"><h2>当前采用封面</h2><RecordLinks items={[value.index, value.record]} /></div>
    <div className="cover-library-grid">{value.items.map((item: RecordData) => {
      const image = item.media || item.original;
      return <article className="cover-library-card" key={item.name}>
        {image ? <button className="cover-library-art" aria-label={`打开${item.name}`} onClick={() => preview({ kind: 'image', name: item.name, key: image.key, url: image.url })}>
          <img src={image.url + `?v=${revision}`} alt={item.name} loading="lazy" />
        </button> : <p className="muted">成品与采用原图尚未就绪。</p>}
        <div className="cover-library-body"><h3>{item.name}</h3><Rich html={item.statusHtml} />
          <dl className="cover-library-facts">
            <dt>用途</dt><dd>{item.scope} · {item.layout}</dd>
            <dt>采用版本</dt><dd>{item.version}</dd>
            <dt>目标规格</dt><dd>{item.targetSize} · {item.targetRatio}</dd>
            <dt>成品实测</dt><dd>{item.media ? `${item.media.width}×${item.media.height} · ${item.media.ratio}` : '待处理'}</dd>
            <dt>原图实测</dt><dd>{item.original ? `${item.original.width}×${item.original.height} · ${item.original.ratio}` : '尚未登记'}</dd>
          </dl>
          <div className="cover-library-links"><Original url={item.media?.url} label="成品原文件" />{item.media && <a href={item.media.url + '?download=true'} download>下载成品</a>}<Original url={item.original?.url} label="采用原图" />{item.original && <a href={item.original.url + '?download=true'} download>下载原图</a>}</div>
          <RecordLinks items={[item.review, item.processing]} />
        </div>
      </article>;
    })}</div>
    {!value.items.length && <p className="muted">尚无已登记的采用封面，可先查看候选和制作记录。</p>}
    <details className="cover-library-history" onToggle={event => setHistoryOpen(event.currentTarget.open)}>
      <summary>候选与历史（{value.candidates.length}）</summary>
      {historyOpen && <div className="cover-library-grid">{value.candidates.map((item: RecordData) => <article className="cover-library-card" key={item.media.key}>
        <button className="cover-library-art" aria-label={`打开候选${item.name}`} onClick={() => preview({ kind: 'image', name: item.name, key: item.media.key, url: item.media.url })}>
          <img loading="lazy" src={item.media.url + `?v=${revision}`} alt={item.name} />
        </button><div className="cover-library-body"><h3>{item.name}</h3>
          <p>{item.generation} · {item.status}</p><p className="muted">{item.media.width}×{item.media.height} · {item.media.ratio}</p>
          <Original url={item.media.url} label="候选原图" /><RecordLinks items={[item.record]} />
        </div>
      </article>)}</div>}
    </details>
    <Groups groups={value.groups} />
  </>;
}

function RecordLinks({ items }: { items: (RecordData | null)[] }) {
  const preview = useContext(PreviewContext);
  return <div className="cover-library-records">{items.filter(Boolean).map(item => <button className="link" key={item!.url} onClick={() => preview({ kind: item!.key.endsWith('.md') ? 'markdown' : 'text', name: item!.name, key: item!.key + new URL(item!.url, window.location.origin).hash, url: item!.url })}>{item!.name}</button>)}</div>;
}
