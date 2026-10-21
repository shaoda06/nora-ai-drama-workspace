import { PointerTooltip } from './PointerTooltip';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { TaskCard, type Task } from './TaskCard';
import { LocalQueueCard, localQueueStates, type LocalQueueTask } from './LocalQueueCard';
import { TaskDetailDialog } from './TaskDetailDialog';
import { TaskHistory } from './TaskHistory';
import { NodeEditor } from './NodeEditor';
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
  const [editingNodes, setEditingNodes] = useState(false);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [tasks, setTasks] = useState<(Task | LocalQueueTask)[]>([]);
  const [localCategory, setLocalCategory] = useState<keyof typeof localQueueStates>('queued');
  const [localRows, setLocalRows] = useState<LocalQueueTask[]>([]);
  const localRef = useRef<LocalQueueTask[]>([]);
  const dragToken = useRef<string | null>(null);
  const dragUrl = useRef<string | null>(null);
  const dragTimer = useRef<number | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState('');
  const [nodes, setNodes] = useState<RemoteNode[]>([]);
  const [counts, setCounts] = useState<Record<string, { queued: number; paused: number; history: number }>>({});
  const [historyUpdates, setHistoryUpdates] = useState<Record<string, string | null>>({});
  const [selectedUrl, setSelectedUrl] = useState<string | null>(null);
  const taskQuery = useQuery({
    queryKey: ['task-sidebar'],
    queryFn: async ({ signal }) => {
      const response = await fetch('/api/comfy/tasks?include_history=false', { signal });
      if (!response.ok) throw new Error('任务列表刷新失败');
      return response.json();
    },
    staleTime: 0,
    refetchInterval: 3000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: 'always',
  });
  const connection = taskQuery.isError ? 'reconnecting' : taskQuery.data ? 'connected' : 'loading';
  const { refetch: refreshTasks } = taskQuery;
  useEffect(() => {
    const snapshot = taskQuery.data;
    if (snapshot) {
      setTasks(snapshot.tasks);
      const incoming: LocalQueueTask[] = snapshot.local_tasks ?? snapshot.tasks.filter((task: Task | LocalQueueTask) => 'queue' in task);
      if (!dragToken.current) {
        localRef.current = incoming;
        setLocalRows(incoming);
      }
      setNodes(snapshot.remote_nodes);
      setCounts(snapshot.local_counts);
      setHistoryUpdates(snapshot.history_updated_at);
    }
  }, [taskQuery.data]);
  useEffect(() => {
    return () => {
      window.clearInterval(dragTimer.current);
      if (dragToken.current) void fetch('/api/comfy/drag', { method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: dragToken.current, release: true }) });
    };
  }, []);
  const selectedNode = nodes.find(node => node.url === selectedUrl) ?? nodes[0];
  const liveNodes = nodes.filter(node => node.connection === 'connected' && !node.error && !node.queue_error && node.running_count !== null);
  const remoteActivity = connection !== 'connected' ? 'unknown'
    : liveNodes.some(node => node.running_count! > 0) ? 'running'
    : nodes.length > 0 && liveNodes.length === nodes.length ? 'idle' : 'unknown';
  const remoteActivityLabel = remoteActivity === 'running' ? '远端有任务正在执行'
    : remoteActivity === 'idle' ? '远端当前没有进行中任务' : '远端执行状态暂未确认';
  const category = (task: LocalQueueTask): keyof typeof localQueueStates => task.category ??
    (task.status === 'queued' || task.status === 'local_queued' ? 'queued' : task.status === 'paused' ? 'paused' : 'history');
  const nodeRows = localRows.filter(task => task.remote_url === selectedNode?.url);
  const localCounts = { queued: counts[selectedNode?.url]?.queued ?? 0, paused: counts[selectedNode?.url]?.paused ?? 0,
    history: Object.values(counts).reduce((total, count) => total + count.history, 0) };
  const historyUpdatedAt = Object.values(historyUpdates).reduce<string | null>((latest, value) =>
    value && (!latest || Date.parse(value) > Date.parse(latest)) ? value : latest, null);
  const localTasks = nodeRows.filter(task => category(task) === localCategory);
  const localPositions = new Map(localTasks.filter(task => task.status === 'local_queued' || task.status === 'queued')
    .map((task, index) => [task.id, index + 1]));
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
    : selectedNode?.error ? selectedNode.error
    : selectedNode?.connection === 'reconnecting' ? selectedNode.updated_at
      ? '远端连接中断，显示上次队列，正在自动重连' : '远端暂未连接，正在自动重连'
    : selectedNode?.queue_error;
  const write = useCallback(async (path: string, value: unknown, method = 'POST') => {
    const response = await fetch(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
    const data = await response.json();
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail));
    return data;
  }, []);
  const reload = useCallback(async () => {
    const snapshot = (await refreshTasks({ throwOnError: true })).data!;
    localRef.current = snapshot.local_tasks;
    setLocalRows(snapshot.local_tasks);
    setTasks(snapshot.tasks);
    setCounts(snapshot.local_counts);
    setHistoryUpdates(snapshot.history_updated_at);
    return snapshot.local_tasks as LocalQueueTask[];
  }, [refreshTasks]);
  const action = useCallback(async (id: string, operation: string) => {
    setBusy(true); setActionError('');
    try { await write(`/api/comfy/tasks/${id}/action`, { action: operation }); await reload(); }
    catch (error) { setActionError((error as Error).message); }
    finally { setBusy(false); }
  }, [write, reload]);
  const transfer = useCallback(async (id: string, url: string) => {
    setBusy(true); setActionError('');
    try { await write(`/api/comfy/tasks/${id}/transfer`, { url }); await reload(); }
    catch (error) { setActionError((error as Error).message); }
    finally { setBusy(false); }
  }, [write, reload]);
  const startDrag = useCallback(async (id: string) => {
    if (dragToken.current) return false;
    setBusy(true); setActionError('');
    try {
      const url = selectedNode!.url;
      const result = await write('/api/comfy/drag', { url });
      dragToken.current = result.token;
      dragUrl.current = url;
      const fresh = await reload();
      if (!fresh.some(task => task.id === id && task.status === 'local_queued' && task.remote_url === url)) {
        await write('/api/comfy/drag', { token: result.token, release: true });
        dragToken.current = null;
        throw new Error('这项任务已经开始提交，请选择其他排队任务');
      }
      dragTimer.current = window.setInterval(() => {
        void write('/api/comfy/drag', { token: dragToken.current }).catch(error => setActionError(error.message));
      }, 5000);
      return true;
    } catch (error) {
      if (dragToken.current) {
        try { await write('/api/comfy/drag', { token: dragToken.current, release: true }); }
        catch (releaseError) { setActionError((releaseError as Error).message); }
        dragToken.current = null;
      }
      dragUrl.current = null;
      setActionError((error as Error).message); return false;
    } finally { setBusy(false); }
  }, [write, reload, selectedNode?.url]);
  const endDrag = useCallback(async () => {
    const token = dragToken.current;
    if (!token) return;
    setBusy(true);
    try { await write('/api/comfy/order', { token, ids: localRef.current.filter(task => task.status === 'local_queued' && task.remote_url === dragUrl.current).map(task => task.id) }, 'PUT'); }
    catch (error) { setActionError((error as Error).message); }
    finally {
      window.clearInterval(dragTimer.current);
      try { await write('/api/comfy/drag', { token, release: true }); }
      catch (error) { setActionError((error as Error).message); }
      dragToken.current = null;
      dragUrl.current = null;
      try { await reload(); } catch (error) { setActionError((error as Error).message); }
      setBusy(false);
    }
  }, [write, reload]);
  const reorderLocal = useCallback((sourceId: string, targetId: string) => {
    const current = localRef.current;
    const source = current.findIndex(task => task.id === sourceId && task.status === 'local_queued' && task.remote_url === dragUrl.current);
    const target = current.findIndex(task => task.id === targetId && task.status === 'local_queued' && task.remote_url === dragUrl.current);
    if (source === -1 || target === -1 || source === target) return;
    const next = [...current];
    const [moved] = next.splice(source, 1); next.splice(target, 0, moved);
    localRef.current = next;
    setLocalRows(next);
  }, []);
  return <><aside className="comfy-sidebar" data-open={open} aria-label="生成任务进度">
    <button className="comfy-sidebar-toggle" aria-expanded={open} aria-controls="comfy-task-list"
      aria-label={open ? '收起任务进度' : '展开任务进度'} onClick={() => {
        setOpen(!open);
      }}><span aria-hidden="true">{open ? '‹' : '›'}</span><span className="comfy-rail-label">任务进度</span>
      <PointerTooltip text={remoteActivityLabel}><span className="comfy-rail-runner" data-state={remoteActivity} role="img" aria-label={remoteActivityLabel}>
        <svg width="24" height="32" viewBox="0 0 24 32" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <g className="comfy-runner-body"><circle cx="12" cy="5" r="2.5" /><path d="M12 9v9" />
            <g transform="translate(12 11)"><path className="comfy-runner-arm-back" d="M0 0v5l3 2" /><path className="comfy-runner-arm" d="M0 0v5l3 2" /></g>
            <g transform="translate(12 18)"><path className="comfy-runner-leg-back" d="M0 0v6l3 3" /><path className="comfy-runner-leg" d="M0 0v6l3 3" /></g>
          </g>
        </svg>
      </span></PointerTooltip>
      <span className="comfy-rail-summary">
        <span className="comfy-rail-values">
          {(Object.keys(localQueueStates) as (keyof typeof localQueueStates)[]).map(status => <span key={status}>{status === 'queued' ? '队列中' : localQueueStates[status]} <b>{localCounts[status]}</b></span>)}
        </span>
      </span></button>
    <div id="comfy-task-list" className="comfy-task-content" data-view={editingNodes ? 'nodes' : 'tasks'} hidden={!open}>
      {editingNodes ? <NodeEditor close={() => setEditingNodes(false)} /> : <>
      <div className="comfy-node-heading"><nav className="underline-tabs comfy-node-tabs" aria-label="远端节点">
        {nodes.map(node => <PointerTooltip key={node.url} text={connection === 'connected' ? nodeConnectionLabels[node.connection] : '等待后台连接恢复'}><button  aria-current={node.url === selectedNode?.url ? 'page' : undefined}
          disabled={busy || dragToken.current !== null}
          onClick={() => { setSelectedUrl(node.url); setActionError(''); }} >
          <span className="comfy-node-dot" data-connection={connection === 'connected' ? node.connection : 'connecting'}
            aria-hidden="true" />{node.name}</button></PointerTooltip>)}
      </nav><button className="comfy-node-edit" disabled={busy || dragToken.current !== null}
        onClick={() => setEditingNodes(true)}>编辑</button></div>
      <section className="comfy-queue" aria-label="远端队列">
      <div className="comfy-task-heading"><strong>远端</strong>
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
        <div className="comfy-task-heading comfy-local-heading"><strong>本地</strong>
          <nav className="underline-tabs comfy-local-tabs" aria-label="本地任务分类">
            {(Object.keys(localQueueStates) as (keyof typeof localQueueStates)[]).map(status => <button key={status}
              aria-current={localCategory === status ? 'page' : undefined} disabled={busy || dragToken.current !== null}
              onClick={() => setLocalCategory(status)}>{localQueueStates[status]}（{localCounts[status]}）</button>)}
          </nav>
        </div>
        {localCategory === 'history' ? <TaskHistory
          updatedAt={historyUpdatedAt} total={localCounts.history} onDetails={setDetailId} /> :
        <div className="comfy-queue-body" key={`${selectedNode?.url}:${localCategory}`}>
          {actionError && <p className="comfy-task-warning" role="alert">{actionError}</p>}
          {localTasks.length === 0 && <p className="comfy-empty">暂无{localQueueStates[localCategory]}任务</p>}
          <div className="comfy-task-items">{localTasks.map(task => <LocalQueueCard key={task.id} task={task}
            position={localPositions.get(task.id)}
            busy={busy || dragToken.current !== null} onAction={action} onTransfer={transfer} onDragStart={startDrag} onDragEnd={endDrag} onDetails={setDetailId}
            onReorder={task.status === 'local_queued' ? reorderLocal : undefined} />)}</div>
        </div>}
      </section>
      </>}
    </div>
  </aside>{detailId && <TaskDetailDialog key={detailId} id={detailId}
    updatedAt={historyUpdatedAt ?? undefined}
    nodes={nodes} close={() => setDetailId(null)} openTask={setDetailId} />}</>;
}
