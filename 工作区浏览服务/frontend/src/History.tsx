import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get } from './api';
import { Document, PreviewContext, Result } from './components';
export default function History() {
  const [selected, setSelected] = useState('版本记录.md');
  const list = useQuery({ queryKey: ['history'], queryFn: () => get<{ path: string; name: string }[]>('/api/history'), refetchInterval: 5000 });
  const document = useQuery({ queryKey: ['history-document', selected], queryFn: () => get<{ title: string; html: string }>(`/api/history/document?path=${encodeURIComponent(selected)}`), refetchInterval: 5000 });
  return <PreviewContext.Provider value={item => setSelected(item.key!)}><p className="eyebrow">开发跟踪</p><h1>版本与开发记录</h1><p className="muted">记录功能、修改原因、验证结果和后续事项。</p><div className="history-layout"><nav aria-label="开发文档">{list.data?.map(item => <button key={item.path} aria-current={selected === item.path ? 'page' : undefined} onClick={() => setSelected(item.path)}>{item.name}</button>)}</nav><article className="panel"><Result loading={document.isPending} error={document.error || list.error} />{document.data && <Document key={selected} value={document.data} />}</article></div></PreviewContext.Provider>;
}
