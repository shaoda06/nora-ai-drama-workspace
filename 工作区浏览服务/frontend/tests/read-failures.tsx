import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { get } from '../src/api';
import { Dialog, Result } from '../src/components';
import { FloatingMessage, Notifications, useNotify } from '../src/components/Notifications';
import '../src/style.css';
import '../src/components/TaskSidebar.css';

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
function ReadArea({ name }: { name: string }) {
  const query = useQuery({ queryKey: ['read-failure-fixture', name], queryFn: () => get<{ text: string }>('/api/read-failure-fixture/' + name), initialData: name === 'A' ? { text: '读取区A的缓存资料。' } : undefined });
  return <section aria-label={'读取区' + name}><h2>读取区{name}</h2>
    <Result loading={query.isPending} error={query.error} retry={query.refetch} retrying={query.isFetching} />
    {query.data && <p>{query.data.text}</p>}
  </section>;
}
function Demo() {
  const notify = useNotify();
  const [showB, setShowB] = useState(true);
  const [dialog, setDialog] = useState(false);
  return <div className="workspace-with-tasks"><main>
    <h1>读取失败公共消息回归</h1>
    <div className="toolbar">
      <button onClick={() => notify('独立普通通知。')}>普通通知</button>
      <button onClick={() => setShowB(value => !value)}>切换读取区B</button>
      <button onClick={() => setDialog(true)}>打开失败预览</button>
    </div>
    <FloatingMessage>项目资料有更新。<button onClick={() => {}}>读取新版本</button></FloatingMessage>
    <ReadArea name="A" />{showB && <ReadArea name="B" />}
    {dialog && <Dialog title="失败预览" close={() => setDialog(false)}><ReadArea name="Modal" /></Dialog>}
  </main><footer className="site-footer">测试页脚</footer></div>;
}
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><Notifications><Demo /></Notifications></QueryClientProvider>);
