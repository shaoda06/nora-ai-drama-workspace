import { cloneElement, useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import type { HTMLAttributes, ReactElement } from 'react';
import { createPortal } from 'react-dom';
import './PointerTooltip.css';

/** A layout-neutral tooltip for a single focusable trigger. */
export function PointerTooltip({ text, children }: {
  text: string; children: ReactElement<HTMLAttributes<HTMLElement>>;
}) {
  const id = useId();
  const tooltip = useRef<HTMLDivElement>(null);
  const [anchor, setAnchor] = useState<{ x: number; y: number } | null>(null);
  const open = anchor !== null;

  useLayoutEffect(() => {
    if (!anchor || !tooltip.current) return;
    const element = tooltip.current;
    const { width, height } = element.getBoundingClientRect();
    const gap = 12, margin = 8;
    const left = Math.max(margin, Math.min(anchor.x + gap, window.innerWidth - width - margin));
    // Prefer above the pointer; use below when the top edge leaves no room.
    const preferredTop = anchor.y - height - gap;
    const top = Math.max(margin, Math.min(preferredTop >= margin ? preferredTop : anchor.y + gap, window.innerHeight - height - margin));
    element.style.left = `${left}px`;
    element.style.top = `${top}px`;
    element.style.visibility = 'visible';
  }, [anchor, text]);

  useEffect(() => {
    if (!open) return;
    const hide = () => setAnchor(null);
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') hide(); };
    window.addEventListener('scroll', hide, { capture: true, passive: true });
    window.addEventListener('resize', hide);
    window.addEventListener('blur', hide);
    window.addEventListener('keydown', escape);
    return () => {
      window.removeEventListener('scroll', hide, true);
      window.removeEventListener('resize', hide);
      window.removeEventListener('blur', hide);
      window.removeEventListener('keydown', escape);
    };
  }, [open]);

  const description = [children.props['aria-describedby'], open ? id : undefined].filter(Boolean).join(' ') || undefined;
  return <span className="pointer-tooltip-trigger"
    onPointerEnter={event => { if (event.pointerType !== 'touch') setAnchor({ x: event.clientX, y: event.clientY }); }}
    onPointerMove={event => { if (event.pointerType !== 'touch') setAnchor({ x: event.clientX, y: event.clientY }); }}
    onPointerLeave={() => setAnchor(null)}
    onFocus={event => { const rect = event.target.getBoundingClientRect(); setAnchor({ x: rect.right, y: rect.top }); }}
    onBlur={() => setAnchor(null)}>
    {cloneElement(children, { 'aria-describedby': description })}
    {open ? createPortal(<div ref={tooltip} id={id} role="tooltip" className="pointer-tooltip">{text}</div>, document.body) : null}
  </span>;
}
