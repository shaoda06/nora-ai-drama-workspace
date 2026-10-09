import './TaskCard.css';

export interface LocalTask {
  source?: 'local';
  id: string; project: string; title: string; task_type: keyof typeof stages;
  status: string; connection: string; node: string | null; remote_url: string;
  progress: { value: number; max: number } | null;
  error: string | null; collected: number; expected: number;
  director_progress?: { segment: number; segment_total: number; phase_label: string };
  segment_warning?: string | null;
}

export interface ExternalTask {
  source: 'external';
  id: string; prompt_id: string; remote_url: string; status: string;
  queue_position: number | null;
}

export type Task = LocalTask | ExternalTask;

const states: Record<string, string> = {
  submitting: '正在提交', queued: '排队中', running: '执行中', collecting: '正在取回',
  completed: '已完成', failed: '执行失败', needs_attention: '待核对',
  collection_failed: '取回失败', submission_unknown: '提交未确认', rejected: '提交被拒绝',
};
const stages = { image: '图片生成', 'image-upscale': '图片超分',
  'video-first-pass': '视频一采', 'video-second-pass': '视频二采', 'video-postprocess': '视频后处理' } as const;

export function TaskCard({ task }: { task: Task }) {
  const external = task.source === 'external';
  return <section className="comfy-task" data-source={external ? 'external' : 'local'}>
    <div className="comfy-task-top">
      <div className="comfy-task-identity">
        <span className="comfy-task-source">{external ? '其他设备提交' : '本机提交'}</span>
        {task.source !== 'external' && <>
          <span className="comfy-task-project" title={task.project}>{task.project}</span>
          <span className="comfy-task-type">{stages[task.task_type]}</span>
        </>}
      </div>
      <strong className="comfy-task-status" data-status={task.status}>
        {!external && task.status === 'completed' ? '已取回' : states[task.status] || task.status}
      </strong>
    </div>
    {task.source === 'external' ? <>
      <div className="comfy-external-title">
        <h2>任务ID：<code>{task.prompt_id}</code></h2>
        {task.queue_position !== null && <span className="comfy-task-position" aria-label="队列位置">第 {task.queue_position} 位</span>}
      </div>
    </> : <>
      <h2>{task.title}</h2>
      <details className="comfy-task-details"><summary>任务详情</summary>
      {task.node && <p>当前阶段：{task.node}</p>}
      {task.director_progress && <p>本轮第 {task.director_progress.segment} / {task.director_progress.segment_total} 段
        · {task.director_progress.phase_label}</p>}
      {task.progress && task.progress.max > 0 && <div className="comfy-progress">
        <div className="comfy-progress-label"><span>当前阶段采样</span><strong>{task.progress.value} / {task.progress.max} 步</strong></div>
        <progress aria-label="当前节点步数" value={task.progress.value} max={task.progress.max} />
      </div>}
      {task.expected > 0 && <p className="comfy-task-collected">成果取回 <strong>{task.collected} / {task.expected}</strong></p>}
      </details>
      {task.connection === 'reconnecting' && <p className="comfy-task-warning">远端连接恢复中，进度可能滞后</p>}
      {task.error && <p className="comfy-task-warning">{task.error}</p>}
      {task.segment_warning && <p className="comfy-task-warning">{task.segment_warning}</p>}
    </>}
  </section>;
}
