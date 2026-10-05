export function TabNav({ items, selected, onChange, label, vertical = false }: {
  items: { value: string; label: string }[];
  selected: string;
  onChange: (value: string) => void;
  label: string;
  vertical?: boolean;
}) {
  return <nav className={vertical ? 'tabs tabs-vertical' : 'tabs'} aria-label={label}>
    {items.map(item => <button key={item.value} aria-current={selected === item.value ? 'page' : undefined} onClick={() => onChange(item.value)}>{item.label}</button>)}
  </nav>;
}
