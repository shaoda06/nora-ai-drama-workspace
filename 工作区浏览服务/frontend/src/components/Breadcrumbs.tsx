import type { Ref } from 'react';

export function Breadcrumbs({ items, currentRef }: { items: { label: string; href?: string; onClick?: () => void }[]; currentRef?: Ref<HTMLSpanElement> }) {
  return <nav className="breadcrumbs" aria-label="当前位置">{items.map((item, index) =>
    <span key={index}>{index > 0 && <span className="breadcrumb-separator" aria-hidden="true"> / </span>}{index === items.length - 1 ? <span ref={currentRef} tabIndex={-1} aria-current="page">{item.label}</span> : <a href={item.href} onClick={event => { if (item.onClick) { event.preventDefault(); item.onClick(); } }}>{item.label}</a>}</span>
  )}</nav>;
}
