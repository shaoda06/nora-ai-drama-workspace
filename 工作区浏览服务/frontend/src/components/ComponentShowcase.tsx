import { useCallback, useEffect, useRef, useState } from 'react';
import { Dialog, Document, FileTree, PreviewContext } from '../components';
import { TabNav } from './TabNav';
import { UnderlineTabs } from './UnderlineTabs';
import { TabSelect } from './TabSelect';
import { Switch } from './Switch';
import { CopyButton } from './CopyButton';
import { FloatingMessage, useNotify } from './Notifications';
import { MessagePanel } from './MessagePanel';
import { Pagination } from './Pagination';
import { ComponentExample as Example, ShowcaseExamples } from './ShowcaseExamples';
import './ComponentShowcase.css';

const categories = [
  { value: 'controls', label: '按钮与切换' }, { value: 'select', label: '下拉菜单' },
  { value: 'messages', label: '消息提示' }, { value: 'reading', label: '弹窗与阅读' },
  { value: 'lists', label: '列表与分页' },
  { value: 'layout', label: '布局与搜索' }, { value: 'files', label: '文件与正文' },
  { value: 'states', label: '加载与同步' }, { value: 'media', label: '图片与音视频' },
  { value: 'production', label: '选集与分段' }, { value: 'tasks', label: '任务卡片' },
  { value: 'coverage', label: '覆盖范围' },
];
const options = [
  { value: 'one', label: '候选一' }, { value: 'two', label: '候选二', badge: '已采用' },
  { value: 'long', label: '这是一条较长的选项名称，用来查看菜单在窄屏下的换行效果' },
];
const sampleText = '这是一段公共组件演示文字。';
const sampleDocument = { html: '<h1>示例阅读文档</h1><p>这里的内容仅用于演示，不属于任何项目。</p><h2 id="demo-overview">内容概览</h2><p>可以展开章节导航、跳到指定章节，也可以复制示例文字。</p><h3 id="demo-detail">阅读细节</h3><p>正文沿用网站的字体、段落与表格样式。</p><h2 id="demo-checks">示例清单</h2><ul><li>打开文档弹窗</li><li>查看章节与正文</li><li>关闭后继续浏览组件</li></ul><table><thead><tr><th>状态</th><th>说明</th></tr></thead><tbody><tr><td>示例</td><td>不读取或修改真实项目资料</td></tr></tbody></table>' };
const sampleItems = Array.from({ length: 18 }, (_, i) => `示例记录 ${String(i + 1).padStart(2, '0')}`);

export function ComponentShowcase({ onImplementation }: { onImplementation: () => void }) {
  const [category, setCategory] = useState('controls');
  const [clicks, setClicks] = useState(0);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(sampleText);
  const [tab, setTab] = useState('overview');
  const [selection, setSelection] = useState('one');
  const [disabled, setDisabled] = useState(false);
  const [pending, setPending] = useState(false);
  const [dialog, setDialog] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [empty, setEmpty] = useState(false);
  const notify = useNotify();
  const notices = useRef<(() => void)[]>([]);
  useEffect(() => () => { notices.current.forEach(remove => remove()); }, []);
  const showNotice = (text: string, tone: 'info' | 'error' = 'info') => { notices.current.push(notify(text, tone)); };
  const clearNotices = () => { notices.current.forEach(remove => remove()); notices.current = []; setPending(false); };
  const closeDialog = useCallback(() => setDialog(null), []);
  return <div className="component-showcase">
    <header className="component-showcase-heading"><div><h2>公共组件</h2><p>直接操作真实组件，查看网站统一的样式和行为。</p></div><button className="link" onClick={onImplementation}>实现说明</button></header>
    <TabNav label="组件分类" items={categories} selected={category} onChange={value => { clearNotices(); setCategory(value); }} />
    <div className="component-examples">
      {category === 'controls' && <>
        <Example title="按钮与复制" rule="按钮沿用全站样式；禁用后不能操作。复制按钮会复制下方示例文字并触发公共反馈。" usage="文档阅读、提示词、修改意见">
          <div className="component-demo-row"><button onClick={() => setClicks(n => n + 1)}>普通按钮</button><button className="link" onClick={() => setClicks(n => n + 1)}>链接按钮</button><button disabled>禁用按钮</button></div>
          <p>已点击 {clicks} 次</p><p>{sampleText}</p><CopyButton text={sampleText} label="复制示例文字" />
        </Example>
        <Example title="编辑开关与页签" rule="开关只控制示例正文的编辑状态；页签用于切换同一区域的内容。" usage="提示词编辑、分镜与提示词页签">
          <div className="component-demo-row"><span>编辑模式</span><Switch label="示例编辑模式" checked={editing} onChange={setEditing} /></div>
          {editing ? <textarea aria-label="示例正文" value={draft} onChange={event => setDraft(event.target.value)} /> : <p className="component-draft">{draft}</p>}
          <UnderlineTabs label="示例页签" items={[{ value: 'overview', label: '概览' }, { value: 'detail', label: '详情' }]} selected={tab} onChange={setTab} />
          <p>{tab === 'overview' ? '这里是概览内容。' : '这里是详情内容。'}</p>
        </Example>
      </>}
      {category === 'select' && <Example title="选项菜单" rule="选中项右侧统一显示“当前”，支持方向键、Enter选择与Esc关闭；长选项可换行。" usage="项目切换、场次轮次、视频候选、提示词分类">
        <div className="component-demo-row"><TabSelect label="示例选项" items={options} selected={selection} onChange={setSelection} disabled={disabled} /><span>禁用菜单</span><Switch label="禁用示例菜单" checked={disabled} onChange={setDisabled} /></div>
        <p className="component-draft">已选择：{options.find(item => item.value === selection)!.label}</p>
      </Example>}
      {category === 'messages' && <>
        <Example title="公共消息" rule="成功提示3秒消失，错误提示不定时消失；所有提示都可关闭。关闭持续提示不会结束演示状态。" usage="保存、复制、下载进度、读取错误与更新提醒">
          <div className="component-demo-row"><button onClick={() => showNotice('演示：操作成功')}>显示成功提示</button><button onClick={() => showNotice('演示：操作失败，请重试', 'error')}>显示错误提示</button><button disabled={pending} onClick={() => setPending(true)}>显示持续提示</button></div>
          <p>演示状态：{pending ? '进行中' : '未进行'}</p>
          <div className="component-demo-row"><button disabled={!pending} onClick={() => { setPending(false); showNotice('演示已结束'); }}>结束演示</button><button className="link" onClick={clearNotices}>清除演示消息</button></div>
        </Example>
        <Example title="页面内说明" rule="与当前内容相关的说明留在正文中，悬停或聚焦文字可查看详情。操作反馈使用左下角消息。" usage="剧集制作的分段说明与资料状态">
          <MessagePanel label="示例页面说明" messages={[{ id: 'info', content: '这是随页面展示的资料说明。', detail: '此处使用公共MessagePanel与详情提示组件。' }, { id: 'warning', tone: 'warning', content: '示例资料待确认。', actions: <button className="link" onClick={() => setDialog('示例资料说明')}>查看说明</button> }]} />
        </Example>
      </>}
      {category === 'reading' && <Example title="文档弹窗" rule="弹窗复用正文排版和章节导航。点击关闭、按Esc或点击遮罩可退出，回到原阅读位置。" usage="开发记录、项目总索引、项目文档预览">
        <button onClick={() => setDialog('示例阅读文档')}>打开示例文档</button>
        <p>打开后可展开章节、跳转正文，或复制示例文字。</p>
      </Example>}
      {category === 'lists' && <>
        <Example title="目录与文件" rule="目录按需展开，点击文件进入阅读。这里仅展示示例文件。" usage="项目文档目录、参考资料">
          <PreviewContext.Provider value={item => setDialog(item.name)}><FileTree showOriginal={false} items={[{ kind: 'group', name: '示例目录', files: [{ kind: 'markdown', name: '示例说明', key: 'demo-note', statusHtml: '<span class="status-badge status-gray">示例</span>' }, { kind: 'group', name: '子目录', files: [{ kind: 'markdown', name: '阅读示例', key: 'demo-reading', statusHtml: '<span class="status-badge status-gray">示例</span>' }] }] }]} /></PreviewContext.Provider>
        </Example>
        <Example title="分页与空状态" rule="示例每页6项，首页和末页会禁用对应方向；无内容时不显示分页。" usage="版本记录、资产列表、风格库">
          <div className="component-demo-row"><span>显示空列表</span><Switch label="显示空列表" checked={empty} onChange={setEmpty} /></div>
          {empty ? <p className="muted">这里还没有记录。</p> : <ul className="component-sample-list">{sampleItems.slice((page - 1) * 6, page * 6).map(item => <li key={item}>{item}</li>)}</ul>}
          <Pagination page={page} total={empty ? 0 : sampleItems.length} pageSize={6} change={setPage} />
        </Example>
      </>}
      <ShowcaseExamples key={category} category={category} />
    </div>
    {pending && <FloatingMessage>演示进行中。关闭消息不会结束演示，可在展示页点击“结束演示”。</FloatingMessage>}
    {dialog && <Dialog title={dialog} close={closeDialog}><div className="component-demo-row"><CopyButton text={sampleText} label="复制示例文字" /></div><Document value={sampleDocument} showOriginal={false} /></Dialog>}
  </div>;
}
