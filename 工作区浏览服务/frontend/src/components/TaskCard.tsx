import { useEffect, useState } from 'react';
import './TaskCard.css';

export interface LocalTask {
  source?: 'local';
  id: string; project: string; title: string; task_type: keyof typeof stages;
  status: string; connection: string; node: string | null; remote_url: string;
  progress: { value: number; max: number } | null;
  error: string | null; collected: number; expected: number;
  created_at: string; started_at?: string | null;
  director_progress?: { segment: number; segment_total: number; phase_label: string };
  segment_warning?: string | null;
}

export interface ExternalTask {
  source: 'external';
  id: string; prompt_id: string; remote_url: string; status: string;
  queue_position: number | null;
}

export type Task = LocalTask | ExternalTask;

const stages = { image: '图片生成', 'image-upscale': '图片超分',
  'video-first-pass': '视频一采', 'video-second-pass': '视频二采', 'video-postprocess': '视频后处理' } as const;

function clockText(seconds: number) {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `${pad(Math.floor(seconds / 3600))}小时:${pad(Math.floor(seconds / 60) % 60)}分钟:${pad(seconds % 60)}秒`;
}

export function TaskCard({ task }: { task: Task }) {
  const external = task.source === 'external';
  const queued = task.status === 'queued' || task.status === 'submitting';
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    if (external) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [external]);
  const submitted = task.source !== 'external' ? new Date(task.created_at) : null;
  return <section className="comfy-task" data-source={external ? 'external' : 'local'}>
    <div className="comfy-task-top">
      <div className="comfy-task-identity">
        <span className="comfy-task-source">{external ? '其他设备提交' : '本机提交'}</span>
        {task.source !== 'external' && <>
          <span className="comfy-task-project" title={task.project}>{task.project}</span>
          <span className="comfy-task-type">{stages[task.task_type]}</span>
        </>}
      </div>
      <strong className="comfy-task-status" data-status={queued ? 'queued' : 'running'}>
        {queued ? '排队中' : '进行中'}
      </strong>
    </div>
    {task.source === 'external' ? <>
      <div className="comfy-external-title">
        <h2>任务ID：<code>{task.prompt_id}</code></h2>
        {task.queue_position !== null && <span className="comfy-task-position" aria-label="队列位置">第 {task.queue_position} 位</span>}
      </div>
    </> : <>
      <div className="comfy-local-title">
        <h2>{task.title}</h2>
        <div className="comfy-task-timing">
          {queued && submitted ? <>
            <time dateTime={task.created_at}>提交时间：{clockText(submitted.getHours() * 3600 + submitted.getMinutes() * 60 + submitted.getSeconds())}</time>
            <span>等待时长：{clockText(Math.max(0, Math.floor((now - submitted.getTime()) / 1000)))}</span>
          </> : <span>运行时长：{task.started_at ? clockText(Math.max(0, Math.floor((now - new Date(task.started_at).getTime()) / 1000))) : '待获取开始时间'}</span>}
        </div>
      </div>
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
