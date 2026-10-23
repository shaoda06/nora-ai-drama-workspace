import type { ReactNode } from 'react';
import { PointerTooltip } from './PointerTooltip';

export function UnderlineTabs<T extends string>({ items, selected, onChange, label, disabled = false, compact = false, scrollable = false }: {
  items: { value: T; label: string; icon?: ReactNode; tooltip?: string }[];
  selected: T;
  onChange: (value: T) => void;
  label: string;
  disabled?: boolean;
  compact?: boolean;
  scrollable?: boolean;
}) {
  return <nav className={`underline-tabs${compact ? ' underline-tabs-compact' : ''}${scrollable ? ' underline-tabs-scroll' : ''}`} aria-label={label}>
    {items.map(item => <PointerTooltip key={item.value} text={item.tooltip}><button disabled={disabled} aria-current={selected === item.value ? 'page' : undefined} onClick={() => onChange(item.value)}>{item.icon}{item.label}</button></PointerTooltip>)}
  </nav>;
}
