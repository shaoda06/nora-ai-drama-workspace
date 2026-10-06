export function Loading() {
  return <div className="page-loading" role="status" aria-live="polite">
    <span className="loading-spinner" aria-hidden="true" />
    <span>页面正在加载中</span>
  </div>;
}
