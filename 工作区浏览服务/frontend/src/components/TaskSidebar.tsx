import { useEffect, useState } from 'react';
import { TaskCard, type Task } from './TaskCard';
import './TaskSidebar.css';

interface RemoteNode { url: string; name: string }

const activeStates = new Set(['submitting', 'queued', 'running', 'collecting']);

export function TaskSidebar() {
  const [open, setOpen] = useState(() => localStorage.getItem('nora-task-sidebar') === 'open');
  const [tasks, setTasks] = useState<Task[]>([]);
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
  const visibleTasks = tasks.filter(task => task.remote_url === selectedNode?.url);
  const nodeActive = visibleTasks.filter(task => activeStates.has(task.status)).length;
  const nodeCompleted = visibleTasks.filter(task => task.status === 'completed').length;
  return <aside className="comfy-sidebar" data-open={open} aria-label="生成任务进度">
    <button className="comfy-sidebar-toggle" aria-expanded={open} aria-controls="comfy-task-list"
      aria-label={open ? '收起任务进度' : '展开任务进度'} onClick={() => {
        setOpen(!open); localStorage.setItem('nora-task-sidebar', open ? 'closed' : 'open');
      }}><span aria-hidden="true">{open ? '‹' : '›'}</span><span className="comfy-rail-label">任务进度</span><span className="comfy-rail-count">{active}</span></button>
    <div id="comfy-task-list" className="comfy-task-content" hidden={!open}>
      <section className="comfy-queue" aria-label="远端队列">
      <div className="comfy-task-heading"><strong>远端队列</strong><div className="comfy-task-counts">
        <span>{nodeActive} 项进行中</span><span>{nodeCompleted} 项已完成</span>
      </div></div>
      <nav className="underline-tabs comfy-node-tabs" aria-label="远端节点">
        {nodes.map(node => <button key={node.url} aria-current={node.url === selectedNode?.url ? 'page' : undefined}
          onClick={() => setSelectedUrl(node.url)}>{node.name}</button>)}
      </nav>
      <div className="comfy-queue-body" key={selectedNode?.url}>
      {visibleTasks.length === 0 && <p className="comfy-empty">{connection === 'connected' ? '该节点暂无已登记任务' : '等待任务状态…'}</p>}
      <div className="comfy-task-items">{visibleTasks.map(task => <TaskCard key={task.id} task={task} />)}</div>
      </div>
      </section>
      <section className="comfy-queue" aria-label="本地队列">
        <div className="comfy-task-heading"><strong>本地队列</strong></div>
        <div className="comfy-queue-body" />
      </section>
    </div>
  </aside>;
}
