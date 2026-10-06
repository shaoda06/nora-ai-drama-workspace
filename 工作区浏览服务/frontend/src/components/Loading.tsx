import { createPortal } from 'react-dom';

export function Loading({ page = false }: { page?: boolean }) {
  const content = <div className={'page-loading' + (page ? ' page-loading-screen' : '')} role="status" aria-live="polite">
    <span className="loading-spinner" aria-hidden="true" />
    <span>页面正在加载中</span>
  </div>;
  return page ? createPortal(content, document.body) : content;
}
