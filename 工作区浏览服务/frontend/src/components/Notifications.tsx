import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import './Notifications.css';

type Notification = { text: ReactNode; tone: 'info' | 'error'; expiresAt: number | null; dismissible: boolean };
type Message = Notification & { id: string };
const NotificationContext = createContext<(text: ReactNode, tone?: Notification['tone'], duration?: number) => () => void>(() => () => {});
const MessageContext = createContext<{
  put: (message: Message) => void;
  remove: (id: string) => void;
}>(null!);
export const useNotify = () => useContext(NotificationContext);

/** Persistent messages share the host, but keep their source component's lifetime and actions. */
export function FloatingMessage({ children, tone = 'info' }: { children: ReactNode; tone?: Notification['tone'] }) {
  const id = useId();
  const { put, remove } = useContext(MessageContext);
  useEffect(() => {
    put({ id, text: children, tone, expiresAt: null, dismissible: false });
  }, [id, children, tone, put]);
  useEffect(() => () => remove(id), [id, remove]);
  return null;
}

function MessageCard({ message, remove }: { message: Message; remove: (id: string) => void }) {
  const { id, expiresAt } = message;
  useEffect(() => {
    if (expiresAt === null) return;
    const timer = window.setTimeout(() => remove(id), Math.max(0, expiresAt - Date.now()));
    return () => window.clearTimeout(timer);
  }, [id, expiresAt, remove]);
  return <div className={'floating-message floating-message-' + message.tone} role={message.tone === 'error' ? 'alert' : 'status'}>
    <div className="floating-message-content">{message.text}</div>
    {message.dismissible && <button className="floating-message-close" aria-label="关闭通知" onClick={() => remove(id)}>×</button>}
  </div>;
}

export function Notifications({ children }: { children: ReactNode }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [target, setTarget] = useState<Element>(document.body);
  const nextId = useRef(0);
  const popup = useRef<HTMLElement>(null);
  const remove = useCallback((id: string) => setMessages(current => current.filter(message => message.id !== id)), []);
  const put = useCallback((message: Message) => setMessages(current => {
    const index = current.findIndex(item => item.id === message.id);
    return index < 0 ? [...current, message] : current.map(item => item.id === message.id ? message : item);
  }), []);
  const registry = useMemo(() => ({ put, remove }), [put, remove]);
  const notify = useCallback((text: ReactNode, tone: Notification['tone'] = 'info', duration = 3000) => {
    const id = `notification-${nextId.current++}`;
    put({ id, text, tone, expiresAt: duration ? Date.now() + duration : null, dismissible: true });
    return () => remove(id);
  }, [put, remove]);
  useEffect(() => {
    const locate = () => {
      const dialogs = document.querySelectorAll('dialog[open]');
      setTarget(dialogs.item(dialogs.length - 1) || document.body);
    };
    const observer = new MutationObserver(locate);
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['open'] });
    locate();
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (messages.length && !popup.current!.matches(':popover-open')) popup.current!.showPopover();
  }, [messages.length, target]);
  return <NotificationContext.Provider value={notify}><MessageContext.Provider value={registry}>{children}{messages.length > 0 && createPortal(
    <aside ref={popup} popover="manual" className="floating-messages" aria-label="消息通知">
      {messages.map(message => <MessageCard key={message.id} message={message} remove={remove} />)}
    </aside>, target
  )}</MessageContext.Provider></NotificationContext.Provider>;
}
