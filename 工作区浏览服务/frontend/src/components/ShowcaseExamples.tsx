import { useCallback, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { FileItem, SegmentVideo as VideoItem } from '../api';
import { Document, Groups, Preview, PreviewContext, Result, Rich } from '../components';
import { SearchField } from './SearchField';
import { PageHeader } from './PageHeader';
import { Breadcrumbs } from './Breadcrumbs';
import { EntryCard } from './EntryCard';
import { PointerTooltip } from './PointerTooltip';
import { DownloadButton } from './DownloadButton';
import { FileActions, Original } from './FileActions';
import { SyncNotification } from './SyncNotification';
import { TabNav } from './TabNav';
import { AssetMedia } from './AssetMedia';
import { AssetCandidateMedia } from './AssetCandidateMedia';
import { ReferenceMediaCard } from './ReferenceMediaCard';
import { AudioPreviewButton, useAudioPreview } from './AudioPreviewButton';
import { EpisodeButton } from './EpisodeButton';
import { SegmentStageStrip } from './SegmentStageStrip';
import { SegmentVideo } from './SegmentVideo';
import { SegmentLayout } from './SegmentLayout';
import type { SegmentVideoHandle } from './SegmentVideo';
import { PromptSections } from './PromptSections';
import { TaskCard } from './TaskCard';
import { LocalQueueCard } from './LocalQueueCard';

export function ComponentExample({ title, rule, usage, children, fullWidth = false }: { fullWidth?: boolean; title: string; rule: string; usage: string; children: ReactNode }) {
  return <section className={"component-example" + (fullWidth ? " is-full-width" : "")} aria-label={title}>
    <h3>{title}</h3><p className="component-rule">{rule}</p>
    <div className="component-demo">{children}</div>
    <p className="component-usage">使用位置：{usage}</p>
  </section>;
}
const fileUrl = '/api/component-samples/file';
const image: FileItem = { kind: 'image', name: '示例图形', key: 'image.svg', url: '/component-samples/image.svg' };
const audio: FileItem = { kind: 'audio', name: '示例提示音', key: 'tone.wav', url: '/component-samples/tone.wav' };
const video: FileItem = { kind: 'video', name: '示例视频', key: 'video.webm', url: '/component-samples/video.webm' };
const imageRecord = { type: '示例参考图', media: image, version: 'v1.0', statusHtml: '<span class="status-badge status-gray">示例</span>', scope: '仅供组件展示' };
const videoRecord: VideoItem = { key: 'sample-video', url: video.url!, stage: '一采', run: 'R001', approved: true, candidateNumber: 1, fileRevision: 'sample-1', deliveryStatus: '已取回', taskStatus: '已完成', checkedAt: '' };
const segments = [{ id: 'P001', duration: 2, scriptHtml: '', videos: [videoRecord] }, { id: 'P002', duration: 3, scriptHtml: '', videos: [] }];
const sampleDoc = { html: '<h2 id="sample-text">正文与代码</h2><p>这是一份示例文档。</p><pre><code>可以复制这段示例文字。</code></pre><h2 id="sample-end">附属资料</h2><p>展开下方其他资料查看目录。</p>', headerHtml: '<p>作者：演示</p><p>用途：查看折叠信息</p>', groups: [{ name: '示例附件', files: [{ kind: 'document', name: '附属说明', doc: { html: '<p>仅供演示的附属说明。</p>' } }] }] };
const retainSample = () => () => {};

export function ShowcaseExamples({ category }: { category: string }) {
  const [text, setText] = useState('');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState('one');
  const [preview, setPreview] = useState<FileItem | null>(null);
  const close = useCallback(() => setPreview(null), []);
  const [readState, setReadState] = useState('ready');
  const [sync, setSync] = useState<{ error?: string; errorKind?: string; retryAt?: number; updating?: boolean }>({});
  const [wide, setWide] = useState(false);
  const [time, setTime] = useState(0);
  const [segment, setSegment] = useState('P001');
  const [vertical, setVertical] = useState(false);
  const [queueState, setQueueState] = useState('local_queued');
  const [action, setAction] = useState('尚未操作');
  const [started] = useState(() => new Date().toISOString());
  const playerRef = useRef<SegmentVideoHandle>(null);
  const sound = useAudioPreview(category === 'media', null, 1);
  return <PreviewContext.Provider value={setPreview}>
    {category === 'layout' && <>
      <ComponentExample fullWidth title="标题与路径导航" rule="页面标题可带说明和操作区；纵向内容使用stacked规格统一间距；点击路径返回上一级示例。" usage="项目、资产、风格库、开发记录">
        <PageHeader eyebrow="示例栏目" title="示例页面" description="这里展示公共页面标题。" actions={<button onClick={() => setText('已点击标题操作')}>示例操作</button>} />
        <PageHeader stacked title="带附属内容的示例标题"><span>示例阶段信息</span><span>示例路径信息</span></PageHeader>
        <Breadcrumbs items={[{ label: '示例列表', href: '#/history', onClick: () => setText('已返回示例列表') }, { label: '示例详情' }]} />
        <p role="status">{text || '试试右侧操作或路径链接。'}</p>
      </ComponentExample>
      <ComponentExample title="入口卡片与搜索" rule="输入文字筛选示例；点击卡片按正常链接跳转至网站入口页，会离开展示页。" usage="首页、资料目录、资产与风格库">
        <div className="component-demo-stack"><SearchField label="搜索示例入口" placeholder="搜索示例…" value={search} onChange={setSearch} />
        <SearchField size="compact" label="紧凑搜索示例" placeholder="紧凑搜索…" value={search} onChange={setSearch} /><SearchField label="禁用搜索示例" placeholder="不可搜索" value="" onChange={setSearch} disabled />
        {(!search || '公共组件示例'.includes(search)) ? <EntryCard to="/" title="公共组件示例" description="返回网站入口页" icon="▤" /> : <p className="muted">没有匹配的示例。</p>}</div>
      </ComponentExample>
      <ComponentExample title="导航的分组与方向" rule="同一组件支持横排、竖排、紧凑和分组下拉；加宽规格用于项目顶部，竖排示例在手机上改为两列。禁用项不可选择。" usage="顶部栏目、侧栏、制作模式">
        <TabNav wide label="示例分组导航" selected={selected} onChange={setSelected} groups={[{ label: '示例分组', values: ['two', 'three'] }]} items={[{ value: 'one', label: '普通页签' }, { value: 'two', label: '子项甲' }, { value: 'three', label: '子项乙' }, { value: 'disabled', label: '禁用页签', disabled: true }]} />
        <TabNav label="示例竖排导航" vertical mobileLayout="grid" compact selected={selected} onChange={setSelected} items={[{ value: 'one', label: '示例甲' }, { value: 'two', label: '示例乙' }]} />
      </ComponentExample>
      <ComponentExample title="悬停与键盘提示" rule="悬停或键盘聚焦显示说明，移开或按Esc关闭；提示不挤动布局。" usage="长标题、播放入口、状态详情">
        <PointerTooltip text="这是公共提示框的完整说明。"><button>查看悬停说明</button></PointerTooltip>
      </ComponentExample>
    </>}
    {category === 'files' && <>
      <ComponentExample title="原文件与下载" rule="查看和下载使用固定示例文本。下载会保存component-sample.txt，不读取项目文件。" usage="文件目录、资料卡、制作资源下载">
        <div className="component-demo-row"><Original url={fileUrl} label="示例原文件" /><FileActions url={fileUrl} /></div>
        <DownloadButton url={fileUrl + '?download=true'} label="下载示例文件" title="组件示例文件" />
        <FileActions url={fileUrl} downloadOnly />
        <DownloadButton url={null} file={{ text: "本地导出示例。\n", name: "component-export.md", type: "text/markdown;charset=utf-8" }} label="下载本地导出示例" title="本地导出示例" />
        <DownloadButton url={null} label="没有文件时禁用" title="暂无示例文件" />
      </ComponentExample>
      <ComponentExample title="文档信息与附属资料" rule="文档信息、章节导航、代码复制和其他资料均由真实文档组件渲染。" usage="项目文档、资料卡、开发记录弹窗">
        <Document value={sampleDoc} showOriginal={false} />
        <Groups groups={[{ name: '普通分组示例', files: [{ kind: 'document', name: '分组文件', doc: { html: '<p>普通分组中的示例文件。</p>' } }] }]} />
      </ComponentExample>
      <ComponentExample title="提示词分节与正文" rule="已识别的提示词字段可折叠；正文和状态标签沿用统一排版。" usage="视频提示词、文档正文与资产状态">
        <PromptSections language="zh" text={'summary: 示例概述\ndetailed_description: 仅供演示的详细描述\noverall_soundscape: 示例声景'} />
        <Rich html={'<p>示例状态：<span class="status-badge status-gray">待确认</span> <span class="status-badge status-green">已完成</span></p>'} />
      </ComponentExample>
    </>}
    {category === 'states' && <>
      <ComponentExample title="加载与读取重试" rule="手动切换示例状态；失败提示中的重新读取恢复本地示例，不发起资料请求。" usage="各页查询、详情和预览">
        <div className="component-demo-row"><button onClick={() => setReadState('loading')}>显示加载</button><button onClick={() => setReadState('error')}>模拟读取失败</button><button onClick={() => setReadState('ready')}>结束加载</button></div>
        <Result loading={readState === 'loading'} error={readState === 'error' ? new Error('示例读取错误') : null} retry={() => setReadState('ready')} retrying={false} />
        {readState === 'ready' && <p role="status">示例资料已就绪。</p>}
      </ComponentExample>
      <ComponentExample title="同步反馈" rule="倒计时来自示例时间；重试状态与结束由下方按钮控制，不连接项目同步。" usage="项目资料检查">
        <div className="component-demo-row"><button onClick={() => setSync({ error: '示例同步错误', retryAt: Date.now() + 5000 })}>模拟同步失败</button><button onClick={() => setSync({ error: '示例资料变动', errorKind: 'source_changed', retryAt: Date.now() + 5000 })}>模拟资料更新</button><button onClick={() => setSync({ updating: true })}>模拟重试中</button><button onClick={() => setSync({})}>结束同步演示</button></div>
        <SyncNotification {...sync} />
      </ComponentExample>
    </>}
    {category === 'media' && <>
      {sound.player}
      <ComponentExample fullWidth title="图片与候选卡片" rule="点击图片在公共预览中放大；候选分组按类型展开。图片为随服务提供的示例图形。" usage="人物、场景、道具、封面">
        <AssetMedia items={[imageRecord]} revision={1} formal />
        <AssetCandidateMedia items={[imageRecord]} revision={1} />
      </ComponentExample>
      <ComponentExample title="音视频卡片与试听" rule="试听播放2秒轻提示音，可暂停；视频入口打开公共预览。无音频时按钮禁用。" usage="参考音视频、人物音色">
        <ReferenceMediaCard item={{ kind: 'reference', name: audio.name, media: audio, approvalHtml: '<span class="status-badge status-gray">示例</span>' }} audio playing={sound.playingId === 'sample'} progress={sound.progress} onPlay={() => sound.toggle('sample', audio.url!)} onSelect={() => setPreview(audio)} />
        <ReferenceMediaCard item={{ kind: 'reference', name: video.name, media: video }} audio={false} playing={false} progress={0} onPlay={() => setPreview(video)} onSelect={() => setPreview(video)} />
        <AudioPreviewButton name="缺少参考音频的示例" enabled={false} playing={false} progress={0} onClick={() => {}} />
      </ComponentExample>
      <ComponentExample fullWidth title="分段播放器" rule="示例使用制作页同一份布局；宽屏时显示右侧分段导航，手机上的视频操作区使用整行宽度。" usage="剧集制作分段视频">
        <SegmentLayout wide={wide} navigation={<SegmentStageStrip segments={segments} selected={segment} onSelect={setSegment} vertical newVideoSegments={new Set(['P001'])} previousEnding={null} previousSelected={false} onPreviousSelect={() => {}} />} player={<SegmentVideo current={videoRecord} onTimeChange={setTime} retainSource={retainSample} wide={wide} onToggleWide={() => setWide(!wide)} continuousControl={null} playerRef={playerRef} />}>
          <section className="segment-script"><Rich html="<h3>示例分镜</h3><p>切换宽屏可查看播放器与分段导航的共同布局。</p>" /></section>
        </SegmentLayout>
        <p>示例播放位置：{time.toFixed(1)}秒</p><button onClick={() => playerRef.current!.seekTo(1)}>跳到1秒</button>
      </ComponentExample>
    </>}
    {category === 'production' && <>
      <ComponentExample title="选集按钮" rule="点击只更新示例选集，题名和状态使用正式组件排版。" usage="分集大纲、剧集制作">
        <EpisodeButton item={{ kind: 'episode', name: 'EP001', title: '组件演示集', titleStatus: '工作集名', statusHtml: '<span class="status-badge status-gray">未开始</span>' }} onSelect={setSelected} /><p>已选择：{selected === 'one' ? '尚未选集' : selected}</p>
      </ComponentExample>
      <ComponentExample fullWidth title="分段与制作状态" rule="P001标记本轮新生成；可切换分段和横竖布局，悬停状态图标查看详情。" usage="分段制作、宽屏分段导航">
        <button onClick={() => setVertical(!vertical)}>{vertical ? '切换横排' : '切换竖排'}</button>
        <SegmentStageStrip segments={segments} selected={segment} onSelect={setSegment} vertical={vertical} newVideoSegments={new Set(['P001'])} previousEnding={null} previousSelected={false} onPreviousSelect={() => {}} />
        <p>当前分段：{segment}</p>
      </ComponentExample>
    </>}
    {category === 'tasks' && <>
      <ComponentExample fullWidth title="运行任务卡片" rule="显示固定示例进度，可以展开详情；没有提交或轮询生成任务。" usage="全局任务进度">
        <TaskCard task={{ id: 'showcase-running', project: '示例项目', title: '组件展示任务', task_type: 'image', prompt_id: null, status: 'running', connection: 'connected', node: '示例节点', remote_url: '', progress: { value: 3, max: 10 }, error: null, collected: 0, expected: 1, created_at: started, started_at: started, source_session_name: '本地组件演示' }} />
      </ComponentExample>
      <ComponentExample fullWidth title="排队任务卡片" rule="暂停、恢复、插队和提交按钮只更新演示状态，不操作真实队列。" usage="全局待提交与暂停列表">
        <LocalQueueCard task={{ queue: 'local', id: 'showcase-queued', project: '示例项目', title: '本地演示队列', task_type: 'image', status: queueState, remote_url: '', created_at: started, source_session_name: '本地组件演示' }} position={1} onAction={(_id, next) => { setAction(({ pause: '已暂停示例', resume: '已恢复示例', immediate: '已模拟立即提交', insert: '已模拟插队' } as Record<string, string>)[next]); if (next === 'pause' || next === 'resume') setQueueState(next === 'pause' ? 'paused' : 'local_queued'); }} />
        <p role="status">{action}</p>
      </ComponentExample>
    </>}
    {category === 'coverage' && <>
      <ComponentExample title="全站框架就在当前页面" rule="这些组件在当前页面已真实运行，不重复嵌套第二套页头或任务侧栏。" usage="所有页面">
        <ul><li>AppShell：顶部、正文与公共页脚。</li><li>ProjectSwitcher：左上角品牌旁的项目菜单。</li><li>TaskSidebar：左侧任务栏。</li><li>Notifications：左下角消息。</li><li>PageCheckStatus：页脚最近检查时间，使用实际查询结果。</li><li>BottomTools：页面向下滚动后出现的返回顶部按钮，并避让消息。</li></ul>
      </ComponentExample>
      <ComponentExample title="展示范围与业务模块" rule="可复用控件及业务卡片在各分类演示；下列整页业务模块需要真实资料，保留在原页面，不在这里启动真实业务。" usage="项目制作、任务管理与设置">
        <p>EpisodeProduction、EpisodeOutlines、SceneWorkspace、SegmentWorkspace、SceneDirectorSheets、SceneStoryboardEditor、RevisionNoteEditor、SceneDownloads、CoverLibrary、ReferenceLibrary属于业务页面或流程；TaskHistory、TaskDetailDialog、NodeEditor负责真实任务和节点数据。</p>
        <p>它们使用的按钮、导航、文档、媒体、消息、卡片及分页已在对应分类展示。Context、数据查询和缓存Hook属于内部逻辑，随所属组件验证。</p>
        <p>新增或修改公共组件时，必须在同次改动中同步这里的真实演示、说明与相关状态检查。</p>
      </ComponentExample>
    </>}
    {preview && <Preview project="" item={preview} revision={1} close={close} />}
  </PreviewContext.Provider>;
}
