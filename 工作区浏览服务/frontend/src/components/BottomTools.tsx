import { useEffect, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import './BottomTools.css';

/** Reserve the actual space used by notifications, including multiline messages. */
export function BottomTools({ children }: { children: ReactNode }) {
  const [noticeSpace, setNoticeSpace] = useState(0);
  useEffect(() => {
    const measure = () => {
      const footer = document.querySelector('.site-footer')?.getBoundingClientRect();
      const floor = (footer?.top ?? window.innerHeight) - 16;
      const notices = document.querySelectorAll<HTMLElement>('.floating-messages:popover-open');
      setNoticeSpace(Math.max(0, ...Array.from(notices, element => {
        const rect = element.getBoundingClientRect();
        return rect.width && rect.height ? floor - rect.top + 12 : 0;
      })));
    };
    const resize = new ResizeObserver(measure);
    const observe = () => {
      resize.disconnect();
      document.querySelectorAll('.floating-messages, .site-footer').forEach(element => resize.observe(element));
      measure();
    };
    const changes = new MutationObserver(observe);
    changes.observe(document.body, { childList: true, subtree: true });
    document.addEventListener('toggle', measure, true);
    window.addEventListener('resize', measure);
    observe();
    return () => {
      changes.disconnect(); resize.disconnect();
      document.removeEventListener('toggle', measure, true);
      window.removeEventListener('resize', measure);
    };
  }, []);
  return <div className="app-bottom-tools" style={{ '--bottom-notice-space': `${noticeSpace}px` } as CSSProperties}>{children}</div>;
}
