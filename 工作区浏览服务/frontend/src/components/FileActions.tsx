import './FileActions.css';

export function Original({ url, label = '原文件' }: { url?: string; label?: string }) {
  return url ? <a href={url} target="_blank" rel="noopener noreferrer">{label} ↗</a> : null;
}

export function FileActions({ url, downloadOnly = false, centered = false, viewLabel = '查看', downloadLabel = '下载' }: { url?: string; downloadOnly?: boolean; centered?: boolean; viewLabel?: string; downloadLabel?: string }) {
  if (!url) return null;
  const download = new URL(url, window.location.href);
  download.hash = '';
  download.searchParams.set('download', 'true');
  return <span className={`file-action-links${centered ? ' file-action-links-center' : ''}`}>
    {!downloadOnly && <Original url={url} label={viewLabel} />}
    <a href={download.href} download>{downloadLabel}</a>
  </span>;
}
