import { useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { TabSelect } from '../src/components/TabSelect';
import { LocalQueueCard } from '../src/components/LocalQueueCard';
import '../src/style.css';
function Demo() {
  const [value, setValue] = useState('');
  const [calls, setCalls] = useState(0);
  const [destination, setDestination] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  const items = [{ value: '', label: '全部分类' }, { value: '图片', label: '图片' }, { value: '视频', label: '视频' }];
  const change = (value: string) => { setValue(value); setCalls(count => count + 1); };
  return <main><h1>共用下拉菜单测试</h1>
    <TabSelect label="分类筛选" selected={value} onChange={change} items={items} />
    <div className="tabs tabs-grouped"><TabSelect label="分组导航" selected={value} onChange={change} items={items} reselect /></div>
    <TabSelect iconOnly label="快速选择" selected={value} onChange={change} items={items} />
    <TabSelect label="禁用" selected={value} onChange={change} items={items} disabled />
    <TabSelect label="空选项" selected="" onChange={change} items={[]} />
    <p data-testid="calls">{calls}</p><p data-testid="destination">{destination}</p>
    <button onClick={() => dialog.current!.showModal()}>打开弹窗</button>
    <dialog ref={dialog} style={{ padding: 24 }}><form onSubmit={event => { event.preventDefault(); dialog.current!.close(); }}>
      <label>上级分类<TabSelect label="弹窗分类" selected={value} onChange={change} items={items} /></label>
      <button type="submit">保存</button>
    </form></dialog>
    <LocalQueueCard task={{ queue: 'local', id: 'test', project: '', title: '隔离任务', task_type: 'image', status: 'paused', remote_url: 'source', can_transfer: true, transfer_targets: [{ name: '目标节点', url: 'target' }], created_at: '', updated_at: '' }} onTransfer={(_, url) => setDestination(url)} />
    <div style={{ position: 'fixed', bottom: 12, right: 12 }}><TabSelect label="底部菜单" selected="19" onChange={() => {}} items={Array.from({ length: 20 }, (_, i) => ({ value: String(i), label: `第${i}项` }))} /></div>
  </main>;
}
createRoot(document.getElementById('root')!).render(<Demo />);
