import { useEffect, useRef, useState } from 'react';
import './NodeEditor.css';

interface SavedNode { url: string; has_auth: boolean; locked: boolean }
interface Config { revision: string | null; nodes: SavedNode[] }
interface Row extends SavedNode {
  key: number; original_url: string | null; auth_mode: 'keep' | 'none' | 'basic'; username: string; password: string;
}

export function NodeEditor({ close }: { close: () => void }) {
  const [config, setConfig] = useState<Config | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [initialRows, setInitialRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [confirmClose, setConfirmClose] = useState(false);
  const [confirmReload, setConfirmReload] = useState(false);
  const nextKey = useRef(0);
  const dirty = JSON.stringify(rows) !== JSON.stringify(initialRows);

  function accept(value: Config) {
    const next = value.nodes.map(node => ({ ...node, key: nextKey.current++, original_url: node.url,
      auth_mode: node.has_auth ? 'keep' as const : 'none' as const, username: '', password: '' }));
    setConfig(value); setRows(next); setInitialRows(next);
    setConfirmClose(false); setConfirmReload(false);
  }
  async function load(signal?: AbortSignal) {
    setLoading(true); setError(''); setNotice('');
    try {
      const response = await fetch('/api/comfy/config', { signal, cache: 'no-store' });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail);
      accept(data);
    } catch (failure) {
      if (signal?.aborted) return;
      setError((failure as Error).message);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!dirty) return;
    const prevent = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener('beforeunload', prevent);
    return () => window.removeEventListener('beforeunload', prevent);
  }, [dirty]);
  function update(index: number, value: Partial<Row>) {
    setRows(current => current.map((row, at) => at === index ? { ...row, ...value } : row));
    setNotice('');
  }
  function move(index: number, direction: number) {
    setRows(current => {
      const next = [...current];
      [next[index], next[index + direction]] = [next[index + direction], next[index]];
      return next;
    });
    setNotice('');
  }
  async function save(andClose = false) {
    setSaving(true); setError(''); setNotice('');
    try {
      const response = await fetch('/api/comfy/config', { method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ revision: config!.revision, nodes: rows.map(({ url, original_url, auth_mode, username, password }) =>
          ({ url, original_url, auth_mode, ...(auth_mode === 'basic' ? { username, password } : {}) })) }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail);
      accept(data); setNotice('已保存'); setConfirmClose(false);
      if (andClose) close();
    } catch (failure) {
      setError((failure as Error).message);
    } finally { setSaving(false); }
  }
  const busy = loading || saving;
  return <>
    <header className="comfy-node-editor-heading">
      <button autoFocus disabled={saving} onClick={() => dirty ? setConfirmClose(true) : close()}>‹ 返回</button>
      <strong>节点编辑</strong>
    </header>
    <section className="comfy-node-editor node-editor-body" aria-label="节点编辑" data-node-config-unsaved={dirty || saving}>
      {confirmReload && <div className="node-editor-confirm" role="status">
        <p>重新载入会放弃尚未保存的节点修改。</p>
        <div><button disabled={busy} onClick={() => { setConfirmReload(false); void load(); }}>放弃修改并重新载入</button>
          <button disabled={busy} onClick={() => setConfirmReload(false)}>继续编辑</button></div>
      </div>}
      {confirmClose && !confirmReload && <div className="node-editor-confirm" role="status">
        <p>节点修改尚未保存。</p>
        <div><button disabled={busy} onClick={() => void save(true)}>保存并返回</button>
          <button disabled={saving} onClick={close}>放弃修改并返回</button>
          <button disabled={saving} onClick={() => setConfirmClose(false)}>继续编辑</button></div>
      </div>}
      {loading && <p role="status">正在读取节点配置…</p>}
      {error && <div className="node-editor-error" role="alert"><p>{error}</p><button disabled={busy} onClick={() => {
        if (dirty) setConfirmReload(true); else void load();
      }}>重新载入</button></div>}
      {config && <form onSubmit={event => { event.preventDefault(); void save(); }}>
        <p className="node-editor-hint">所有项目共用此配置。第一项为默认节点，其余为备用节点。</p>
        <fieldset disabled={busy} className="node-editor-fields">
          {rows.map((row, index) => <section className="node-editor-card" key={row.key} aria-label={`节点${index + 1}`}>
            <div className="node-editor-card-heading"><strong>{index === 0 ? '默认节点' : `备用${index}`}</strong>
              <div><button type="button" aria-label={`上移节点${index + 1}`} disabled={index === 0} onClick={() => move(index, -1)}>上移</button>
                <button type="button" aria-label={`下移节点${index + 1}`} disabled={index === rows.length - 1} onClick={() => move(index, 1)}>下移</button>
                <button type="button" aria-label={`删除节点${index + 1}`} disabled={row.locked || rows.length === 1}
                  onClick={() => { setRows(current => current.filter(item => item.key !== row.key)); setNotice(''); }}>删除</button></div>
            </div>
            <label>节点地址<input aria-label={`节点${index + 1}地址`} type="url" required value={row.url} disabled={row.locked}
              placeholder="http://127.0.0.1:8188" onChange={event => update(index, { url: event.target.value })} /></label>
            {row.locked && <p className="node-editor-hint">有未结束或待处理任务，地址暂不能修改或删除。</p>}
            <label>认证<select aria-label={`节点${index + 1}认证`} value={row.auth_mode}
              onChange={event => update(index, { auth_mode: event.target.value as Row['auth_mode'], username: '', password: '' })}>
              {row.has_auth && <option value="keep">保留已配置认证</option>}
              <option value="none">无需认证</option><option value="basic">填写Basic账号密码</option>
            </select></label>
            {row.auth_mode === 'basic' && <div className="node-editor-auth">
              <label>账号<input aria-label={`节点${index + 1}账号`} autoComplete="off" required value={row.username}
                onChange={event => update(index, { username: event.target.value })} /></label>
              <label>密码<input aria-label={`节点${index + 1}密码`} type="password" autoComplete="new-password" required value={row.password}
                onChange={event => update(index, { password: event.target.value })} /></label>
            </div>}
          </section>)}
          {rows.length === 0 && <p className="node-editor-hint">尚未配置节点，点击下方添加。</p>}
          <button type="button" className="node-editor-add" onClick={() => {
            setRows(current => [...current, { key: nextKey.current++, original_url: null, url: '', has_auth: false,
              locked: false, auth_mode: 'none', username: '', password: '' }]); setNotice('');
          }}>＋ 添加节点</button>
        </fieldset>
        <footer className="node-editor-save"><button type="submit" disabled={busy || !dirty || rows.length === 0}>{saving ? '保存中…' : '保存'}</button>
          <span role="status">{notice || (dirty ? '有未保存的修改' : '')}</span></footer>
      </form>}
    </section>
  </>;
}
