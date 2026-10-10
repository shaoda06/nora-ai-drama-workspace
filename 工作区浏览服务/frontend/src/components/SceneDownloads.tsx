import './SceneDownloads.css';

export function SceneDownloads() {
  return <div className="stage-downloads" aria-label="资源下载">
    {['后处理', '二采', '一采'].map(stage => <section className="stage-download-section" key={stage} aria-label={stage + '资源下载'}>
      <h3>{stage}</h3>
      <section className="stage-download-group" aria-label={stage + '正式版视频下载'}>
        <h4>正式版视频下载</h4>
        <button type="button" className="stage-download-bundle">打包下载正式版视频</button>
      </section>
      <section className="stage-download-group" aria-label={stage + '导演包下载'}>
        <h4>导演包下载</h4>
        <div className="stage-download-actions">
          <button type="button">下载导演包</button>
          <button type="button">下载画布</button>
        </div>
      </section>
    </section>)}
  </div>;
}
