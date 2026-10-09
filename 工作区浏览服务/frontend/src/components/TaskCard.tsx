import './TaskCard.css';

export interface LocalTask {
  source?: 'local';
  id: string; project: string; title: string; task_type: string; prompt_id: string | null;
  status: string; connection: string; node: string | null; remote_url: string;
  progress: { value: number; max: number } | null;
  error: string | null; notification: string; collected: number; expected: number; updated_at: string;
  director_progress?: { segment: number; segment_total: number; timeline_segment: number; phase_label: string };
  segment_warning?: string | null;
  notification_unknown?: number;
  segments?: { identity: string; index: number; check: string; error: string | null }[];
}

export interface ExternalTask {
  source: 'external';
  id: string; prompt_id: string; remote_url: string; status: string;
  created_at: string; queue_position: number | null;
  outputs_count?: number;
  error?: string;
}

export type Task = LocalTask | ExternalTask;

const states: Record<string, string> = {
  submitting: '正在提交', queued: '排队中', running: '执行中', collecting: '正在取回',
  completed: '已完成', failed: '执行失败', needs_attention: '待核对',
  collection_failed: '取回失败', submission_unknown: '提交未确认', rejected: '提交被拒绝',
};
const stages: Record<string, string> = { image: '图片生成', 'image-upscale': '图片超分',
  'video-first-pass': '视频一采', 'video-second-pass': '视频二采', 'video-postprocess': '视频后处理' };
const notifications: Record<string, string> = { waiting: '等待任务结果', waiting_idle: '等待会话空闲',
  waiting_connection: '等待Codex连接', sending: '正在通知会话', sent: '已通知原会话', delivery_unknown: '通知送达未确认' };

export function TaskCard({ task }: { task: Task }) {
  const external = task.source === 'external';
  return <section className="comfy-task" data-source={external ? 'external' : 'local'}>
    <div className="comfy-task-top">
      <span className="comfy-task-source">{external ? '其他设备提交' : '本机提交'}</span>
      <strong className="comfy-task-status" data-status={task.status}>
        {!external && task.status === 'completed' ? '已取回' : states[task.status] || task.status}
      </strong>
    </div>
    {task.source === 'external' ? <>
      <h2>任务 <code>{task.prompt_id.slice(0, 8)}</code></h2>
      <dl className="comfy-task-facts">
        <div><dt>提交时间</dt><dd><time dateTime={task.created_at}>{new Date(task.created_at).toLocaleString('zh-CN')}</time></dd></div>
        {task.queue_position !== null && <div><dt>排队位置</dt><dd>第 {task.queue_position} 位</dd></div>}
        {task.outputs_count !== undefined && <div><dt>生成结果</dt><dd>{task.outputs_count} 个</dd></div>}
      </dl>
      {task.error && <p className="comfy-task-warning">{task.error}</p>}
      <details className="comfy-task-details"><summary>任务详情</summary>
        <p className="comfy-task-id">任务ID：<code>{task.prompt_id}</code></p>
      </details>
    </> : <>
      <p className="comfy-task-project">{task.project} · {stages[task.task_type] || task.task_type}</p>
      <h2>{task.title}</h2>
      {task.node && <p>当前阶段：{task.node}</p>}
      {task.director_progress && <p>本轮第 {task.director_progress.segment} / {task.director_progress.segment_total} 段
        · {task.director_progress.phase_label}</p>}
      {task.progress && task.progress.max > 0 && <div className="comfy-progress">
        <div className="comfy-progress-label"><span>当前阶段采样</span><strong>{task.progress.value} / {task.progress.max} 步</strong></div>
        <progress aria-label="当前节点步数" value={task.progress.value} max={task.progress.max} />
      </div>}
      {task.expected > 0 && <p className="comfy-task-collected">成果取回 <strong>{task.collected} / {task.expected}</strong></p>}
      {task.connection === 'reconnecting' && <p className="comfy-task-warning">远端连接恢复中，进度可能滞后</p>}
      {task.error && <p className="comfy-task-warning">{task.error}</p>}
      {task.segment_warning && <p className="comfy-task-warning">{task.segment_warning}</p>}
      <details className="comfy-task-details"><summary>任务详情{task.segments?.length ? ` · ${task.segments.length} 段已取回` : ''}</summary>
        {task.director_progress && <p>原组序：{task.director_progress.timeline_segment}</p>}
        {task.prompt_id && <p className="comfy-task-id">任务ID：<code>{task.prompt_id}</code></p>}
        {task.segments && <ul className="comfy-segments">{task.segments.map(segment => <li key={segment.identity}>
          <strong>{segment.identity}</strong><span>{segment.check}</span>
          {segment.error && <span className="comfy-task-warning">{segment.error}</span>}
        </li>)}</ul>}
        <p className="comfy-notification">{notifications[task.notification] || task.notification}</p>
        {!!task.notification_unknown && <p className="comfy-task-warning">另有 {task.notification_unknown} 条事件送达未确认，请在原会话核对</p>}
      </details>
      <time className="comfy-task-updated" dateTime={task.updated_at}>更新于 {new Date(task.updated_at).toLocaleString('zh-CN')}</time>
    </>}
  </section>;
}
