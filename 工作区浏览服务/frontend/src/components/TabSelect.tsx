export function TabSelect({ items, selected, onChange, label, disabled = false }: {
  items: { value: string; label: string }[];
  selected: string;
  onChange: (value: string) => void;
  label: string;
  disabled?: boolean;
}) {
  return <select className="tab-select" aria-label={label} disabled={disabled} data-active={Boolean(selected)} value={selected} onChange={event => onChange(event.target.value)}>
    <option value="" disabled hidden>{label}</option>
    {items.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
  </select>;
}
