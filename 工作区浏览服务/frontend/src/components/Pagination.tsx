import './Pagination.css';

export function Pagination({ page, total, change, pageSize = 36, showItemCount = true, variant = 'default' }: { page: number; total: number; change: (n: number) => void; pageSize?: number; showItemCount?: boolean; variant?: 'default' | 'arrows' }) {
  const last = Math.max(1, Math.ceil(total / pageSize));
  const arrows = variant === 'arrows';
  return total > pageSize ? <div className={arrows ? 'pagination-arrows' : 'pagination'}>
    <button aria-label="上一页" disabled={page <= 1} onClick={() => change(page - 1)}>{arrows ? <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5-7 7 7 7" /></svg> : '上一页'}</button>
    {!arrows && <span>{!showItemCount && '第'}<span className="pagination-current" style={{ width: `${String(last).length}ch` }}>{page}</span>{showItemCount ? ` / ${last} · 共${total}项` : `页 / 共${last}页`}</span>}
    <button aria-label="下一页" disabled={page >= last} onClick={() => change(page + 1)}>{arrows ? <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7" /></svg> : '下一页'}</button>
  </div> : null;
}
