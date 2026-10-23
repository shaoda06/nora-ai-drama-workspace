import { useState } from 'react';
import { SearchField } from '../../src/components/SearchField';
import { Switch } from '../../src/components/Switch';

const longText = '很长的中文输入说明与搜索条件' + 'LongUnbrokenInputReference'.repeat(6);
export function InputsFixture() {
  const [value, setValue] = useState('');
  const [changes, setChanges] = useState(0);
  const [checked, setChecked] = useState(false);
  const [toggles, setToggles] = useState(0);
  const [disabled, setDisabled] = useState(false);
  const [submits, setSubmits] = useState(0);
  const change = (next: string) => { setValue(next); setChanges(n => n + 1); };
  return <section className="panel" data-testid="inputs">
    <button onClick={() => setDisabled(state => !state)}>切换输入禁用</button>
    <output data-testid="input-counts" style={{ display: 'block', overflowWrap: 'anywhere' }}>{JSON.stringify({ changes, toggles, submits, checked })}</output>
    <form onSubmit={event => { event.preventDefault(); setSubmits(n => n + 1); }}>
      <div style={{ width: 220, maxWidth: '100%', display: 'grid', gap: 12 }} data-testid="input-container">
        <SearchField label="标准搜索检查" placeholder={longText} value={value} onChange={change} disabled={disabled} />
        <SearchField size="compact" label="紧凑搜索检查" placeholder={longText} value={value} onChange={change} disabled={disabled} />
        <input aria-label="单行输入检查" placeholder={longText} value={value} onChange={event => change(event.target.value)} disabled={disabled} />
        <textarea aria-label="多行输入检查" placeholder={longText} value={value} onChange={event => change(event.target.value)} disabled={disabled} />
        <input aria-label="只读输入检查" value={longText} readOnly />
        <textarea aria-label="只读多行检查" value={longText} readOnly />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }} data-testid="long-switch-row">
          <span style={{ minWidth: 0, overflowWrap: 'anywhere' }}>{longText}</span>
          <Switch label={longText} checked={checked} disabled={disabled} onChange={next => { setChecked(next); setToggles(n => n + 1); }} />
        </div>
        <button type="submit">提交示例输入</button>
      </div>
    </form>
  </section>;
}
