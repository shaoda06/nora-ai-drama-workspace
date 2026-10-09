import type { FileItem } from '../api';

export function SceneDownloads({ files }: { files: FileItem[] }) {
  const packs = files.filter(item => item.name.endsWith('-导演包.mmxpack.zip'));
  return <section className="scene-downloads" aria-label="本场导演包下载">
    <h3>导演包下载</h3>
    {!packs.length ? <p className="muted">本场暂无可下载的导演包。</p> : <>
      <p className="muted">先打开配套画布，再在导演台导入整个导演包；修改时另存副本。</p>
      <div className="director-pack-list">{packs.map(pack => {
        const title = pack.name.slice(0, -'-导演包.mmxpack.zip'.length);
        const canvas = files.find(item => item.name === title + '.workflow.json');
        return <article className="director-pack-card" key={pack.key}>
          <h4>{title}</h4>
          <div className="director-pack-actions">
            <a href={pack.url} download={pack.name}>下载导演包</a>
            {canvas ? <a href={canvas.url} download={canvas.name}>下载配套画布</a> : <span className="muted">缺少配套画布</span>}
          </div>
        </article>;
      })}</div>
    </>}
  </section>;
}
