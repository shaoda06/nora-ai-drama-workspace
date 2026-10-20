import { useRef, useState } from 'react';

export async function copyText(text: string, buffer: HTMLTextAreaElement) {
  if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
  else {
    buffer.select();
    if (!document.execCommand('copy')) throw new Error('当前浏览器不支持自动复制');
  }
}

export function CopyButton({ text, label, onMessage }: { text: string; label: string; onMessage?: (message: string) => void }) {
  const [message, setMessage] = useState('');
  const buffer = useRef<HTMLTextAreaElement>(null);
  return <><button onClick={async event => {
    const button = event.currentTarget;
    try { await copyText(text, buffer.current!); setMessage('已复制'); onMessage?.('已复制'); }
    catch (error) {
      const failure = `复制失败：${String(error)}；可选中下方文本复制。`;
      setMessage(failure);
      onMessage?.(failure);
    }
    button.focus();
  }}>{label}</button><textarea ref={buffer} className="clipboard-buffer" aria-hidden="true" tabIndex={-1} readOnly value={text} />{!onMessage && message && <p role="status" className="notice">{message}</p>}{message.includes('选中') && <textarea aria-label="手动复制内容" readOnly value={text} onFocus={event => event.currentTarget.select()} />}</>;
}
