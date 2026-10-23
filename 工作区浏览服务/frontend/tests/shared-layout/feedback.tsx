import { useEffect, useState } from 'react';
import { Dialog } from '../../src/components';
import { FloatingMessage, useNotify } from '../../src/components/Notifications';
import { Switch } from '../../src/components/Switch';

const longTitle = '长标题检查：保存资料时发生错误，请查看详细说明。' + 'DocumentRevisionReference'.repeat(4);
const longText = '长文字检查：这是一条模拟错误，请核对资料后重试，不会修改任何真实项目。'.repeat(4) + 'VeryLongUnbrokenReference'.repeat(12);
export function FeedbackFixture() {
  const notify = useNotify();
  const [dialog, setDialog] = useState<'default' | 'compact' | null>(null);
  const [busy, setBusy] = useState(false);
  const [running, setRunning] = useState(false);
  const [progress, setProgress] = useState(0);
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setProgress(value => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, [running]);
  return <section data-testid="feedback" className="panel">
    <h2>弹窗与消息检查</h2>
    <button onClick={() => setDialog('default')}>打开长内容弹窗</button>
    <button onClick={() => setDialog('compact')}>打开长内容紧凑弹窗</button>
    <button onClick={() => notify('已保存')}>短成功提示</button>
    <button onClick={() => notify(longText)}>长成功提示</button>
    <button onClick={() => notify(longText, 'error')}>长错误提示</button>
    <button onClick={() => setRunning(true)}>开始模拟操作</button>
    <button onClick={() => setRunning(false)}>结束模拟操作</button>
    <output data-testid="progress">{progress}</output>
    {running && <FloatingMessage>模拟操作进行中：{progress}。{longText}</FloatingMessage>}
    {dialog && <Dialog title={longTitle} size={dialog} closeDisabled={busy} close={() => setDialog(null)}>
      <Switch label="模拟禁止关闭" checked={busy} onChange={setBusy} />
      <button onClick={() => notify(longText, 'error')}>弹窗内错误提示</button>
      <p>{longText}</p>
      {Array.from({ length: 12 }, (_, i) => <p key={i}>第{i + 1}段。{longText}</p>)}
    </Dialog>}
  </section>;
}
