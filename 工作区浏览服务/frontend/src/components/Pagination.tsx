export function Pagination({ page, total, change, pageSize = 36, showItemCount = true }: { page: number; total: number; change: (n: number) => void; pageSize?: number; showItemCount?: boolean }) {
  const last = Math.max(1, Math.ceil(total / pageSize));
  return total > pageSize ? <div className="pagination"><button disabled={page <= 1} onClick={() => change(page - 1)}>上一页</button><span>{!showItemCount && '第'}<span className="pagination-current" style={{ width: `${String(last).length}ch` }}>{page}</span>{showItemCount ? ` / ${last} · 共${total}项` : `页 / 共${last}页`}</span><button disabled={page >= last} onClick={() => change(page + 1)}>下一页</button></div> : null;
}
