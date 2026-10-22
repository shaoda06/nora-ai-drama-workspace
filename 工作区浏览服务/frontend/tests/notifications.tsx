import { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Document, Preview } from '../src/components';
import { FloatingMessage, Notifications, useNotify } from '../src/components/Notifications';
import { SyncNotification } from '../src/components/SyncNotification';
import { BottomTools } from '../src/components/BottomTools';
import '../src/style.css';
import '../src/components/TaskSidebar.css';

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
function Demo() {
  const notify = useNotify();
  const cleanup = useRef<() => void>(() => {});
  const [documentVersion, setDocumentVersion] = useState(1);
  const [documentVisible, setDocumentVisible] = useState(true);
  const [pending, setPending] = useState(false);
  const [preview, setPreview] = useState(false);
  const [revision, setRevision] = useState(1);
  const [sync, setSync] = useState<{ error: string | null; retryAt?: number }>({ error: null });
  useEffect(() => {
    const update = () => setRevision(value => value + 1);
    window.addEventListener('fixture-preview-update', update);
    return () => window.removeEventListener('fixture-preview-update', update);
  }, []);
  return <div className="workspace-with-tasks">
    <main><h1>公共消息组件回归测试</h1><div className="toolbar">
      <button onClick={() => notify('普通通知，3秒后消失。')}>普通通知</button>
      <button onClick={() => notify('音频播放失败，请稍后重试。', 'error')}>错误通知</button>
      <button onClick={() => { cleanup.current = notify('独立常驻通知。', 'info', 0); }}>常驻通知</button>
      <button onClick={() => cleanup.current()}>清理常驻通知</button>
      <button onClick={() => setDocumentVersion(value => value + 1)}>更新文档</button>
      <button onClick={() => setDocumentVisible(value => !value)}>切换文档</button>
      <button onClick={() => setPending(value => !value)}>切换页面更新</button>
      <button onClick={() => setPreview(true)}>打开预览</button>
      <button onClick={() => setSync({ error: '同步失败', retryAt: Date.now() + 30000 })}>同步失败</button>
      <button onClick={() => setSync({ error: null })}>同步恢复</button>
      <button onClick={() => { for (let i = 0; i < 15; i++) notify(`多条通知${i}`, 'info', 0); }}>批量通知</button>
    </div>
    <SyncNotification error={sync.error} errorKind="parse_error" retryAt={sync.retryAt} updating={false} />
    {documentVisible && <Document value={{ html: `<h2>正文第${documentVersion}版</h2><p>文档内容。</p>`, url: '/fixture.md' }} />}
    {pending && <FloatingMessage>页面已有更新，将在编辑或播放结束后自动刷新。</FloatingMessage>}
    {preview && <Preview project="消息测试" item={{ kind: 'text', name: '预览测试.txt', key: '预览测试.txt', url: '/fixture.txt' }} revision={revision} close={() => setPreview(false)} />}
    </main>
    <footer className="site-footer">测试页脚</footer>
    <BottomTools><button className="back-top">↑ 返回顶部</button></BottomTools>
  </div>;
}
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><Notifications><Demo /></Notifications></QueryClientProvider>);
