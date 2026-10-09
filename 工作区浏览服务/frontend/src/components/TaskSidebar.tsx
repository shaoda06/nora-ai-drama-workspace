import { useCallback, useEffect, useState } from 'react';
import { TaskCard, type Task } from './TaskCard';
import { LocalQueueCard, localQueueStates, type LocalQueueTask } from './LocalQueueCard';
import './TaskSidebar.css';

interface RemoteNode {
  url: string; name: string; connection: 'connecting' | 'connected' | 'reconnecting';
  queue: { prompt_id: string; status: 'running' | 'queued'; queue_position: number | null }[];
  running_count: number | null; queued_count: number | null; updated_at: string | null;
  error: string | null; queue_error: string | null;
}

const nodeConnectionLabels = { connecting: '正在连接', connected: '已连接', reconnecting: '连接中断，正在自动重连' };

export function TaskSidebar() {
  const [open, setOpen] = useState(false);
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
  const selectedNode = nodes.find(node => node.url === selectedUrl) ?? nodes[0];
  const allLocalTasks = tasks.filter((task): task is LocalQueueTask => 'queue' in task && task.queue === 'local');
  const localCounts = { queued: allLocalTasks.filter(task => task.status === 'queued').length,
    paused: allLocalTasks.filter(task => task.status === 'paused').length,
    completed: allLocalTasks.filter(task => task.status === 'completed').length };
  const localTasks = allLocalTasks.filter(task => task.status === localCategory);
  const registered = new Map(tasks.filter((task): task is Task => !('queue' in task && task.queue === 'local'))
    .filter(task => task.source !== 'external' && task.remote_url === selectedNode?.url && task.prompt_id)
    .map(task => [task.prompt_id, task]));
  const visibleTasks: Task[] = (selectedNode?.queue ?? []).map(entry => {
    const local = registered.get(entry.prompt_id);
    return local ? { ...local, status: entry.status } : {
      source: 'external', id: `${selectedNode.url}:${entry.prompt_id}`, remote_url: selectedNode.url, ...entry,
    };
  });
  const nodeWarning = connection !== 'connected' ? '后台连接恢复中，远端队列数据可能滞后'
    : selectedNode?.connection === 'reconnecting' ? selectedNode.updated_at
      ? '远端连接中断，显示上次队列，正在自动重连' : '远端暂未连接，正在自动重连'
    : selectedNode?.queue_error;
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
        setOpen(!open);
      }}><span aria-hidden="true">{open ? '‹' : '›'}</span><span className="comfy-rail-label">任务进度</span>
      <span className="comfy-rail-summary">
        {nodes.length === 0 && <span className="comfy-rail-group"><strong>远端节点</strong><span className="comfy-rail-values">正在读取</span></span>}
        {nodes.map(node => <span className="comfy-rail-group" key={node.url}
          title={`${node.name}：${connection === 'connected' ? nodeConnectionLabels[node.connection] : '后台连接恢复中'}${node.queue_error ? '，队列数据可能滞后' : ''}`}>
          <strong>{node.name}</strong>
          <span className="comfy-rail-values"><span>进行中 <b>{node.running_count ?? '—'}</b></span><span>队列中 <b>{node.queued_count ?? '—'}</b></span></span>
        </span>)}
        <span className="comfy-rail-group"><strong>本地队列</strong><span className="comfy-rail-values">
          {(Object.keys(localQueueStates) as LocalQueueTask['status'][]).map(status => <span key={status}>{localQueueStates[status]} <b>{localCounts[status]}</b></span>)}
        </span></span>
      </span></button>
    <div id="comfy-task-list" className="comfy-task-content" hidden={!open}>
      <section className="comfy-queue" aria-label="远端队列">
      <div className="comfy-task-heading"><strong>远端队列</strong></div>
      <div className="comfy-node-heading"><nav className="underline-tabs comfy-node-tabs" aria-label="远端节点">
        {nodes.map(node => <button key={node.url} aria-current={node.url === selectedNode?.url ? 'page' : undefined}
          onClick={() => setSelectedUrl(node.url)} title={connection === 'connected' ? nodeConnectionLabels[node.connection] : '等待后台连接恢复'}>
          <span className="comfy-node-dot" data-connection={connection === 'connected' ? node.connection : 'connecting'}
            aria-hidden="true" />{node.name}</button>)}
      </nav>
      <div className="comfy-node-counts" aria-label="当前节点任务数量">
        <span>进行中 <strong>{selectedNode?.running_count ?? '—'}</strong></span><span>队列中 <strong>{selectedNode?.queued_count ?? '—'}</strong></span>
      </div></div>
      <div className="comfy-queue-body" key={selectedNode?.url}>
      {nodeWarning && <p className="comfy-task-warning" role="status">{nodeWarning}</p>}
      {visibleTasks.length === 0 && <p className="comfy-empty">{!selectedNode ? '暂无配置的远端节点'
        : !selectedNode.updated_at ? selectedNode.connection === 'reconnecting' ? '尚未获取到远端队列' : '正在读取远端队列…'
        : '该节点暂无队列任务'}</p>}
      <div className="comfy-task-items">{visibleTasks.map(task => <TaskCard key={task.id} task={task} />)}</div>
      </div>
      </section>
      <section className="comfy-queue" aria-label="本地队列">
        <div className="comfy-task-heading comfy-local-heading"><strong>本地队列</strong>
          <nav className="underline-tabs comfy-local-tabs" aria-label="本地任务分类">
            {(Object.keys(localQueueStates) as LocalQueueTask['status'][]).map(status => <button key={status}
              aria-current={localCategory === status ? 'page' : undefined} onClick={() => setLocalCategory(status)}>{localQueueStates[status]}（{localCounts[status]}）</button>)}
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
