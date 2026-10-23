import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TabNav } from '../src/components/TabNav';
import { TabSelect } from '../src/components/TabSelect';
import { ComponentShowcase } from '../src/components/ComponentShowcase';
import { Notifications } from '../src/components/Notifications';
import '../src/style.css';

function Fixture() {
  const [selected, setSelected] = useState('position');
  const [disabled, setDisabled] = useState(false);
  return <main><h1>分组下拉箭头回归</h1>
    <TabNav label="项目导航示例" items={[{ value: 'position', label: '项目定位' }, { value: 'character', label: '人物资料' }, { value: 'scene', label: '场景资料' }, { value: 'reference', label: '参考音频' }]}
      groups={[{ label: '相关资料', values: ['character', 'scene'] }, { label: '参考素材', values: ['reference'] }]}
      selected={selected} onChange={setSelected} disabled={disabled} />
    <TabSelect label="普通下拉示例" items={[{ value: 'scene', label: '场景资料' }]} selected="scene" onChange={() => {}} disabled={disabled} />
    <button onClick={() => setDisabled(value => !value)}>切换禁用</button>
    <output aria-label="当前页面">{selected}</output>
    <ComponentShowcase onImplementation={() => {}} />
  </main>;
}
const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><MemoryRouter><Notifications><Fixture /></Notifications></MemoryRouter></QueryClientProvider>);
