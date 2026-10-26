import { RoundNewDot } from './RoundNewDot';
import { TabSelect } from './TabSelect';
import './TabNav.css';

export function TabNav({ items, selected, onChange, label, vertical = false, groups, disabled = false, compact = false, wide = false, mobileLayout = "scroll", scrollable = false }: {
  items: { value: string; label: string; disabled?: boolean; marker?: string }[];
  selected: string;
  onChange: (value: string) => void;
  label: string;
  vertical?: boolean;
  groups?: { label: string; values: string[] }[];
  disabled?: boolean;
  compact?: boolean;
  wide?: boolean;
  mobileLayout?: "scroll" | "grid";
  scrollable?: boolean;
}) {
  return <nav className={(vertical ? 'tabs tabs-vertical' : groups ? 'tabs tabs-grouped' : 'tabs') + (compact ? ' tabs-compact' : '') + (wide ? ' tabs-wide' : '') + (vertical && mobileLayout === 'grid' ? ' tabs-mobile-grid' : '') + (scrollable ? ' tabs-scroll' : '')} aria-label={label}>
    {items.map(item => {
      const group = groups?.find(group => group.values.includes(item.value));
      if (!group) return <button key={item.value} title={item.marker ? `${item.label} · ${item.marker}` : scrollable ? item.label : undefined} aria-description={item.marker} disabled={disabled || item.disabled} aria-current={selected === item.value ? 'page' : undefined} onClick={() => onChange(item.value)}>{item.label}{item.marker && <RoundNewDot />}</button>;
      if (item.value !== group.values[0]) return null;
      const active = group.values.includes(selected);
      return <TabSelect highlightSelected reselect key={group.label} disabled={disabled} label={group.label} selected={active ? selected : ''} onChange={onChange} items={items.filter(item => group.values.includes(item.value))} />;
    })}
  </nav>;
}
