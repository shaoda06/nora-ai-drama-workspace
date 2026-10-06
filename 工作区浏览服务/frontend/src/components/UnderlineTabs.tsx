export function UnderlineTabs({ items, selected, onChange, label, disabled = false }: {
  items: { value: string; label: string }[];
  selected: string;
  onChange: (value: string) => void;
  label: string;
  disabled?: boolean;
}) {
  return <nav className="underline-tabs" aria-label={label}>
    {items.map(item => <button key={item.value} disabled={disabled} aria-current={selected === item.value ? 'page' : undefined} onClick={() => onChange(item.value)}>{item.label}</button>)}
  </nav>;
}
