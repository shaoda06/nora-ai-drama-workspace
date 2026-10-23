import type { ReactNode } from 'react';

export function PageHeader({ eyebrow, title, description, actions, children, eyebrowInline = false, stacked = false }: { eyebrow?: string; title: string; description?: string; actions?: ReactNode; children?: ReactNode; eyebrowInline?: boolean; stacked?: boolean }) {
  return <div className={'page-heading' + (stacked ? ' page-heading-stacked' : '')}>
    <div>{eyebrow && !eyebrowInline && <p className="eyebrow">{eyebrow}</p>}<div className="page-title"><h1>{title}</h1>{eyebrow && eyebrowInline && <p className="eyebrow">{eyebrow}</p>}</div>{description && <p className="page-description">{description}</p>}{children}</div>
    {actions && <div className="page-actions">{actions}</div>}
  </div>;
}
