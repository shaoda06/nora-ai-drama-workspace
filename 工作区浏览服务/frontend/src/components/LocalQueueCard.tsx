import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { taskTypeLabels } from './TaskCard';
import './LocalQueueCard.css';

export const localQueueStates = { queued: '排队中', paused: '暂停中', history: '历史' } as const;
const statusLabels: Record<string, string> = { local_queued: '排队中', queued: '排队中', paused: '暂停中',
  preparing: '准备提交', submitting: '提交中', collecting: '取回中', completed: '已完成',
  failed: '生成失败', rejected: '提交被拒绝', collection_failed: '取回失败',
  needs_attention: '状态待核对', submission_unknown: '提交结果待核对', cancelled: '已取消' };

export interface LocalQueueTask {
  queue: 'local';
  id: string; project: string; title: string;
  task_type: keyof typeof taskTypeLabels;
  status: string; category?: keyof typeof localQueueStates;
  source_session_name?: string; error?: string | null; notification?: string;
  queue_position?: number | null; collected?: number; expected?: number;
}

export function LocalQueueCard({ task, position, onReorder, onAction, busy, onDragStart, onDragEnd }: {
  task: LocalQueueTask; position?: number; onReorder?: (sourceId: string, targetId: string) => void;
  onAction?: (id: string, action: string) => void; busy?: boolean;
  onDragStart?: (id: string) => Promise<boolean>; onDragEnd?: () => void;
}) {
  const cardRef = useRef<HTMLElement>(null);
  const floatingRef = useRef<HTMLElement>(null);
  const [drag, setDrag] = useState<{
    pointerId: number; offsetX: number; offsetY: number;
    left: number; top: number; width: number; height: number;
  } | null>(null);
  useEffect(() => {
    if (!drag || !onReorder) return;
    let left = drag.left;
    let top = drag.top;
    let dropping = false;
    let landing: Animation | undefined;
    const move = (event: PointerEvent) => {
      if (event.pointerId !== drag.pointerId || dropping) return;
      left = event.clientX - drag.offsetX;
      top = event.clientY - drag.offsetY;
      floatingRef.current!.style.transform = `translate(${left}px, ${top}px) scale(1.015)`;
      const target = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>('.local-queue-card');
      if (target) onReorder(task.id, target.dataset.localTaskId!);
    };
    const end = (event: PointerEvent) => {
      if (event.pointerId !== drag.pointerId || dropping) return;
      dropping = true;
      const destination = cardRef.current!.getBoundingClientRect();
      landing = floatingRef.current!.animate([
        { transform: `translate(${left}px, ${top}px) scale(1.015)` },
        { transform: `translate(${destination.left}px, ${destination.top}px) scale(1)`, boxShadow: '0 0 0 rgba(20, 58, 48, 0)' },
      ], { duration: 180, easing: 'cubic-bezier(.2,.8,.2,1)', fill: 'forwards' });
      landing.onfinish = () => { setDrag(null); onDragEnd?.(); };
    };
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', end);
    document.addEventListener('pointercancel', end);
    const blur = () => end({ pointerId: drag.pointerId } as PointerEvent);
    window.addEventListener('blur', blur);
    return () => {
      landing?.cancel();
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', end);
      document.removeEventListener('pointercancel', end);
      window.removeEventListener('blur', blur);
    };
  }, [drag, onReorder, onDragEnd, task.id]);
  const content = <>
    <div className="local-queue-card-top">
      <div className="local-queue-card-identity">
        <span className="local-queue-card-source">本机提交</span>
        <span className="local-queue-card-project" title={task.project}>{task.project}</span>
        <span className="local-queue-card-type">{taskTypeLabels[task.task_type]}</span>
      </div>
      <strong className="local-queue-card-status" data-status={task.status}>{statusLabels[task.status] || task.status}{position !== undefined && ` #${position}`}</strong>
    </div>
    <div className="local-queue-card-body">
      <div className="local-queue-card-description">
        <h2>{task.title}</h2>
        <p className="local-queue-card-session" title={task.source_session_name}>来源会话：{task.source_session_name || '会话名称暂不可用'}</p>
      </div>
      {['local_queued', 'queued', 'paused'].includes(task.status) && <div className="local-queue-card-actions" aria-label="本地任务操作">
        <button type="button" data-tone="green" disabled={busy || !onAction} onClick={() => onAction?.(task.id, 'immediate')}>立即提交</button>
        <button type="button" data-tone="blue" disabled={busy || !onAction} onClick={() => onAction?.(task.id, 'insert')}>插队</button>
        <button type="button" data-tone={task.status === 'paused' ? 'green' : 'orange'} disabled={busy || !onAction}
          onClick={() => onAction?.(task.id, task.status === 'paused' ? 'resume' : 'pause')}>{task.status === 'paused' ? '恢复' : '暂停'}</button>
        <button type="button" data-tone="red" disabled={busy || !onAction} onClick={() => onAction?.(task.id, 'cancel')}>取消</button>
      </div>}
    </div>
    {task.category === 'history' && task.expected !== undefined && <p className="local-queue-card-session">成果保存：{task.collected} / {task.expected}</p>}
    {task.error && <p className="local-queue-card-error">{task.error}</p>}
    {task.notification && ['waiting_connection', 'waiting_idle', 'delivery_unknown', 'sending'].includes(task.notification) && <p className="local-queue-card-session">
      通知：{task.notification === 'delivery_unknown' ? '送达状态不明，等待确认' : '等待发送'}</p>}
  </>;
  return <>
    <section ref={cardRef} className="local-queue-card" data-local-task-id={task.id}
      data-sortable={!!onReorder} data-dragging={!!drag}
      onPointerDown={async event => {
        if (!onReorder || busy || drag || event.button !== 0 || (event.target as HTMLElement).closest('button')) return;
        event.preventDefault();
        const rect = event.currentTarget.getBoundingClientRect();
        const pointerId = event.pointerId, clientX = event.clientX, clientY = event.clientY;
        let released = false;
        const release = () => { released = true; };
        document.addEventListener('pointerup', release, { once: true });
        document.addEventListener('pointercancel', release, { once: true });
        window.addEventListener('blur', release, { once: true });
        const accepted = !onDragStart || await onDragStart(task.id);
        document.removeEventListener('pointerup', release);
        document.removeEventListener('pointercancel', release);
        window.removeEventListener('blur', release);
        if (!accepted) return;
        if (released) { onDragEnd?.(); return; }
        setDrag({ pointerId, offsetX: clientX - rect.left, offsetY: clientY - rect.top,
          left: rect.left, top: rect.top, width: rect.width, height: rect.height });
      }}>{content}</section>
    {drag && createPortal(<section ref={floatingRef} className="local-queue-card local-queue-card-floating"
      aria-hidden="true" style={{ width: drag.width, height: drag.height,
        transform: `translate(${drag.left}px, ${drag.top}px) scale(1.015)` }}>{content}</section>, document.body)}
  </>;
}
