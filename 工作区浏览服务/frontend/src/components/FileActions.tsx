import './FileActions.css';

export function Original({ url, label = '原文件' }: { url?: string; label?: string }) {
  return url ? <a href={url} target="_blank" rel="noopener noreferrer">{label} ↗</a> : null;
}

export function FileActions({ url, downloadOnly = false }: { url?: string; downloadOnly?: boolean }) {
  if (!url) return null;
  const download = new URL(url, window.location.href);
  download.hash = '';
  download.searchParams.set('download', 'true');
  return <span className="file-action-links">
    {!downloadOnly && <Original url={url} label="查看" />}
    <a href={download.href} download>下载</a>
  </span>;
}
