import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';

type Notification = { text: string; tone: 'info' | 'error' };
const NotificationContext = createContext<(text: string, tone?: Notification['tone']) => void>(() => {});
export const useNotify = () => useContext(NotificationContext);

export function Notifications({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState<Notification | null>(null);
  const popup = useRef<HTMLElement>(null);
  const notify = useCallback((text: string, tone: Notification['tone'] = 'info') => setMessage({ text, tone }), []);
  useEffect(() => {
    if (!message) return;
    popup.current!.hidePopover();
    popup.current!.showPopover();
    const timer = window.setTimeout(() => setMessage(null), 3000);
    return () => window.clearTimeout(timer);
  }, [message]);
  return <NotificationContext.Provider value={notify}>{children}{message && createPortal(
    <aside ref={popup} popover="manual" className={'notification notification-' + message.tone} role={message.tone === 'error' ? 'alert' : 'status'}>
      <span>{message.text}</span><button aria-label="关闭通知" onClick={() => setMessage(null)}>×</button>
    </aside>, document.querySelector('dialog[open]') || document.body
  )}</NotificationContext.Provider>;
}
