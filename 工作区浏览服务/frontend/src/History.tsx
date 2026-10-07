import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get } from './api';
import { Document, PreviewContext, Result } from './components';
import { PageHeader } from './components/PageHeader';
import { TabNav } from './components/TabNav';
export default function History() {
  const [selected, setSelected] = useState('版本记录.md');
  const list = useQuery({ queryKey: ['history'], queryFn: () => get<{ path: string; name: string }[]>('/api/history'), refetchInterval: 5000 });
  const document = useQuery({ queryKey: ['history-document', selected], queryFn: () => get<{ title: string; html: string }>(`/api/history/document?path=${encodeURIComponent(selected)}`), refetchInterval: 5000 });
  return <PreviewContext.Provider value={item => setSelected(item.key!)}><PageHeader eyebrow="开发跟踪" title="版本与开发记录" description="记录功能、修改原因、验证结果和后续事项。" /><div className="history-layout"><TabNav vertical label="开发文档" items={(list.data || []).map(item => ({ value: item.path, label: item.name }))} selected={selected} onChange={setSelected} /><article className="panel"><Result page loading={list.isPending || document.isPending} error={document.error || list.error} retry={document.error ? document.refetch : list.refetch} retrying={document.isFetching || list.isFetching} />{document.data && <Document key={selected} value={document.data} />}</article></div></PreviewContext.Provider>;
}
