import { useEffect, useRef, useState } from 'react';
import { useInfiniteQuery } from '@tanstack/react-query';
import { LocalQueueCard, type LocalQueueTask } from './LocalQueueCard';

interface HistoryPage { items: LocalQueueTask[]; total: number; next_offset: number | null }

export function TaskHistory({ url, updatedAt, total, onDetails }: {
  url: string; updatedAt?: string | null; total: number; onDetails: (id: string) => void;
}) {
  const [text, setText] = useState('');
  const [search, setSearch] = useState('');
  const [result, setResult] = useState('all');
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(text.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [text]);
  const query = useInfiniteQuery({ queryKey: ['task-history', url, search, result], initialPageParam: 0,
    queryFn: async ({ pageParam }): Promise<HistoryPage> => {
      const params = new URLSearchParams({ url, q: search, result, offset: String(pageParam), limit: '20' });
      const response = await fetch(`/api/comfy/history?${params}`);
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '任务历史读取失败');
      return data;
    }, getNextPageParam: page => page.next_offset ?? undefined, retry: false, gcTime: 0 });
  const { refetch } = query;
  const previous = useRef({ updatedAt, total });
  useEffect(() => {
    if (previous.current.updatedAt !== updatedAt || previous.current.total !== total) {
      previous.current = { updatedAt, total };
      void refetch();
    }
  }, [updatedAt, total, refetch]);
  const items = Array.from(new Map(query.data?.pages.flatMap(page => page.items).map(task => [task.id, task]) ?? []).values());
  const matches = query.data?.pages[0].total;
  return <div className="comfy-history">
    <div className="comfy-history-controls"><input type="search" aria-label="搜索任务标题或来源会话"
      placeholder="搜索标题或来源会话" value={text} onChange={event => setText(event.target.value)} />
      <select aria-label="历史任务结果" value={result} onChange={event => setResult(event.target.value)}>
        <option value="all">全部结果</option><option value="completed">已完成</option>
        <option value="abnormal">异常</option><option value="cancelled">已取消</option>
      </select></div>
    <div className="comfy-queue-body">
      {query.isPending && <p className="comfy-empty" role="status">正在读取历史…</p>}
      {query.isError && <p className="comfy-task-warning" role="alert">{query.error.message} <button
        disabled={query.isFetching} onClick={() => void refetch()}>重新读取</button></p>}
      {!query.isPending && !query.isError && items.length === 0 && <p className="comfy-empty">{search || result !== 'all' ? '没有符合条件的历史任务' : '暂无历史任务'}</p>}
      <div className="comfy-task-items">{items.map(task => <LocalQueueCard key={task.id} task={task} onDetails={onDetails} />)}</div>
      {matches !== undefined && matches > 0 && <div className="comfy-history-footer"><span>已显示 {items.length} / {matches} 条</span>
        {query.hasNextPage && <button disabled={query.isFetching} onClick={() => void query.fetchNextPage()}>
          {query.isFetchingNextPage ? '正在加载…' : '加载更多'}</button>}
      </div>}
    </div>
  </div>;
}
