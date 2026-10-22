import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get } from './api';
import { Document, PreviewContext, Result } from './components';
import { PageHeader } from './components/PageHeader';
import { TabNav } from './components/TabNav';

const RECORDS = 'all-records';

export default function History() {
  const [selected, setSelected] = useState('版本记录.md');
  const [path, anchor] = selected.split('#');
  const showRecords = selected === RECORDS;
  const content = useRef<HTMLElement>(null);
  const list = useQuery({ queryKey: ['history'], queryFn: () => get<{ path: string; name: string }[]>('/api/history'), refetchInterval: 5000 });
  const document = useQuery({ queryKey: ['history-document', path], queryFn: () => get<{ title: string; html: string }>(`/api/history/document?path=${encodeURIComponent(path)}`), enabled: !showRecords, refetchInterval: 5000 });
  const records = (list.data || []).filter(item => item.path.startsWith('开发记录/'));
  const navigation = [
    { value: '版本记录.md', label: '版本记录' },
    { value: RECORDS, label: '全部开发记录' },
    ...(list.data || []).filter(item => item.path !== '版本记录.md' && !item.path.startsWith('开发记录/')).map(item => ({ value: item.path, label: item.name })),
  ];
  const openDocument = (value: string) => {
    setSelected(value);
    window.scrollTo(0, 0);
  };
  useEffect(() => {
    if (!anchor || !document.isSuccess) return;
    const id = decodeURIComponent(anchor);
    content.current?.querySelectorAll<HTMLElement>('[id]').forEach(element => {
      if (element.id === id) {
        element.scrollIntoView({ block: 'start' });
        element.tabIndex = -1;
        element.focus({ preventScroll: true });
      }
    });
  }, [selected, anchor, document.isSuccess]);
  const documentError = !showRecords && document.error;
  return <PreviewContext.Provider value={item => openDocument(item.key!)}>
    <PageHeader eyebrow="开发跟踪" title="版本与开发记录" />
    <div className="history-layout">
      <TabNav vertical label="开发文档" items={navigation} selected={path.startsWith('开发记录/') ? RECORDS : path} onChange={openDocument} />
      <article className="panel" ref={content}>
        <Result page loading={list.isPending || (!showRecords && document.isPending)} error={documentError || list.error} retry={documentError ? document.refetch : list.refetch} retrying={document.isFetching || list.isFetching} />
        {showRecords ? <>
          <h1>全部开发记录</h1>
          <ul>{[...records].sort((a, b) => b.name.localeCompare(a.name, 'zh-CN', { numeric: true })).map(item => <li key={item.path}><button className="link" onClick={() => openDocument(item.path)}>{item.name}</button></li>)}</ul>
        </> : document.data && <Document key={selected} value={document.data} />}
      </article>
    </div>
  </PreviewContext.Provider>;
}
