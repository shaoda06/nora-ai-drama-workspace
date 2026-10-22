import { useEffect, useId, useRef, useState } from 'react';
import type { CSSProperties, KeyboardEvent } from 'react';
import './TabSelect.css';

type Props = {
  items: { value: string; label: string; badge?: string }[];
  selected: string;
  onChange: (value: string) => void;
  label: string;
  disabled?: boolean;
  reselect?: boolean;
  iconOnly?: boolean;
};

export function TabSelect({ items, selected, onChange, label, disabled, iconOnly, reselect = false }: Props) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [active, setActive] = useState(0);
  const [position, setPosition] = useState<CSSProperties>({});
  const positionMenu = () => {
    const rect = trigger.current!.getBoundingClientRect();
    const width = Math.min(Math.max(rect.width, 340), window.innerWidth - 16);
    const below = window.innerHeight - rect.bottom - 12;
    const above = rect.top - 12;
    const openAbove = below < 320 && above > below;
    setPosition({ left: Math.max(8, Math.min(rect.left, window.innerWidth - width - 8)),
      top: openAbove ? undefined : rect.bottom + 4, bottom: openAbove ? window.innerHeight - rect.top + 4 : undefined, width, maxHeight: Math.min(320, openAbove ? above : below) });
    setActive(Math.max(0, items.findIndex(item => item.value === selected)));
  };
  const close = () => { menu.current!.hidePopover(); setExpanded(false); };
  const choose = (index: number) => { const value = items[index].value; close(); trigger.current!.focus(); if (reselect || value !== selected) onChange(value); };
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
      if (expanded) {
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); }
        close();
      }
    }
  };
  return <>
    <button ref={trigger} type="button" className={`tab-select tab-select-marked${iconOnly ? ' tab-select-icon' : ''}`} role="combobox" aria-label={label}
      aria-haspopup="listbox" aria-controls={id} aria-expanded={expanded} aria-activedescendant={expanded ? `${id}-${active}` : undefined}
      disabled={disabled || items.length === 0} data-active={Boolean(selected)} data-value={selected} onKeyDown={keyDown} popoverTarget={id}
      onClick={() => { if (!expanded) positionMenu(); setExpanded(!expanded); }}>
      {!iconOnly && <span className="tab-select-label">{items.find(item => item.value === selected)?.label || label}{items.find(item => item.value === selected)?.badge && <span className="tab-select-status">{items.find(item => item.value === selected)!.badge}</span>}</span>}
      <svg aria-hidden="true" width="12" height="12" viewBox="0 0 12 12"><path d="m3 4.5 3 3 3-3" fill="none" stroke="currentColor" /></svg>
    </button>
    <div ref={menu} id={id} popover="auto" role="listbox" aria-label={label} className="tab-select-menu" style={position}
      onToggle={event => setExpanded(event.currentTarget.matches(':popover-open'))}>
      {items.map((item, index) => <button key={item.value} type="button" role="option" id={`${id}-${index}`}
        aria-selected={item.value === selected} data-active={index === active} tabIndex={-1}
        onMouseEnter={() => setActive(index)} onMouseDown={event => event.preventDefault()} onClick={() => choose(index)}>
        <span>{item.label}{item.badge && <span className="tab-select-status">{item.badge}</span>}</span>{item.value === selected && <span className="tab-select-badge">当前</span>}
      </button>)}
    </div>
  </>;
}
