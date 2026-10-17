import { useEffect, useId, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';

type Props = {
  items: { value: string; label: string; badge?: string }[];
  selected: string;
  onChange: (value: string) => void;
  label: string;
  disabled?: boolean;
  reselect?: boolean;
};

function MarkedTabSelect({ items, selected, onChange, label, disabled }: Props) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [active, setActive] = useState(0);
  const [position, setPosition] = useState({ left: 0, top: 0, width: 0, maxHeight: 0 });
  const positionMenu = () => {
    const rect = trigger.current!.getBoundingClientRect();
    const width = Math.min(Math.max(rect.width, 340), window.innerWidth - 16);
    setPosition({ left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)),
      top: rect.bottom + 4, width, maxHeight: Math.min(320, Math.max(80, window.innerHeight - rect.bottom - 20)) });
    setActive(Math.max(0, items.findIndex(item => item.value === selected)));
  };
  const close = () => { menu.current!.hidePopover(); setExpanded(false); };
  const choose = (index: number) => { onChange(items[index].value); close(); trigger.current!.focus(); };
  useEffect(() => {
    if (expanded) menu.current!.children[active]?.scrollIntoView({ block: 'nearest' });
  }, [active, expanded]);
  const keyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!expanded) trigger.current!.click();
      else setActive(index => (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length);
    } else if (expanded && (event.key === 'Home' || event.key === 'End')) {
      event.preventDefault(); setActive(event.key === 'Home' ? 0 : items.length - 1);
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault(); if (expanded) choose(active); else trigger.current!.click();
    } else if (event.key === 'Escape' || event.key === 'Tab') {
      if (expanded) close();
    }
  };
  return <>
    <button ref={trigger} type="button" className="tab-select tab-select-marked" role="combobox" aria-label={label}
      aria-haspopup="listbox" aria-controls={id} aria-expanded={expanded} aria-activedescendant={expanded ? `${id}-${active}` : undefined}
      disabled={disabled} data-active={Boolean(selected)} data-value={selected} onKeyDown={keyDown} popoverTarget={id}
      onClick={() => { if (!expanded) positionMenu(); }}>
      <span className="tab-select-label">{items.find(item => item.value === selected)?.label || label}</span>
      <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12"><path d="m3 4.5 3 3 3-3" fill="none" stroke="currentColor" /></svg>
    </button>
    <div ref={menu} id={id} popover="auto" role="listbox" aria-label={label} className="tab-select-menu" style={position}
      onToggle={event => setExpanded(event.currentTarget.matches(':popover-open'))}>
      {items.map((item, index) => <button key={item.value} type="button" role="option" id={`${id}-${index}`}
        aria-selected={item.value === selected} data-active={index === active} tabIndex={-1}
        onMouseEnter={() => setActive(index)} onMouseDown={event => event.preventDefault()} onClick={() => choose(index)}>
        <span>{item.label}</span>{item.badge && <span className="tab-select-badge">{item.badge}</span>}
      </button>)}
    </div>
  </>;
}

export function TabSelect({ items, selected, onChange, label, disabled = false, reselect = false }: Props) {
  if (items.some(item => item.badge)) return <MarkedTabSelect items={items} selected={selected} onChange={onChange} label={label} disabled={disabled} />;
  return <select className="tab-select" aria-label={label} disabled={disabled} data-active={Boolean(selected)} value={selected} onChange={event => onChange(event.target.value)}>
    <option value="" disabled hidden>{label}</option>
    {items.map(item => <option key={item.value} value={item.value} onClick={reselect && item.value === selected ? () => onChange(item.value) : undefined}>{item.label}</option>)}
  </select>;
}
