import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';

type Notification = { text: ReactNode; tone: 'info' | 'error'; duration: number };
const NotificationContext = createContext<(text: ReactNode, tone?: Notification['tone'], duration?: number) => () => void>(() => () => {});
export const useNotify = () => useContext(NotificationContext);

export function Notifications({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<Notification | null>(null);
  const popup = useRef<HTMLElement>(null);
  const notify = useCallback((text: ReactNode, tone: Notification['tone'] = 'info', duration = 3000) => {
    const next = { text, tone, duration };
    setMessage(next);
    return () => setMessage(current => current === next ? null : current);
  }, []);
  useEffect(() => {
    if (!message) return;
    popup.current!.hidePopover();
    popup.current!.showPopover();
    if (!message.duration) return;
    const timer = window.setTimeout(() => setMessage(null), message.duration);
    return () => window.clearTimeout(timer);
  }, [message]);
  return <NotificationContext.Provider value={notify}>{children}{message && createPortal(
    <aside ref={popup} popover="manual" className={'notification notification-' + message.tone} role={message.tone === 'error' ? 'alert' : 'status'}>
      <span>{message.text}</span><button aria-label="关闭通知" onClick={() => setMessage(null)}>×</button>
    </aside>, document.querySelector('dialog[open]') || document.body
  )}</NotificationContext.Provider>;
}
