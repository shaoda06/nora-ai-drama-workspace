import type { ReactNode } from 'react';

export function PageHeader({ eyebrow, title, description, actions, eyebrowInline = false }: { eyebrow: string; title: string; description?: string; actions?: ReactNode; eyebrowInline?: boolean }) {
  return <div className="page-heading">
    <div>{!eyebrowInline && <p className="eyebrow">{eyebrow}</p>}<div className="page-title"><h1>{title}</h1>{eyebrowInline && <p className="eyebrow">{eyebrow}</p>}</div>{description && <p className="page-description">{description}</p>}</div>
    {actions && <div className="page-actions">{actions}</div>}
  </div>;
}
