import { useEffect, useState } from 'react';
import './TaskSidebar.css';

interface Task {
  id: string; project: string; title: string; task_type: string; prompt_id: string | null;
  status: string; connection: string; node: string | null;
  progress: { value: number; max: number } | null;
  error: string | null; notification: string; collected: number; expected: number; updated_at: string;
  director_progress?: { segment: number; segment_total: number; timeline_segment: number; phase_label: string };
  segment_warning?: string | null;
  notification_unknown?: number;
  segments?: { identity: string; index: number; check: string; error: string | null }[];
}

const states: Record<string, string> = {
  submitting: '正在提交', queued: '排队中', running: '执行中', collecting: '正在取回',
  completed: '已取回', failed: '执行失败', needs_attention: '待核对',
  collection_failed: '取回失败', submission_unknown: '提交未确认', rejected: '提交被拒绝',
};
const stages: Record<string, string> = { image: '图片生成', 'image-upscale': '图片超分',
  'video-first-pass': '视频一采', 'video-second-pass': '视频二采', 'video-postprocess': '视频后处理' };
const notifications: Record<string, string> = { waiting: '等待任务结果', waiting_idle: '等待会话空闲',
  waiting_connection: '等待Codex连接', sending: '正在通知会话', sent: '已通知原会话', delivery_unknown: '通知送达未确认' };
const activeStates = new Set(['submitting', 'queued', 'running', 'collecting']);

export function TaskSidebar() {
  const [open, setOpen] = useState(() => localStorage.getItem('nora-task-sidebar') === 'open');
  const [tasks, setTasks] = useState<Task[]>([]);
  const [connection, setConnection] = useState<'loading' | 'connected' | 'reconnecting'>('loading');
  useEffect(() => {
    const source = new EventSource('/api/comfy/events');
    source.addEventListener('tasks', event => {
      setTasks(JSON.parse((event as MessageEvent).data).tasks);
      setConnection('connected');
    });
    source.onerror = () => setConnection('reconnecting');
    return () => source.close();
  }, []);
  const active = tasks.filter(task => activeStates.has(task.status)).length;
  return <aside className="comfy-sidebar" data-open={open} aria-label="生成任务进度">
    <button className="comfy-sidebar-toggle" aria-expanded={open} aria-controls="comfy-task-list"
      aria-label={open ? '收起任务进度' : '展开任务进度'} onClick={() => {
        setOpen(!open); localStorage.setItem('nora-task-sidebar', open ? 'closed' : 'open');
      }}><span aria-hidden="true">{open ? '‹' : '›'}</span><span className="comfy-rail-label">任务进度</span><span className="comfy-rail-count">{active}</span></button>
    <div id="comfy-task-list" className="comfy-task-content" hidden={!open}>
      <div className="comfy-task-heading"><strong>生成任务</strong><span>{active} 项进行中</span></div>
      <p className="comfy-stream-status" role="status">{connection === 'loading' ? '正在连接进度服务…' :
        connection === 'reconnecting' ? '进度连接中断，正在重连；保留上次状态' : '实时状态 · 仅查看'}</p>
      {tasks.length === 0 && <p className="comfy-empty">{connection === 'connected' ? '暂无已登记任务' : '等待任务状态…'}</p>}
      <div className="comfy-task-items">{tasks.map(task => <section className="comfy-task" key={task.id}>
        <div className="comfy-task-top"><span>{task.project}</span><strong data-status={task.status}>{states[task.status] || task.status}</strong></div>
        <h2>{task.title}</h2><p>{stages[task.task_type] || task.task_type}{task.node ? ` · 当前节点 ${task.node}` : ''}</p>
        {task.director_progress && <p>本轮第 {task.director_progress.segment} / {task.director_progress.segment_total} 段
          · 原组序 {task.director_progress.timeline_segment} · {task.director_progress.phase_label}</p>}
        {task.progress && task.progress.max > 0 && <div className="comfy-progress">
          <progress aria-label="当前节点步数" value={task.progress.value} max={task.progress.max} />
          <span>当前节点：{task.progress.value} / {task.progress.max} 步</span>
        </div>}
        {task.connection === 'reconnecting' && <p className="comfy-task-warning">远端连接恢复中，进度可能滞后</p>}
        {task.error && <p className="comfy-task-warning">{task.error}</p>}
        {task.segment_warning && <p className="comfy-task-warning">{task.segment_warning}</p>}
        {task.expected > 0 && <p>成果取回：{task.collected} / {task.expected}</p>}
        {task.segments && <ul className="comfy-segments">{task.segments.map(segment => <li key={segment.identity}>
          <strong>{segment.identity}</strong><span>{segment.check}</span>
          {segment.error && <span className="comfy-task-warning">{segment.error}</span>}
        </li>)}</ul>}
        <p className="comfy-notification">{notifications[task.notification] || task.notification}</p>
        {!!task.notification_unknown && <p className="comfy-task-warning">另有 {task.notification_unknown} 条事件送达未确认，请在原会话核对</p>}
        <time dateTime={task.updated_at}>更新于 {new Date(task.updated_at).toLocaleString('zh-CN')}</time>
      </section>)}</div>
    </div>
  </aside>;
}
