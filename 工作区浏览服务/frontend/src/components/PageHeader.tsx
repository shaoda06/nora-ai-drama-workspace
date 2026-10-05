import type { ReactNode } from 'react';

export function PageHeader({ eyebrow, title, description, actions, children, eyebrowInline = false, actionsInline = false }: { eyebrow?: string; title: string; description?: string; actions?: ReactNode; children?: ReactNode; eyebrowInline?: boolean; actionsInline?: boolean }) {
  return <div className="page-heading">
    <div>{eyebrow && !eyebrowInline && <p className="eyebrow">{eyebrow}</p>}<div className="page-title"><h1>{title}</h1>{eyebrow && eyebrowInline && <p className="eyebrow">{eyebrow}</p>}{actionsInline && actions}</div>{description && <p className="page-description">{description}</p>}{children}</div>
    {actions && !actionsInline && <div className="page-actions">{actions}</div>}
  </div>;
}
