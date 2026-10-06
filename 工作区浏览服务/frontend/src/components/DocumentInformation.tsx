import type { ReactNode } from 'react';

export function DocumentInformation({ children }: { children: ReactNode }) {
  return <details className="document-information"><summary>文档信息</summary>{children}</details>;
}
