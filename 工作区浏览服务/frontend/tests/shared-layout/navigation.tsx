import { useState } from 'react';
import { TabNav } from '../../src/components/TabNav';
import { UnderlineTabs } from '../../src/components/UnderlineTabs';
import { TabSelect } from '../../src/components/TabSelect';
import { Pagination } from '../../src/components/Pagination';

const longLabel = '很长的导航选项说明与版本名称' + 'LongUnbrokenReference'.repeat(5);
const items = [{ value: 'short', label: '简短', marker: '本轮新生成视频' }, { value: 'disabled', label: '不可选择', disabled: true }, { value: 'long', label: longLabel }];
export function NavigationFixture() {
  const [selected, setSelected] = useState('short');
  const [page, setPage] = useState(9);
  const [total, setTotal] = useState(1000);
  const [disabled, setDisabled] = useState(false);
  const [filename, setFilename] = useState('one');
  return <section data-testid="navigation" className="panel">
    <button onClick={() => setDisabled(value => !value)}>切换导航禁用</button>
    <button onClick={() => setSelected('short')}>重置导航</button>
    <output data-testid="nav-value">{selected}</output>
    <div data-testid="nav-normal"><TabNav label="长文字导航" items={items} selected={selected} onChange={setSelected} disabled={disabled} /></div>
    <div data-testid="nav-group"><TabNav label="分组导航" items={items} groups={[{ label: '分组长选项', values: items.map(item => item.value) }]} selected={selected} onChange={setSelected} disabled={disabled} /></div>
    <div data-testid="nav-grid"><TabNav vertical mobileLayout="grid" label="网格导航" items={items} selected={selected} onChange={setSelected} disabled={disabled} /></div>
    <div data-testid="nav-scroll"><TabNav vertical label="滚动导航" items={items} selected={selected} onChange={setSelected} disabled={disabled} /></div>
    <div data-testid="underline"><UnderlineTabs label="长文字页签" items={items} selected={selected} onChange={setSelected} disabled={disabled} /></div>
    <div data-testid="underline-scroll"><UnderlineTabs compact scrollable label="滚动页签" items={items} selected={selected} onChange={setSelected} disabled={disabled} /></div>
    <div data-testid="select-field"><TabSelect variant="field" label="长选项下拉" items={items} selected={selected} onChange={setSelected} disabled={disabled} /></div>
    <TabSelect label="全禁用菜单" items={items.map(item => ({ ...item, disabled: true }))} selected="short" onChange={setSelected} />
    <TabSelect label="空菜单" items={[]} selected="" onChange={setSelected} />
    <TabSelect size="toolbar" highlightSelected label="短轮次下拉" items={[{ value: '11', label: '第11轮' }, { value: '10', label: '第10轮' }]} selected="11" onChange={() => {}} disabled={disabled} />
    <TabSelect iconOnly label="图标短选项" items={[{ value: 'one', label: '一' }, { value: 'two', label: '二' }]} selected="one" onChange={() => {}} disabled={disabled} />
    <button onClick={() => { setPage(1); setTotal(1000); }}>首页</button>
    <button onClick={() => { setPage(100); setTotal(1000); }}>末页</button>
    <button onClick={() => { setPage(9); setTotal(1000); }}>第九页</button>
    <button onClick={() => { setPage(99999999); setTotal(1000000000); }}>大页码</button>
    <button onClick={() => { setPage(1); setTotal(10); }}>单页</button>
    <button onClick={() => { setPage(1); setTotal(0); }}>空页</button>
    <div data-testid="pagination"><Pagination page={page} total={total} pageSize={10} change={setPage} /></div>
    <div data-testid="pagination-single"><Pagination alwaysShow itemLabel="集" page={1} total={1} pageSize={5} change={setPage} /></div>
    <div data-testid="pagination-empty"><Pagination alwaysShow itemLabel="集" page={1} total={0} pageSize={5} change={setPage} /></div>
    {[0, 1, 5, 6].map(count => <div key={count} data-testid={`custom-pagination-${count}`}><Pagination compact page={1} total={count} pageSize={5} change={setPage}><span>自定义选集内容</span></Pagination></div>)}
    <div data-testid="filename-pagination" style={{ maxWidth: 161 }}><Pagination compact fitContent alwaysShow page={1} total={5} pageSize={5} change={setPage}>
      <TabNav scrollable disabled={disabled} label="文件名分页示例" selected={filename} onChange={setFilename} items={[{ value: 'one', label: '第1集' }, { value: 'two', label: '第2集' }, { value: 'three', label: '第3集' }, { value: 'four', label: '第4集' }, { value: 'long', label: longLabel }]} />
    </Pagination><output data-testid="filename-value">{filename}</output></div>
    <output data-testid="page-value">{page}</output>
    <div data-testid="switch-content" style={{ height: page % 2 ? 40 : 1600 }}>模拟不同页内容高度</div>
  </section>;
}
