export function TabNav({ items, selected, onChange, label, vertical = false, groups }: {
  items: { value: string; label: string }[];
  selected: string;
  onChange: (value: string) => void;
  label: string;
  vertical?: boolean;
  groups?: { label: string; values: string[] }[];
}) {
  return <nav className={vertical ? 'tabs tabs-vertical' : groups ? 'tabs tabs-grouped' : 'tabs'} aria-label={label}>
    {items.map(item => {
      const group = groups?.find(group => group.values.includes(item.value));
      if (!group) return <button key={item.value} aria-current={selected === item.value ? 'page' : undefined} onClick={() => onChange(item.value)}>{item.label}</button>;
      if (item.value !== group.values[0]) return null;
      const active = group.values.includes(selected);
      return <select className="tab-select" key={group.label} aria-label={group.label} data-active={active} value={active ? selected : ''} onChange={event => onChange(event.target.value)}>
        <option value="" disabled hidden>{group.label}</option>
        {items.filter(item => group.values.includes(item.value)).map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select>;
    })}
  </nav>;
}
