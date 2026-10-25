import { createContext } from 'react';
import type { ReactNode, Ref } from 'react';

export const BreadcrumbActionsContext = createContext<HTMLDivElement | null>(null);
export const BreadcrumbSelectorContext = createContext<HTMLSpanElement | null>(null);

export function Breadcrumbs({ items, currentRef, actionsRef, selectorRef }: { items: { label: ReactNode; href?: string; onClick?: () => void }[]; currentRef?: Ref<HTMLSpanElement>; actionsRef?: Ref<HTMLDivElement>; selectorRef?: Ref<HTMLSpanElement> }) {
  return <nav className="breadcrumbs" aria-label="当前位置"><div>{items.map((item, index) =>
    <span key={index}>{index > 0 && <span className="breadcrumb-separator" aria-hidden="true"> / </span>}{index === items.length - 1 ? <span ref={currentRef} tabIndex={-1} aria-current="page">{item.label}</span> : <a href={item.href} onClick={event => { if (item.onClick) { event.preventDefault(); item.onClick(); } }}>{item.label}</a>}{index === 0 && selectorRef && <span className="breadcrumb-selector" ref={selectorRef} />}</span>
  )}</div>{actionsRef && <div className="breadcrumb-actions" ref={actionsRef} />}</nav>;
}
