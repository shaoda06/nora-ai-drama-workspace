import { useState } from 'react';
import './SceneDownloads.css';

type Request = { time: string; message: string; failed: boolean };

export function DownloadButton({ url, label, title, pack = false }: {
  url: string | null; label: string; title: string; pack?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [requests, setRequests] = useState<Request[]>([]);

  async function download() {
    const index = requests.length;
    const update = (message: string, failed = false) => setRequests(previous => previous.map((request, i) =>
      i === index ? { ...request, message, failed } : request));
    setBusy(true);
    setRequests(previous => [...previous, {
      time: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
      message: pack ? '正在打包视频，请稍候…' : '正在准备文件，请稍候…', failed: false,
    }]);
    try {
      const response = await fetch(url!);
      if (!response.ok) {
        const message = response.headers.get('Content-Type')?.includes('application/json')
          ? (await response.json()).detail : await response.text();
        throw new Error(message || `下载失败（${response.status}）`);
      }
      const disposition = response.headers.get('Content-Disposition') || '';
      const encoded = disposition.match(/filename\*=utf-8''([^;]+)/i);
      const plain = disposition.match(/filename="([^"]+)"/i);
      if (!encoded && !plain) throw new Error('下载响应缺少文件名，请重试。');
      const filename = encoded ? decodeURIComponent(encoded[1]) : plain![1];
      update('正在接收文件，请稍候…');
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = objectUrl;
      link.download = filename;
      document.body.append(link);
      link.click();
      link.remove();
      // The click starts the browser's save before releasing the in-page file.
      setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
      update('文件已准备，已交给浏览器保存，请查看下载列表。');
    } catch (error) {
      update(`下载失败：${error instanceof Error ? error.message : String(error)}`, true);
    } finally {
      setBusy(false);
    }
  }

  return <div className="stage-download-row">
    <button type="button" className="stage-download-link" disabled={!url || busy} aria-busy={busy}
      title={title} onClick={download}>
      {busy && <span className="loading-spinner download-spinner" aria-hidden="true" />}
      {busy ? (pack ? '正在打包…' : '正在准备…') : label}
    </button>
    {requests.map((request, index) => <span className={`stage-download-message ${request.failed ? 'download-failed' : 'muted'}`}
      role={request.failed ? 'alert' : 'status'} key={index}>{request.time} {request.message}</span>)}
  </div>;
}
