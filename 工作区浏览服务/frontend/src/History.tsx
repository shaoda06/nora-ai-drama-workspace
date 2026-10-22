import { PageCheckStatus } from './components/PageCheckStatus';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { get } from './api';
import { Dialog, Document, PreviewContext, Result } from './components';
import { PageHeader } from './components/PageHeader';
import { TabNav } from './components/TabNav';
import { Pagination } from './components/Pagination';
import './History.css';

type HistoryDocument = { title: string; html: string; page: number; pageSize: number; total: number };

function HistoryPreview({ selected, close }: { selected: string; close: () => void }) {
  const [path, anchor] = selected.split('#');
  const content = useRef<HTMLDivElement>(null);
  const document = useQuery({ queryKey: ['history-document', path, 1], queryFn: () => get<HistoryDocument>(`/api/history/document?path=${encodeURIComponent(path)}`), refetchInterval: 5000 });
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
  return <Dialog title={document.data?.title || path.split('/').pop()!.replace(/\.md$/, '')} close={close}>
    <Result loading={document.isPending} error={document.error} retry={document.refetch} retrying={document.isFetching} />
    <div ref={content}>{document.data && <Document key={selected} value={document.data} />}</div>
  </Dialog>;
}

export default function History() {
  const [selected, setSelected] = useState('版本记录.md');
  const [page, setPage] = useState(1);
  const [preview, setPreview] = useState<string | null>(null);
  const closePreview = useCallback(() => setPreview(null), []);
  const showVersions = selected === '版本记录.md';
  const list = useQuery({ queryKey: ['history'], queryFn: () => get<{ path: string; name: string }[]>('/api/history'), refetchInterval: 5000 });
  const document = useQuery({ queryKey: ['history-document', selected, showVersions ? page : 1], queryFn: () => get<HistoryDocument>(`/api/history/document?path=${encodeURIComponent(selected)}&page=${showVersions ? page : 1}`), refetchInterval: 5000 });
  const navigation = [
    { value: '版本记录.md', label: '版本记录' },
    ...(list.data || []).filter(item => item.path !== '版本记录.md' && !item.path.startsWith('开发记录/')).map(item => ({ value: item.path, label: item.name })),
  ];
  const openDocument = (value: string) => {
    setSelected(value);
    window.scrollTo(0, 0);
  };
  const changePage = (value: number) => {
    setPage(value);
    window.scrollTo(0, 0);
  };
  const pagination = showVersions && document.data && <Pagination page={document.data.page} total={document.data.total} pageSize={document.data.pageSize} change={changePage} />;
  return <PreviewContext.Provider value={item => setPreview(item.key!)}>
    <PageCheckStatus queries={[list, document]} />
    <PageHeader eyebrow="开发跟踪" title="版本与开发记录" />
    <div className="history-layout">
      <TabNav vertical label="开发文档" items={navigation} selected={selected} onChange={openDocument} />
      <article className={showVersions ? "panel history-versions" : "panel"}>
        <Result page loading={list.isPending || document.isPending} error={document.error || list.error} retry={document.error ? document.refetch : list.refetch} retrying={document.isFetching || list.isFetching} />
        {document.data && <>
          <Document key={`${selected}:${showVersions ? document.data.page : 1}`} value={document.data} showChapters={!showVersions} />
          {pagination}
        </>}
      </article>
    </div>
    {preview && <HistoryPreview selected={preview} close={closePreview} />}
  </PreviewContext.Provider>;
}
