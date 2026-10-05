import { useRef, useState } from 'react';

export function CopyButton({ text, label }: { text: string; label: string }) {
  const [message, setMessage] = useState('');
  const buffer = useRef<HTMLTextAreaElement>(null);
  return <><button onClick={async event => {
    if (navigator.clipboard && window.isSecureContext) {
      try { await navigator.clipboard.writeText(text); setMessage('已复制'); }
      catch (error) { setMessage(`复制失败：${String(error)}；可选中下方文本复制。`); }
    } else {
      buffer.current!.select();
      const copied = document.execCommand('copy');
      event.currentTarget.focus();
      setMessage(copied ? '已复制' : '当前浏览器不支持自动复制，请选中下方文本复制。');
    }
  }}>{label}</button><textarea ref={buffer} className="clipboard-buffer" aria-hidden="true" tabIndex={-1} readOnly value={text} />{message && <p role="status" className="notice">{message}</p>}{message.includes('选中') && <textarea aria-label="手动复制内容" readOnly value={text} onFocus={event => event.currentTarget.select()} />}</>;
}
