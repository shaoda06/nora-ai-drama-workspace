import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { taskTypeLabels } from './TaskCard';
import './LocalQueueCard.css';

export const localQueueStates = { queued: '排队中', paused: '暂停中', completed: '已完成' } as const;

export interface LocalQueueTask {
  queue: 'local';
  id: string; project: string; title: string;
  task_type: keyof typeof taskTypeLabels;
  status: keyof typeof localQueueStates;
  source_session_name: string;
}

export function LocalQueueCard({ task, position, onReorder }: {
  task: LocalQueueTask; position?: number; onReorder?: (sourceId: string, targetId: string) => void;
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
      landing.onfinish = () => setDrag(null);
    };
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', end);
    document.addEventListener('pointercancel', end);
    return () => {
      landing?.cancel();
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', end);
      document.removeEventListener('pointercancel', end);
    };
  }, [drag, onReorder, task.id]);
  const content = <>
    <div className="local-queue-card-top">
      <div className="local-queue-card-identity">
        <span className="local-queue-card-source">本机提交</span>
        <span className="local-queue-card-project" title={task.project}>{task.project}</span>
        <span className="local-queue-card-type">{taskTypeLabels[task.task_type]}</span>
      </div>
      <strong className="local-queue-card-status" data-status={task.status}>{localQueueStates[task.status]}{task.status === 'queued' && ` #${position}`}</strong>
    </div>
    <div className="local-queue-card-body">
      <div className="local-queue-card-description">
        <h2>{task.title}</h2>
        <p className="local-queue-card-session" title={task.source_session_name}>来源会话：{task.source_session_name}</p>
      </div>
      {task.status !== 'completed' && <div className="local-queue-card-actions" aria-label="本地任务操作" title="样式预览，尚未接入实际调度">
        <button type="button" disabled>立即提交</button>
        <button type="button" disabled>插队</button>
        <button type="button" disabled>{task.status === 'paused' ? '恢复' : '暂停'}</button>
        <button type="button" disabled>取消</button>
      </div>}
    </div>
  </>;
  return <>
    <section ref={cardRef} className="local-queue-card" data-local-task-id={task.id}
      data-sortable={!!onReorder} data-dragging={!!drag}
      onPointerDown={event => {
        if (!onReorder || drag || event.button !== 0 || (event.target as HTMLElement).closest('button')) return;
        event.preventDefault();
        const rect = event.currentTarget.getBoundingClientRect();
        setDrag({ pointerId: event.pointerId, offsetX: event.clientX - rect.left, offsetY: event.clientY - rect.top,
          left: rect.left, top: rect.top, width: rect.width, height: rect.height });
      }}>{content}</section>
    {drag && createPortal(<section ref={floatingRef} className="local-queue-card local-queue-card-floating"
      aria-hidden="true" style={{ width: drag.width, height: drag.height,
        transform: `translate(${drag.left}px, ${drag.top}px) scale(1.015)` }}>{content}</section>, document.body)}
  </>;
}
