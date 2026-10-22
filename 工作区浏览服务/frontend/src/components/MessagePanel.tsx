import type { ReactNode } from 'react';
import { PointerTooltip } from './PointerTooltip';
import './MessagePanel.css';

export type PanelMessage = {
  id: string;
  content: ReactNode;
  tone?: 'info' | 'warning' | 'error';
  detail?: string;
  actions?: ReactNode;
};

export function MessagePanel({ messages, label = '提示信息' }: {
  messages: (PanelMessage | false | null | undefined)[];
  label?: string;
}) {
  const visible = messages.filter((message): message is PanelMessage => !!message);
  if (!visible.length) return null;
  return <section className="message-panel" aria-label={label}>
    {visible.map(message => <div key={message.id} className="message-panel-row" data-tone={message.tone || 'info'}
      data-message={message.id} role={message.tone === 'error' ? 'alert' : 'status'}>
      {message.content && <PointerTooltip text={message.detail}><div className="message-panel-text">{message.content}</div></PointerTooltip>}
      {message.actions && <div className="message-panel-actions">{message.actions}</div>}
    </div>)}
  </section>;
}
