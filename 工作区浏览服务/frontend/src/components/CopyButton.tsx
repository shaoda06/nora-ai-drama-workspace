import { useState } from 'react';

export function CopyButton({ text, label }: { text: string; label: string }) {
  const [message, setMessage] = useState('');
  return <><button onClick={async () => {
    if (navigator.clipboard && window.isSecureContext) {
      try { await navigator.clipboard.writeText(text); setMessage('已复制'); }
      catch (error) { setMessage(`复制失败：${String(error)}；可选中下方文本复制。`); }
    } else setMessage('当前局域网地址不支持自动复制，请选中下方文本复制。');
  }}>{label}</button>{message && <p role="status" className="notice">{message}</p>}{message.includes('选中') && <textarea aria-label="手动复制内容" readOnly value={text} onFocus={event => event.currentTarget.select()} />}</>;
}
