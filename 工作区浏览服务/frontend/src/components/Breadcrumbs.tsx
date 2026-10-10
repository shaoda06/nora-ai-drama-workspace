import { createContext } from 'react';
import type { Ref } from 'react';

export const BreadcrumbActionsContext = createContext<HTMLDivElement | null>(null);

export function Breadcrumbs({ items, currentRef, actionsRef }: { items: { label: string; href?: string; onClick?: () => void }[]; currentRef?: Ref<HTMLSpanElement>; actionsRef?: Ref<HTMLDivElement> }) {
  return <nav className="breadcrumbs" aria-label="当前位置"><div>{items.map((item, index) =>
    <span key={index}>{index > 0 && <span className="breadcrumb-separator" aria-hidden="true"> / </span>}{index === items.length - 1 ? <span ref={currentRef} tabIndex={-1} aria-current="page">{item.label}</span> : <a href={item.href} onClick={event => { if (item.onClick) { event.preventDefault(); item.onClick(); } }}>{item.label}</a>}</span>
  )}</div>{actionsRef && <div className="breadcrumb-actions" ref={actionsRef} />}</nav>;
}
