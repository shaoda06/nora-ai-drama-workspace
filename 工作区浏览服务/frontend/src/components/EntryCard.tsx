import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

export function EntryCard({ to, title, description, icon }: { to: string; title: string; description: string; icon?: ReactNode }) {
  return <Link className="project-card" to={to}>{icon && <span className="project-icon">{icon}</span>}<h3>{title}</h3><p>{description}<span>→</span></p></Link>;
}
