import { FloatingMessage } from './Notifications';
import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Dialog } from '../components';
import { clockText, localDateTime, taskTypeLabels } from './TaskCard';
import { collectionStatus } from './LocalQueueCard';
import './TaskDetailDialog.css';

interface Event {
  id: number; time: string; stage: string; result: string; error?: string;
  source_url?: string; target_url?: string; url?: string; position?: number;
  path?: string; file?: string; identity?: string; collected?: number; notification_id?: string;
  attempt?: number; auto_retry?: number; delay_seconds?: number; next_retry_at?: string; summary?: string;
}
interface Detail {
  group?: { id: string; title: string; status: string; terminal: boolean;
    completed_tasks: number; expected_tasks: number; collected_outputs: number; expected_outputs: number;
    tasks: { task_id: string; title: string; status: string; completed: boolean; needs_attention: boolean }[] } | null;
  summary: {
    id: string; project: string; title: string; task_type: keyof typeof taskTypeLabels; status: string;
    source_session_name: string; enqueued_url: string; remote_url: string; prompt_id: string | null;
    created_at: string; submitted_at: string | null; started_at: string | null; ended_at: string | null;
    collected_at: string | null; failure_stage: string | null; error: string | null;
    collected: number; expected: number; notification: string;
    dispatch_attempt: number | null; preparation_attempt: number | null;
    collection_attempt: number | null; collection_auto_retry: number | null;
    collection_next_retry_at: string | null; collection_retry_stop: string | null;
    resolution?: { summary: string; resolved_at: string; original_status: string };
    closeout?: { status?: string; error?: string };
    closeout_next_retry_at?: string | null;
  };
  events: Event[];
  outputs: { path: string; name: string; identity: string | null; available: boolean; bytes: number | null;
    url: string | null; status: string; downloaded_at: string | null; error: string | null }[];
  records: { name: string; url: string }[];
  notification_batches: { id: string; task_count: number; status: string }[];
  resolution_evidence: { name: string; url: string | null }[];
  replacement_tasks: { id: string; title: string; status: string }[];
}
const stages: Record<string, string> = { enqueue: '登记入队', transfer: '转移节点', pause: '暂停', resume: '恢复排队',
  insert: '插队', immediate: '立即提交', cancel: '取消', reorder: '排序', preflight: '提交前检查',
  target_dependencies: '节点依赖检查', target_cache: '节点缓存检查', upload: '上传素材', upload_binding: '素材绑定',
  dispatch: '调度', submit: '提交远端', execution: '远端生成', collection: '取回全部成果', download: '保存成果',
  collection_retry: '重试取回', notification: '通知来源会话', restart: '后台恢复', reconcile: '核对远端状态', connection: '远端连接', resolution: '异常结案' };
const results: Record<string, string> = { accepted: '已接受', started: '开始', success: '成功', completed: '完成',
  running: '执行中', queued: '远端排队中', failed: '失败', collection_failed: '取回失败', rejected: '被拒绝',
  unknown: '结果待核对', pending: '等待发送', sent: '已发送', acknowledged: 'Agent 已确认', saved: '已保存',
  checked: '已检查', waiting_remote: '等待远端空闲', resume_local: '恢复本地任务', reconnecting: '正在重连', protocol_error: '响应解析失败',
  scheduled: '等待自动重试', attempt_failed: '本轮取回失败', resolved: '已结案' };
const notices: Record<string, string> = { not_required: '无需通知', waiting: '等待发送', waiting_idle: '等待会话空闲',
  waiting_connection: '等待会话连接', sending: '正在发送', sent: '已发送，等待 Agent 确认',
  acknowledged: 'Agent 已确认接收', delivery_unknown: '送达状态待核对' };
const outputStatuses: Record<string, string> = { saved: '已保存', failed: '取回失败', missing: '本机文件缺失', pending: '未记录保存成功' };
const taskGuidance: Record<string, { title: string; text: string }> = {
  submission_unknown: { title: '请来源 Agent 核对提交结果', text: '提交是否成功还没有确认。请来源 Agent 查看提交请求、响应和远端任务记录，确认这次任务是否已被接收。核对前不要再次提交，后台不会自动重发生成请求。' },
  needs_attention: { title: '请来源 Agent 核对远端状态', text: '当前记录不足以确认远端任务的结果。请来源 Agent 根据远端任务 ID、执行结果和过程记录核对；任务暂时查不到，不代表生成失败，核对前不要重新生成。' },
  rejected: { title: '请来源 Agent 检查提交被拒绝的原因', text: '请来源 Agent 查看远端响应，检查工作流、节点依赖和输入资料，修正记录中指出的问题。后台不会自动重新提交；需要再次生成时，另行确认并创建新的执行。' },
  failed: { title: '请来源 Agent 检查生成失败的原因', text: '请来源 Agent 查看远端执行结果和失败阶段，检查对应的工作流、输入或节点问题。后台不会自动重新生成；需要再次生成时，另行确认并创建新的执行。' },
};
const notificationGuidance: Record<string, string> = {
  waiting: '后台会发送保存的结果通知，无需手动重复发送。',
  waiting_idle: '来源会话忙碌，后台会等会话空闲后发送结果通知。',
  waiting_connection: '来源会话暂时无法连接，后台会继续重试发送保存的结果通知。',
  sending: '后台正在发送结果通知，请等待发送结果。',
  sent: '通知已经发出，正在等待来源 Agent 确认收到；无需重复生成或再次发送通知。',
  acknowledged: '来源 Agent 已确认接收；当前报告读取也会登记此回执，旧通知可能只有接收确认。这不代表已经向用户交付，也不代表内容获批。尚未交付的本轮成果由来源 Agent 沿既有制作记录继续汇总。',
  delivery_unknown: '通知是否送达还没有确认，后台只核对接收确认，不自动重发。请来源 Agent 查看会话是否已收到这条结果通知，收到后确认接收；无需重新生成或取回成果。',
};
function date(value: string | null | undefined) {
  if (!value) return '未记录';
  const parsed = new Date(value);
  return `${localDateTime(parsed)}:${String(parsed.getSeconds()).padStart(2, '0')}`;
}

export function TaskDetailDialog({ id, updatedAt, nodes, close, openTask }: {
  id: string; updatedAt?: string; nodes: { url: string; name: string }[]; close: () => void; openTask?: (id: string) => void;
}) {
  const query = useQuery<Detail>({ queryKey: ['task-detail', id], queryFn: async () => {
    const response = await fetch(`/api/comfy/tasks/${encodeURIComponent(id)}/detail`);
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || '任务详情读取失败');
    return body;
  }, retry: false, refetchInterval: query => query.state.data?.group && !query.state.data.group.terminal ? 5000 : false });
  const { refetch } = query;
  useEffect(() => { void refetch(); }, [updatedAt, refetch]);
  const data = query.data;
  const node = (url: string) => nodes.find(item => item.url === url)?.name || url;
  const summary = data?.summary;
  const missingSavedOutput = data?.outputs.some(output => output.status === 'missing');
  const guidance = summary && (summary.status === 'collecting' ? {
    title: summary.collection_next_retry_at ? '后台正在等待自动重试' : '后台正在取回成果',
    text: summary.collection_next_retry_at
      ? `后台将在 ${date(summary.collection_next_retry_at)} 重试未保存的成果。已经保存的成果会保留，现在无需 Agent 手动重试，也不要重新提交生成。`
      : '生成已经结束，后台正在保存成果。请等待全部成果保存成功，或出现需要处理的最终错误；现在无需手动重试或重新生成。',
  } : summary.status === 'collection_failed' ? {
    title: summary.collection_retry_stop === 'exhausted' ? '自动重试已用完，请来源 Agent 接手' : '取回已停止，请来源 Agent 检查原因',
    text: summary.collection_retry_stop === 'exhausted'
      ? '后台已用完本轮 3 次自动重试。请来源 Agent 查看最后一次失败记录，确认远端连接和保存条件恢复后，通过已有的“重试取回”入口再次请求后台下载。'
      : '请来源 Agent 按失败记录检查成果映射、保存路径、文件权限或文件冲突，修正具体问题后，通过已有的“重试取回”入口请求后台继续下载。',
  } : summary.status === 'completed' && missingSavedOutput ? {
    title: '请来源 Agent 核对缺失的本机成果',
    text: '记录显示成果曾经保存成功，但现在找不到文件。请来源 Agent 检查文件是否被移动或删除，并核对原保存路径；先查找或恢复已有成果，不要直接重新生成。',
  } : taskGuidance[summary.status]);
  const timeline = data?.events.filter((event, index, events) => !(event.stage === 'execution' && event.result === 'running'
    && events[index - 1]?.stage === 'execution' && events[index - 1]?.result === 'running')) ?? [];
  const duration = summary?.started_at && summary.ended_at
    ? Math.max(0, Math.floor((Date.parse(summary.ended_at) - Date.parse(summary.started_at)) / 1000)) : null;
  return <Dialog title="任务详情" close={close}><div className="task-detail">
    {query.isPending && <p role="status">正在读取任务详情…</p>}
    {query.isError && <FloatingMessage tone="error">{query.error.message}
      <button onClick={() => void refetch()}>重新读取</button></FloatingMessage>}
    {summary && data && <>
      <div className="task-detail-title"><div><p>{summary.project} · {taskTypeLabels[summary.task_type]}</p>
        <h3>{summary.title}</h3><p>来源会话：{summary.source_session_name || '未记录'}</p></div>
        <strong data-status={summary.status}>{collectionStatus(summary)}</strong></div>
      {data.group && <section className="task-detail-guidance" aria-label="任务组进度">
        <h4>{data.group.title}</h4>
        <p>全组收尾：{data.group.completed_tasks} / {data.group.expected_tasks} 项 · 成果取回：{data.group.collected_outputs} / {data.group.expected_outputs}</p>
        <p>{data.group.status === 'completed' ? '全组已完成，统一通知来源 Agent。'
          : data.group.status === 'terminal_partial' ? '本组已结束，部分任务未完成，详见下列任务。'
          : data.group.status === 'needs_attention' ? '本组有待处理问题，其他任务继续执行。'
          : '各任务独立排队执行，全组完成后统一通知。'}</p>
        <ul>{data.group.tasks.map(task => <li key={task.task_id}>{openTask && task.task_id !== id
          ? <button className="link" onClick={() => openTask(task.task_id)}>{task.title}</button> : task.title}
          {' · '}{task.completed ? '已完成收尾' : task.needs_attention ? '需要处理' : collectionStatus(task)}</li>)}</ul>
      </section>}
      {summary.resolution && <section className="task-detail-guidance" aria-label="异常结案">
        <h4>已结案 · {date(summary.resolution.resolved_at)}</h4><p>{summary.resolution.summary}</p>
        <p className="task-detail-muted">结案不代表原任务生成成功；原任务ID、异常和保存计数保留。</p>
        <ul>{data.resolution_evidence.map((item, index) => <li key={index}>{item.url
          ? <a href={item.url} target="_blank" rel="noreferrer">{item.name} ↗</a> : `${item.name}（文件不可用）`}</li>)}</ul>
        {data.replacement_tasks.map(task => <p key={task.id}>后续任务：{openTask
          ? <button onClick={() => openTask(task.id)}>{task.title} · {collectionStatus(task)}</button>
          : `${task.title} · ${collectionStatus(task)}`}</p>)}
      </section>}
      {summary.error && <section className="task-detail-problem"><h4>{summary.status === 'resolved' ? '原异常（已结案）' : '当前问题'} · {stages[summary.failure_stage || ''] || summary.failure_stage || '阶段未记录'}</h4>
        <p>{summary.error}</p><p>原任务保存记录：{summary.collected} / {summary.expected}</p></section>}
      {summary.status === 'completed' && ['registration_failed', 'browser_pending'].includes(summary.closeout?.status || '') && <section className="task-detail-problem" aria-label="结果收尾问题">
        <h4>{summary.closeout?.status === 'browser_pending' ? '网页同步尚未完成' : '结果登记尚未完成'}</h4>
        <p>{summary.closeout?.error}</p><p>成果已经保存，恢复登记或网页核验即可，不重新生成或取回。</p>
        <p>{summary.closeout_next_retry_at ? `后台将在 ${date(summary.closeout_next_retry_at)} 重试收尾。` : '请来源 Agent 查看结果收尾报告，按具体失败阶段接续。'}</p>
      </section>}
      {guidance && <section className="task-detail-guidance" aria-label="任务处理提示">
        <h4>{guidance.title}</h4><p>{guidance.text}</p>
        {summary.status === 'collection_failed' && <p>已经保存的成果保留，只重试未保存的成果，不重新生成。具体文件见下方“成果”，失败原因见“当前问题”和“过程记录”。</p>}
      </section>}
      <dl className="task-detail-summary">
        <div><dt>最初入队节点</dt><dd>{node(summary.enqueued_url)}</dd></div>
        <div><dt>{summary.submitted_at ? '实际执行节点' : '当前目标节点'}</dt><dd>{node(summary.remote_url)}</dd></div>
        {([['入队时间', summary.created_at], ['提交时间', summary.submitted_at], ['生成开始', summary.started_at],
          [summary.started_at ? '生成结束' : '任务结束', summary.ended_at], ['成果保存完成', summary.collected_at]] as const).map(([label, value]) =>
          <div key={label}><dt>{label}</dt><dd>{date(value)}</dd></div>)}
        <div><dt>生成耗时（不含排队、取回）</dt><dd>{duration === null ? '未记录' : clockText(duration)}</dd></div>
      </dl>
      {summary.collection_attempt !== null && summary.collection_attempt !== undefined && <section><h4>取回重试</h4>
        <p>取回累计尝试：{summary.collection_attempt} 轮 · 本轮已自动重试：{summary.collection_auto_retry || 0} / 3 次</p>
        {summary.status === 'collecting' && summary.collection_next_retry_at && <p>下次重试：{date(summary.collection_next_retry_at)}</p>}
        {summary.collection_retry_stop === 'exhausted' && <p>自动重试次数已用完，交由 Agent 处理。</p>}
        {summary.collection_retry_stop === 'requires_attention' && <p>当前错误需要核对资料或文件，已停止自动重试，交由 Agent 处理。</p>}
      </section>}
      <section><h4>{summary.status === 'resolved' ? '原任务成果记录' : '成果'} <span>{summary.collected} / {summary.expected} 已保存</span></h4>
        <p className="task-detail-muted">{summary.status === 'resolved'
          ? '此处保留原任务当时的保存记录；恢复及替代成果见上方结案依据。'
          : '任务完成后取回全部成果，按入队时指定的本机路径保存。'}</p>
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
            {event.attempt !== undefined && <p>取回第 {event.attempt} 轮{event.auto_retry !== undefined && ` · 自动重试 ${event.auto_retry} / 3`}</p>}
            {event.next_retry_at && <p>下次重试：{date(event.next_retry_at)}</p>}
            {event.summary && <p>{event.summary}</p>}
            {event.source_url && event.target_url && <p>{node(event.source_url)} → {node(event.target_url)}</p>}
            {event.position !== undefined && <p>本地排位 #{event.position}</p>}
            {(event.identity || event.file || event.path) && <p className="task-detail-path">{event.identity || event.file || event.path}</p>}
            {event.error && <p className="task-detail-error">{event.error}</p>}</li>)}
        </ol>}
      </section><section><h4>Agent 通知</h4><p>{notices[summary.notification] || summary.notification || '未记录'}</p>
        {notificationGuidance[summary.notification] && <p className="task-detail-muted">{notificationGuidance[summary.notification]}</p>}
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
