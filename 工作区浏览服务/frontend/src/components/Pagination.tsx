export function Pagination({ page, total, change }: { page: number; total: number; change: (n: number) => void }) {
  const last = Math.max(1, Math.ceil(total / 36));
  return total > 36 ? <div className="pagination"><button disabled={page <= 1} onClick={() => change(page - 1)}>上一页</button><span>{page} / {last} · 共{total}项</span><button disabled={page >= last} onClick={() => change(page + 1)}>下一页</button></div> : null;
}
