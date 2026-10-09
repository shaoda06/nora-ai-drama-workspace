import { useEffect, useState } from 'react';
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

export function LocalQueueCard({ task, onReorder }: {
  task: LocalQueueTask; onReorder?: (sourceId: string, targetId: string) => void;
}) {
  const [dragging, setDragging] = useState(false);
  useEffect(() => {
    if (!dragging || !onReorder) return;
    const move = (event: PointerEvent) => {
      const target = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>('.local-queue-card');
      if (target) onReorder(task.id, target.dataset.localTaskId!);
    };
    const end = () => setDragging(false);
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', end);
    document.addEventListener('pointercancel', end);
    return () => {
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', end);
      document.removeEventListener('pointercancel', end);
    };
  }, [dragging, onReorder, task.id]);
  return <section className="local-queue-card" data-local-task-id={task.id} data-dragging={dragging}>
    <div className="local-queue-card-top">
      <div className="local-queue-card-identity">
        {onReorder && <button type="button" className="local-queue-drag-handle" title="拖动卡片调整排队顺序" aria-label="拖动排序"
          onPointerDown={event => {
            event.preventDefault();
            setDragging(true);
          }}>⠿</button>}
        <span className="local-queue-card-source">本机提交</span>
        <span className="local-queue-card-project" title={task.project}>{task.project}</span>
        <span className="local-queue-card-type">{taskTypeLabels[task.task_type]}</span>
      </div>
      <strong className="local-queue-card-status" data-status={task.status}>{localQueueStates[task.status]}</strong>
    </div>
    <div className="local-queue-card-body">
      <div className="local-queue-card-description">
        <h2>{task.title}</h2>
        <p className="local-queue-card-session" title={task.source_session_name}>来源会话：{task.source_session_name}</p>
      </div>
      <div className="local-queue-card-actions" aria-label="本地任务操作" title="样式预览，尚未接入实际调度">
        <button type="button" disabled>暂停</button>
        <button type="button" disabled>立即提交</button>
        <button type="button" disabled>插队</button>
      </div>
    </div>
  </section>;
}
