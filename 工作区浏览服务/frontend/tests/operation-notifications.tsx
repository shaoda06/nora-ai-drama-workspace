import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Dialog } from '../src/components';
import { Notifications } from '../src/components/Notifications';
import { CopyButton } from '../src/components/CopyButton';
import { DownloadButton } from '../src/components/DownloadButton';
import { NodeEditor } from '../src/components/NodeEditor';
import { useRevisionNotesExport } from '../src/components/RevisionNotes';
import '../src/style.css';

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
function Demo() {
  const [nodes, setNodes] = useState(false);
  const notes = useRevisionNotesExport({ project: '界面测试', episode: 'EP001', scene: 'C001' }, [], { stage: '一采', number: 1, label: '第1轮', versions: {} });
  return <div className="workspace-with-tasks"><main>
    <h1>操作消息回归测试</h1>
    <div className="toolbar"><CopyButton label="复制测试正文" text="测试正文" /><button onClick={() => setNodes(true)}>编辑测试节点</button>{notes.control}</div>
    <DownloadButton url="/fixture-download" label="下载测试文件" title="测试文件" />
    {nodes && <Dialog title="测试节点配置" close={() => setNodes(false)}><NodeEditor close={() => setNodes(false)} /></Dialog>}
    {notes.dialog}
  </main><footer className="site-footer">测试页脚</footer></div>;
}
createRoot(document.getElementById('root')!).render(<QueryClientProvider client={client}><Notifications><Demo /></Notifications></QueryClientProvider>);
