import './Pagination.css';

export function Pagination({ page, total, change, pageSize = 36, showItemCount = true, variant = 'default', alwaysShow = false, itemLabel = '项' }: { page: number; total: number; change: (n: number) => void; pageSize?: number; showItemCount?: boolean; variant?: 'default' | 'arrows'; alwaysShow?: boolean; itemLabel?: string }) {
  const last = Math.max(1, Math.ceil(total / pageSize));
  const arrows = variant === 'arrows';
  return alwaysShow || total > pageSize ? <div className={arrows ? 'pagination-arrows' : 'pagination'}>
    {(!arrows || page > 1) && <button aria-label={arrows ? '上一张图' : '上一页'} disabled={page <= 1} onClick={() => change(page - 1)}>{arrows ? <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5-7 7 7 7" /></svg> : '上一页'}</button>}
    {!arrows && <span>{!showItemCount && '第'}<span className="pagination-current" style={{ width: `${String(last).length}ch` }}>{page}</span>{showItemCount ? ` / ${last} · 共${total}${itemLabel}` : `页 / 共${last}页`}</span>}
    {(!arrows || page < last) && <button data-direction="next" aria-label={arrows ? '下一张图' : '下一页'} disabled={page >= last} onClick={() => change(page + 1)}>{arrows ? <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7" /></svg> : '下一页'}</button>}
  </div> : null;
}
