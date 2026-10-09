import { useCallback, useEffect, useState } from 'react';
import { TaskCard, type Task } from './TaskCard';
import { LocalQueueCard, localQueueStates, type LocalQueueTask } from './LocalQueueCard';
import './TaskSidebar.css';

interface RemoteNode { url: string; name: string }

const activeStates = new Set(['submitting', 'queued', 'running', 'collecting']);

export function TaskSidebar() {
  const [open, setOpen] = useState(() => localStorage.getItem('nora-task-sidebar') === 'open');
  const [tasks, setTasks] = useState<(Task | LocalQueueTask)[]>([]);
  const [localCategory, setLocalCategory] = useState<LocalQueueTask['status']>('queued');
  const [nodes, setNodes] = useState<RemoteNode[]>([]);
  const [selectedUrl, setSelectedUrl] = useState<string | null>(null);
  const [connection, setConnection] = useState<'loading' | 'connected' | 'reconnecting'>('loading');
  useEffect(() => {
    const source = new EventSource('/api/comfy/events');
    source.addEventListener('tasks', event => {
      const snapshot = JSON.parse((event as MessageEvent).data);
      setTasks(snapshot.tasks);
      setNodes(snapshot.remote_nodes);
      setConnection('connected');
    });
    source.onerror = () => setConnection('reconnecting');
    return () => source.close();
  }, []);
  const active = tasks.filter(task => activeStates.has(task.status)).length;
  const selectedNode = nodes.find(node => node.url === selectedUrl) ?? nodes[0];
  const allLocalTasks = tasks.filter((task): task is LocalQueueTask => 'queue' in task && task.queue === 'local');
  const localTasks = allLocalTasks.filter(task => task.status === localCategory);
  const nodeTasks = tasks.filter((task): task is Task => !('queue' in task && task.queue === 'local'))
    .filter(task => task.remote_url === selectedNode?.url);
  const visibleTasks = nodeTasks.filter(task => activeStates.has(task.status));
  const nodeRunning = nodeTasks.filter(task => task.status === 'running').length;
  const nodeQueued = nodeTasks.filter(task => task.status === 'queued').length;
  const reorderLocal = useCallback((sourceId: string, targetId: string) => {
    setTasks(current => {
      const sourceIndex = current.findIndex(task => task.id === sourceId && 'queue' in task && task.queue === 'local' && task.status === 'queued');
      const targetIndex = current.findIndex(task => task.id === targetId && 'queue' in task && task.queue === 'local' && task.status === 'queued');
      if (sourceIndex === -1 || targetIndex === -1 || sourceIndex === targetIndex) return current;
      const reordered = [...current];
      const [moved] = reordered.splice(sourceIndex, 1);
      reordered.splice(targetIndex, 0, moved);
      return reordered;
    });
  }, []);
  return <aside className="comfy-sidebar" data-open={open} aria-label="生成任务进度">
    <button className="comfy-sidebar-toggle" aria-expanded={open} aria-controls="comfy-task-list"
      aria-label={open ? '收起任务进度' : '展开任务进度'} onClick={() => {
        setOpen(!open); localStorage.setItem('nora-task-sidebar', open ? 'closed' : 'open');
      }}><span aria-hidden="true">{open ? '‹' : '›'}</span><span className="comfy-rail-label">任务进度</span><span className="comfy-rail-count">{active}</span></button>
    <div id="comfy-task-list" className="comfy-task-content" hidden={!open}>
      <section className="comfy-queue" aria-label="远端队列">
      <div className="comfy-task-heading"><strong>远端队列</strong></div>
      <div className="comfy-node-heading"><nav className="underline-tabs comfy-node-tabs" aria-label="远端节点">
        {nodes.map((node, index) => <button key={node.url} aria-current={node.url === selectedNode?.url ? 'page' : undefined}
          onClick={() => setSelectedUrl(node.url)}><span className="comfy-node-dot" data-preview={index === 0 ? 'connected' : 'disconnected'}
            aria-hidden="true" title="连接状态样式示意，尚未接入监控" />{node.name}</button>)}
      </nav>
      <div className="comfy-node-counts" aria-label="当前节点任务数量">
        <span>进行中 <strong>{nodeRunning}</strong></span><span>队列中 <strong>{nodeQueued}</strong></span>
      </div></div>
      <div className="comfy-queue-body" key={selectedNode?.url}>
      {visibleTasks.length === 0 && <p className="comfy-empty">{connection === 'connected' ? '该节点暂无已登记任务' : '等待任务状态…'}</p>}
      <div className="comfy-task-items">{visibleTasks.map(task => <TaskCard key={task.id} task={task} />)}</div>
      </div>
      </section>
      <section className="comfy-queue" aria-label="本地队列">
        <div className="comfy-task-heading comfy-local-heading"><strong>本地队列</strong>
          <nav className="underline-tabs comfy-local-tabs" aria-label="本地任务分类">
            {(Object.keys(localQueueStates) as LocalQueueTask['status'][]).map(status => <button key={status}
              aria-current={localCategory === status ? 'page' : undefined} onClick={() => setLocalCategory(status)}>{localQueueStates[status]}（{allLocalTasks.filter(task => task.status === status).length}）</button>)}
          </nav>
        </div>
        <div className="comfy-queue-body" key={localCategory}>
          {localTasks.length === 0 && <p className="comfy-empty">暂无{localQueueStates[localCategory]}任务</p>}
          <div className="comfy-task-items">{localTasks.map((task, index) => <LocalQueueCard key={task.id} task={task}
            position={task.status === 'queued' ? index + 1 : undefined}
            onReorder={task.status === 'queued' ? reorderLocal : undefined} />)}</div>
        </div>
      </section>
    </div>
  </aside>;
}
