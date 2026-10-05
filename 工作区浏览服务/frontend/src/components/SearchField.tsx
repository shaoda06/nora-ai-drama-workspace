export function SearchField({ label, placeholder, value, onChange }: { label: string; placeholder: string; value: string; onChange: (value: string) => void }) {
  return <input className="search-field" aria-label={label} placeholder={placeholder} value={value} onChange={event => onChange(event.target.value)} />;
}
