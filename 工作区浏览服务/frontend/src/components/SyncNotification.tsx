import { useEffect, useState } from 'react';
import { useNotify } from './Notifications';

function RetryCountdown({ retryAt, changed }: { retryAt: number; changed: boolean }) {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const seconds = Math.max(0, Math.ceil((retryAt - now) / 1000));
  return seconds ? <>{changed ? '资料正在更新' : '资料更新失败'}，{seconds}秒后重试。</> : <>正在等待重试…</>;
}

export function SyncNotification({ error, errorKind, retryAt, updating }: {
  error?: string | null; errorKind?: string | null; retryAt?: number; updating?: boolean;
}) {
  const notify = useNotify();
  useEffect(() => {
    if (updating) return notify('正在同步资料…');
    if (error && retryAt) return notify(<RetryCountdown retryAt={retryAt} changed={errorKind === 'source_changed'} />,
      errorKind === 'source_changed' ? 'info' : 'error', 0);
  }, [error, errorKind, retryAt, updating, notify]);
  return null;
}
