import { useContext } from 'react';
import { createPortal } from 'react-dom';
import type { UseQueryResult } from '@tanstack/react-query';
import { FooterCheckContext } from './AppShell';

type CheckQuery = Pick<UseQueryResult, 'dataUpdatedAt' | 'isFetching' | 'isError' | 'isPlaceholderData'>;

/** Use the current page's read queries, excluding global service/task polling. */
export function PageCheckStatus({ queries }: { queries: CheckQuery[] }) {
  const target = useContext(FooterCheckContext);
  const updatedAt = Math.max(0, ...queries.filter(query => !query.isPlaceholderData).map(query => query.dataUpdatedAt));
  const failed = queries.some(query => query.isError);
  const checking = queries.some(query => query.isFetching);
  const date = updatedAt ? new Date(updatedAt) : null;
  const formatted = date?.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).replaceAll('/', '-');
  return target && createPortal(<span title="当前页面数据最近一次成功读取的时间；数据未变化也会更新。">
    最近检查：{date ? <time dateTime={date.toISOString()} title={formatted} aria-label={formatted}><span className="footer-check-date">{formatted!.slice(0, 11)}</span>{formatted!.slice(11)}</time> : failed ? '尚无成功记录' : checking ? '正在检查…' : '尚未检查'}
    {failed && '（检查失败）'}
  </span>, target);
}
