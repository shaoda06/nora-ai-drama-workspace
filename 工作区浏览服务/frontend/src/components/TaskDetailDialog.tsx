import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Dialog } from '../components';
import { clockText, localDateTime, taskTypeLabels } from './TaskCard';
import { statusLabels } from './LocalQueueCard';
import './TaskDetailDialog.css';

interface Event {
  id: number; time: string; stage: string; result: string; error?: string;
  source_url?: string; target_url?: string; url?: string; position?: number;
  path?: string; file?: string; identity?: string; collected?: number; notification_id?: string;
}
interface Detail {
  summary: {
    id: string; project: string; title: string; task_type: keyof typeof taskTypeLabels; status: string;
    source_session_name: string; enqueued_url: string; remote_url: string; prompt_id: string | null;
    created_at: string; submitted_at: string | null; started_at: string | null; ended_at: string | null;
    collected_at: string | null; failure_stage: string | null; error: string | null;
    collected: number; expected: number; notification: string;
    dispatch_attempt: number | null; preparation_attempt: number | null;
  };
  events: Event[];
  outputs: { path: string; name: string; identity: string | null; available: boolean; bytes: number | null;
    url: string | null; status: string; downloaded_at: string | null; error: string | null }[];
  records: { name: string; url: string }[];
  notification_batches: { id: string; task_count: number; status: string }[];
}
const stages: Record<string, string> = { enqueue: '登记入队', transfer: '转移节点', pause: '暂停', resume: '恢复排队',
  insert: '插队', immediate: '立即提交', cancel: '取消', reorder: '排序', preflight: '提交前检查',
  target_dependencies: '节点依赖检查', target_cache: '节点缓存检查', upload: '上传素材', upload_binding: '素材绑定',
  dispatch: '调度', submit: '提交远端', execution: '远端生成', collection: '取回全部成果', download: '保存成果',
  collection_retry: '重试取回', notification: '通知来源会话', restart: '后台恢复', reconcile: '核对远端状态', connection: '远端连接' };
const results: Record<string, string> = { accepted: '已接受', started: '开始', success: '成功', completed: '完成',
  running: '执行中', queued: '远端排队中', failed: '失败', collection_failed: '取回失败', rejected: '被拒绝',
  unknown: '结果待核对', pending: '等待发送', sent: '已发送', acknowledged: 'Agent 已确认', saved: '已保存',
  checked: '已检查', waiting_remote: '等待远端空闲', resume_local: '恢复本地任务', reconnecting: '正在重连', protocol_error: '响应解析失败' };
const notices: Record<string, string> = { not_required: '无需通知', waiting: '等待发送', waiting_idle: '等待会话空闲',
  waiting_connection: '等待会话连接', sending: '正在发送', sent: '已发送，等待 Agent 确认',
  acknowledged: 'Agent 已确认', delivery_unknown: '送达状态待核对' };
const outputStatuses: Record<string, string> = { saved: '已保存', failed: '取回失败', missing: '本机文件缺失', pending: '未记录保存成功' };
function date(value: string | null | undefined) {
  if (!value) return '未记录';
  const parsed = new Date(value);
  return `${localDateTime(parsed)}:${String(parsed.getSeconds()).padStart(2, '0')}`;
}

export function TaskDetailDialog({ id, updatedAt, nodes, close }: {
  id: string; updatedAt?: string; nodes: { url: string; name: string }[]; close: () => void;
}) {
  const query = useQuery<Detail>({ queryKey: ['task-detail', id], queryFn: async () => {
    const response = await fetch(`/api/comfy/tasks/${encodeURIComponent(id)}/detail`);
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || '任务详情读取失败');
    return body;
  }, retry: false });
  const { refetch } = query;
  useEffect(() => { void refetch(); }, [updatedAt, refetch]);
  const data = query.data;
  const node = (url: string) => nodes.find(item => item.url === url)?.name || url;
  const summary = data?.summary;
  const timeline = data?.events.filter((event, index, events) => !(event.stage === 'execution' && event.result === 'running'
    && events[index - 1]?.stage === 'execution' && events[index - 1]?.result === 'running')) ?? [];
  const duration = summary?.started_at && summary.ended_at
    ? Math.max(0, Math.floor((Date.parse(summary.ended_at) - Date.parse(summary.started_at)) / 1000)) : null;
  return <Dialog title="任务历史详情" close={close}><div className="task-detail">
    {query.isPending && <p role="status">正在读取任务详情…</p>}
    {query.isError && <div className="task-detail-problem" role="alert"><p>{query.error.message}</p>
      <button onClick={() => void refetch()}>重新读取</button></div>}
    {summary && data && <>
      <div className="task-detail-title"><div><p>{summary.project} · {taskTypeLabels[summary.task_type]}</p>
        <h3>{summary.title}</h3><p>来源会话：{summary.source_session_name || '未记录'}</p></div>
        <strong data-status={summary.status}>{statusLabels[summary.status] || summary.status}</strong></div>
      {summary.error && <section className="task-detail-problem"><h4>当前问题 · {stages[summary.failure_stage || ''] || summary.failure_stage || '阶段未记录'}</h4>
        <p>{summary.error}</p><p>成果保存：{summary.collected} / {summary.expected}</p></section>}
      <dl className="task-detail-summary">
        <div><dt>最初入队节点</dt><dd>{node(summary.enqueued_url)}</dd></div>
        <div><dt>{summary.submitted_at ? '实际执行节点' : '当前目标节点'}</dt><dd>{node(summary.remote_url)}</dd></div>
        {([['入队时间', summary.created_at], ['提交时间', summary.submitted_at], ['生成开始', summary.started_at],
          [summary.started_at ? '生成结束' : '任务结束', summary.ended_at], ['成果保存完成', summary.collected_at]] as const).map(([label, value]) =>
          <div key={label}><dt>{label}</dt><dd>{date(value)}</dd></div>)}
        <div><dt>生成耗时（不含排队、取回）</dt><dd>{duration === null ? '未记录' : clockText(duration)}</dd></div>
      </dl>
      <section><h4>成果 <span>{summary.collected} / {summary.expected} 已保存</span></h4>
        <p className="task-detail-muted">任务完成后取回全部成果，按入队时指定的本机路径保存。</p>
        {data.outputs.length === 0 ? <p className="task-detail-muted">未登记成果目标。</p> : <ul className="task-detail-outputs">
          {data.outputs.map(output => <li key={output.path}><div className="task-detail-output-heading"><b>{output.name}</b>
            <span data-status={output.status}>{outputStatuses[output.status] || output.status}</span>
            {output.status === 'saved' && output.url && <a href={output.url} target="_blank" rel="noreferrer">查看文件 ↗</a>}</div>
            {output.identity && <p>{output.identity}</p>}<p className="task-detail-path">{output.path}</p>
            <p className="task-detail-muted">保存时间：{date(output.downloaded_at)}{output.bytes !== null && ` · ${(output.bytes / 1024).toFixed(1)} KB`}</p>
            {output.error && <p className="task-detail-error">{output.error}</p>}</li>)}
        </ul>}
      </section>
      <div className="task-detail-columns"><section><h4>过程记录</h4>
        {timeline.length === 0 ? <p className="task-detail-muted">这项旧任务没有过程记录。</p> : <ol className="task-detail-timeline">
          {timeline.map(event => <li key={event.id} data-failed={!!event.error}><time dateTime={event.time}>{date(event.time)}</time>
            <p><b>{stages[event.stage] || event.stage}</b><span>{results[event.result] || event.result}</span></p>
            {event.source_url && event.target_url && <p>{node(event.source_url)} → {node(event.target_url)}</p>}
            {event.position !== undefined && <p>本地排位 #{event.position}</p>}
            {(event.identity || event.file || event.path) && <p className="task-detail-path">{event.identity || event.file || event.path}</p>}
            {event.error && <p className="task-detail-error">{event.error}</p>}</li>)}
        </ol>}
      </section><section><h4>Agent 通知</h4><p>{notices[summary.notification] || summary.notification || '未记录'}</p>
        <dl className="task-detail-notification">{['pending', 'sent', 'acknowledged'].map(result => {
          const events = data.events.filter(event => event.stage === 'notification' && event.result === result);
          return <div key={result}><dt>{results[result]}</dt><dd>{date(events.at(-1)?.time)}</dd></div>;
        })}</dl>
        {data.notification_batches.map(batch => <p key={batch.id}>合并通知：包含 {batch.task_count} 项任务 · {results[batch.status] || batch.status}</p>)}
      </section></div>
      <details className="task-detail-technical"><summary>技术记录</summary><dl>
        <div><dt>本地任务 ID</dt><dd>{summary.id}</dd></div><div><dt>远端任务 ID</dt><dd>{summary.prompt_id || '未取得'}</dd></div>
        <div><dt>目标节点地址</dt><dd>{summary.remote_url}</dd></div>
        <div><dt>准备次数 / 提交次数</dt><dd>{summary.preparation_attempt ?? '未记录'} / {summary.dispatch_attempt ?? '未记录'}</dd></div>
      </dl><div className="task-detail-records">{data.records.map(record => <a key={record.url} href={record.url} target="_blank" rel="noreferrer">{record.name} ↗</a>)}</div>
      </details>
    </>}
  </div></Dialog>;
}
