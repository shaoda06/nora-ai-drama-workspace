export function Breadcrumbs({ items }: { items: string[] }) {
  return <nav className="breadcrumbs" aria-label="当前位置">{items.map((item, index) =>
    <span key={index}>{index > 0 && <span className="breadcrumb-separator" aria-hidden="true"> / </span>}<span aria-current={index === items.length - 1 ? 'page' : undefined}>{item}</span></span>
  )}</nav>;
}
