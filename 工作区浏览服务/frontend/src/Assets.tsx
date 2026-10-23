import { PageCheckStatus } from './components/PageCheckStatus';
import { TabSelect } from './components/TabSelect';
import { useEffect, useRef, useState } from 'react';
import { Link, Navigate, useBlocker, useNavigate, useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Dialog, Preview, Result } from './components';
import { SearchField } from './components/SearchField';
import { FileActions } from './components/FileActions';
import { PageHeader } from './components/PageHeader';
import { FloatingMessage, useNotify } from './components/Notifications';
import './Assets.css';

type Kind = 'person' | 'clothing' | 'prop';
type Slot = 'portrait' | 'views' | 'album';
type Profile = { gender: string; age: string; identity: string; appearance: string; personality: string; description: string };
type Card = { kind: Kind; name: string; category: string; profile: Profile };
type Picture = { id: string; name: string; slot: Slot; mime: string; size: number };
type Asset = Card & { id: string; revision: number; updated_at: string; images: Picture[] };
const kinds: Record<Kind, string> = { person: '人物', clothing: '服装', prop: '道具' };
const clothing = ['帽子', '服装', '鞋子', '配饰'];
const slots: Record<Slot, string> = { portrait: '正面半身图', views: '三视图', album: '相册' };
const imageUrl = (asset: Asset, picture: Picture) => `/api/assets/${asset.id}/images/${picture.id}`;
const newCard = (kind: Kind): Card => ({ kind, name: '', category: kind === 'clothing' ? '服装' : '', profile: { gender: '', age: '', identity: '', appearance: '', personality: '', description: '' } });
const cardOf = ({ kind, name, category, profile }: Card): Card => ({ kind, name, category, profile });

async function api<T>(path = '', method = 'GET', data?: unknown, signal?: AbortSignal): Promise<T> {
  const form = data instanceof FormData;
  const response = await fetch(`/api/assets${path}`, {
    method, signal, headers: data === undefined || form ? undefined : { 'Content-Type': 'application/json' },
    body: data === undefined ? undefined : form ? data : JSON.stringify(data),
  });
  if (!response.ok) {
    const result = await response.json();
    throw new Error(typeof result.detail === 'string' ? result.detail : '内容不符合要求，请检查名称、分类或图片。');
  }
  return response.json();
}

export default function Assets() {
  const { kind = 'person', id } = useParams();
  if (!Object.hasOwn(kinds, kind)) return <Navigate to="/assets/person" replace />;
  return <div className="asset-library">
    <PageHeader title="资产管理" description="整理人物、服装与道具，保存资料和参考图片。" />
    <nav className="asset-tabs" aria-label="资产类型">{Object.entries(kinds).map(([key, label]) => <Link key={key} to={`/assets/${key}`} aria-current={kind === key ? 'page' : undefined}>{label}</Link>)}</nav>
    {id ? <AssetDetail key={`${kind}/${id}`} kind={kind as Kind} id={id} /> : <AssetList key={kind} kind={kind as Kind} />}
  </div>;
}

function AssetList({ kind }: { kind: Kind }) {
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const query = useQuery({ queryKey: ['asset-library'], queryFn: ({ signal }) => api<Asset[]>('', 'GET', undefined, signal) });
  const all = (query.data || []).filter(item => item.kind === kind);
  const needle = search.trim().toLocaleLowerCase();
  const items = all.filter(item => (!category || item.category === category) &&
    [item.name, item.category, ...Object.values(item.profile)].join('\n').toLocaleLowerCase().includes(needle));
  return <>
    <PageCheckStatus queries={[query]} />
    <div className="asset-toolbar"><SearchField label="搜索资产" placeholder={`搜索${kinds[kind]}名称或资料…`} value={search} onChange={setSearch} />
      {kind === 'clothing' && <TabSelect label="服装分类筛选" selected={category} onChange={setCategory} items={[{ value: '', label: '全部分类' }, ...clothing.map((value) => ({ value, label: value }))]} />}
      <Link className="asset-primary" to={`/assets/${kind}/new`}>＋ 新增{kinds[kind]}</Link></div>
    <Result loading={query.isPending} error={query.error} retry={query.refetch} retrying={query.isFetching} />
    {query.data && <p className="muted">{items.length} 份{kinds[kind]}资产</p>}
    <div className="asset-grid">{items.map(item => {
      const cover = item.images.find(image => image.slot === 'portrait') || item.images[0];
      return <Link className="asset-card" key={item.id} to={`/assets/${kind}/${item.id}`}>
        <div className="asset-cover">{cover ? <img src={imageUrl(item, cover)} alt={item.name} loading="lazy" /> : <span>{kinds[kind]}</span>}</div>
        <div className="asset-card-text"><h2>{item.name}</h2><p>{item.profile.identity || item.profile.description || '尚未填写资料'}</p><small>{item.category || `${kinds[kind]}资料卡`} · {item.images.length} 张图片</small></div>
      </Link>;
    })}</div>
    {query.data && !items.length && <div className="asset-empty"><h2>{all.length ? '没有找到匹配的资产' : `还没有${kinds[kind]}资产`}</h2><p>{all.length ? '试试其他关键词或分类。' : `点击“新增${kinds[kind]}”，先建一份资料，再上传图片。`}</p></div>}
  </>;
}

function AssetDetail({ kind, id }: { kind: Kind; id: string }) {
  const query = useQuery({ queryKey: ['asset', id], queryFn: ({ signal }) => api<Asset>(`/${id}`, 'GET', undefined, signal), enabled: id !== 'new', gcTime: 0, staleTime: 0 });
  if (id === 'new') return <><PageCheckStatus queries={[]} /><AssetEditor initial={null} kind={kind} /></>;
  if (!query.data) return <><PageCheckStatus queries={[query]} /><Link to={`/assets/${kind}`}>‹ 返回{kinds[kind]}列表</Link><Result loading={query.isPending} error={query.error} retry={query.refetch} retrying={query.isFetching} /></>;
  if (query.data.kind !== kind) return <Navigate to={`/assets/${query.data.kind}/${id}`} replace />;
  return <><PageCheckStatus queries={[query]} /><AssetEditor initial={query.data} kind={kind} /></>;
}

function AssetEditor({ initial, kind }: { initial: Asset | null; kind: Kind }) {
  const client = useQueryClient();
  const navigate = useNavigate();
  const notify = useNotify();
  const [saved, setSaved] = useState(initial);
  const [draft, setDraft] = useState<Card>(() => initial ? cardOf(initial) : newCard(kind));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState<Picture | null>(null);
  const [remove, setRemove] = useState<Picture | 'asset' | null>(null);
  const [reload, setReload] = useState(false);
  const leaving = useRef(false);
  const dirty = JSON.stringify(draft) !== JSON.stringify(saved ? cardOf(saved) : newCard(kind));
  const blocker = useBlocker(() => !leaving.current && (dirty || busy));
  useEffect(() => {
    const listener = (event: BeforeUnloadEvent) => { if (dirty || busy) { event.preventDefault(); event.returnValue = ''; } };
    window.addEventListener('beforeunload', listener);
    return () => window.removeEventListener('beforeunload', listener);
  }, [dirty, busy]);

  function accept(item: Asset) {
    setSaved(item);
    void client.invalidateQueries({ queryKey: ['asset-library'] });
  }
  async function run(action: () => Promise<void>) {
    setBusy(true); setError('');
    try { await action(); }
    catch (failure) { setError((failure as Error).message); }
    finally { setBusy(false); }
  }
  async function save() {
    const item = await api<Asset>(saved ? `/${saved.id}` : '', saved ? 'PUT' : 'POST', saved ? { ...draft, revision: saved.revision } : draft);
    accept(item); setDraft(cardOf(item)); notify('资料已保存');
    if (!saved) { leaving.current = true; navigate(`/assets/${kind}/${item.id}`, { replace: true }); }
  }
  function setProfile(field: keyof Profile, value: string) { setDraft(current => ({ ...current, profile: { ...current.profile, [field]: value } })); }
  async function upload(slot: Slot, files: File[]) {
    let current = saved!;
    let uploaded = 0;
    try {
      for (const file of files) {
        if (file.size > 25 * 1024 * 1024) throw new Error(`${file.name} 超过 25 MB，请选择较小的图片。`);
        const form = new FormData(); form.append('file', file); form.append('slot', slot); form.append('revision', String(current.revision));
        current = await api<Asset>(`/${current.id}/images`, 'POST', form);
        accept(current); uploaded++;
      }
    } finally { if (uploaded) notify(`已保存 ${uploaded} 张图片`); }
  }
  async function confirmRemove() {
    if (remove === 'asset') {
      await api(`/${saved!.id}?revision=${saved!.revision}`, 'DELETE');
      void client.invalidateQueries({ queryKey: ['asset-library'] });
      leaving.current = true; navigate(`/assets/${kind}`); notify('资产已删除');
    } else if (remove) {
      accept(await api<Asset>(`/${saved!.id}/images/${remove.id}?revision=${saved!.revision}`, 'DELETE'));
      setRemove(null); notify('图片已删除');
    }
  }
  function uploadControl(slot: Slot, replace = false) {
    return <label className="asset-upload" aria-disabled={busy || dirty || !saved}>
      <span>{replace ? '替换图片' : slot === 'album' ? '＋ 上传图片' : '＋ 上传'}</span>
      <input type="file" aria-label={`上传${slots[slot]}`} accept="image/png,image/jpeg,image/webp,image/gif" multiple={slot === 'album'} disabled={busy || dirty || !saved}
        onChange={event => { const files = Array.from(event.target.files || []); event.target.value = ''; if (files.length) void run(() => upload(slot, files)); }} />
    </label>;
  }
  function pictureCard(picture: Picture) {
    return <div className="asset-picture" key={picture.id}>
      <button className="asset-picture-preview" aria-label={`预览${slots[picture.slot]}：${picture.name}`} onClick={() => setPreview(picture)}><img src={imageUrl(saved!, picture)} alt={picture.name} loading="lazy" /></button>
      <div className="asset-picture-footer"><span title={picture.name}>{picture.name}</span><div><FileActions url={imageUrl(saved!, picture)} downloadOnly /><button className="link" disabled={busy || dirty} onClick={() => setRemove(picture)}>删除</button></div></div>
    </div>;
  }
  return <div data-asset-unsaved={dirty || busy}>
    <div className="asset-detail-heading"><Link to={`/assets/${kind}`}>‹ 返回{kinds[kind]}列表</Link>{saved && <button className="asset-danger" disabled={busy || dirty} onClick={() => setRemove('asset')}>删除{kinds[kind]}</button>}</div>
    {error && <FloatingMessage tone="error">{error}{saved && !remove && !reload && <button disabled={busy} onClick={() => setReload(true)}>重新载入</button>}</FloatingMessage>}
    <div className="asset-editor">
      <section className="asset-info" aria-label="资料卡"><h2>{saved ? saved.name : `新增${kinds[kind]}`}</h2>
        <form onSubmit={event => { event.preventDefault(); void run(save); }}><fieldset disabled={busy}>
          <label>名称<input required maxLength={100} value={draft.name} onChange={event => setDraft({ ...draft, name: event.target.value })} placeholder={kind === 'person' ? '人物姓名或称呼' : '资产名称'} /></label>
          {kind === 'clothing' && <label>分类<TabSelect variant="field" label="分类" selected={draft.category} onChange={category => setDraft({ ...draft, category })} items={clothing.map(value => ({ value, label: value }))} /></label>}
          {kind === 'person' && <>
            <div className="asset-field-pair"><label>性别<input value={draft.profile.gender} maxLength={100} onChange={event => setProfile('gender', event.target.value)} /></label><label>年龄<input value={draft.profile.age} maxLength={100} onChange={event => setProfile('age', event.target.value)} placeholder="可填写年龄段" /></label></div>
            <label>身份<input value={draft.profile.identity} maxLength={1000} onChange={event => setProfile('identity', event.target.value)} placeholder="职业、身份或背景" /></label>
            <label>外貌特征<textarea rows={3} maxLength={20000} value={draft.profile.appearance} onChange={event => setProfile('appearance', event.target.value)} /></label>
            <label>性格<textarea rows={3} maxLength={20000} value={draft.profile.personality} onChange={event => setProfile('personality', event.target.value)} /></label>
          </>}
          <label>{kind === 'person' ? '补充资料' : '资料说明'}<textarea rows={5} maxLength={20000} value={draft.profile.description} onChange={event => setProfile('description', event.target.value)} placeholder={kind === 'person' ? '人物经历或其他需要保留的信息' : '外观、材质、颜色、用途等'} /></label>
          <div className="asset-form-actions"><button className="asset-primary" type="submit" disabled={!draft.name.trim() || (!dirty && !!saved)}>{busy ? '正在处理…' : '保存资料'}</button><span className="muted" role="status">{dirty ? '有未保存的修改' : saved ? '资料已保存' : '名称为必填项'}</span></div>
        </fieldset></form>
      </section>
      <section className="asset-images" aria-label="图片资产"><div className="asset-image-heading"><h2>图片资产</h2><span className="muted">PNG / JPG / WebP / GIF · 每张最多 25 MB</span></div>
        {(!saved || dirty) && <p className="asset-hint">先保存资料，再上传或调整图片。</p>}
        {kind === 'person' && <div className="asset-fixed-images">{(['portrait', 'views'] as Slot[]).map(slot => {
          const picture = saved?.images.find(item => item.slot === slot);
          return <section className={`asset-image-slot asset-slot-${slot}`} key={slot}><div className="asset-image-heading"><h3>{slots[slot]}</h3>{uploadControl(slot, !!picture)}</div>{picture ? pictureCard(picture) : <div className="asset-image-empty">{slot === 'views' ? '上传一张包含正面、侧面、背面的三视图' : '上传人物正面半身图片'}</div>}</section>;
        })}</div>}
        <section className="asset-album"><div className="asset-image-heading"><h3>{kind === 'person' ? '相册' : '图片'} <span className="muted">{saved?.images.filter(item => item.slot === 'album').length || 0} 张</span></h3>{uploadControl('album')}</div>
          <div className="asset-album-grid">{saved?.images.filter(item => item.slot === 'album').map(pictureCard)}</div>
          {!saved?.images.some(item => item.slot === 'album') && <div className="asset-image-empty">可以一次选择多张图片，保存不同角度和细节。</div>}
        </section>
      </section>
    </div>
    {preview && saved && <Preview project="" revision={0} item={{ kind: "image", name: preview.name, url: imageUrl(saved, preview) }} close={() => setPreview(null)} />}
    {remove && <Dialog title={remove === 'asset' ? `删除${kinds[kind]}` : '删除图片'} close={() => { if (!busy) setRemove(null); }}><p>{remove === 'asset' ? `将删除“${saved!.name}”的资料及全部图片。` : `将删除“${remove.name}”。`}此操作无法撤销。</p><div className="asset-dialog-actions"><button disabled={busy} onClick={() => setRemove(null)}>取消</button><button className="asset-danger" disabled={busy} onClick={() => void run(confirmRemove)}>确认删除</button></div></Dialog>}
    {reload && <Dialog title="重新载入资料" close={() => setReload(false)}><p>重新载入会放弃当前未保存的输入，读取最近保存的资料和图片。</p><div className="asset-dialog-actions"><button disabled={busy} onClick={() => setReload(false)}>取消</button><button disabled={busy} onClick={() => void run(async () => { const item = await api<Asset>(`/${saved!.id}`); accept(item); setDraft(cardOf(item)); setReload(false); })}>放弃输入并载入</button></div></Dialog>}
    {blocker.state === 'blocked' && <Dialog title={busy ? '正在处理' : '资料尚未保存'} close={() => blocker.reset()}><p>{busy ? '图片或资料正在保存，请等待完成。' : '离开会丢失当前未保存的资料。'}</p><div className="asset-dialog-actions"><button onClick={() => blocker.reset()}>继续编辑</button>{!busy && <button onClick={() => blocker.proceed()}>放弃修改并离开</button>}</div></Dialog>}
  </div>;
}
