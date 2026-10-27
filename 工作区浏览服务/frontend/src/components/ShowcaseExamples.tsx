import { useCallback, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import type { FileItem, SegmentVideo as VideoItem } from '../api';
import { Document, FileTree, Groups, Preview, PreviewContext, Result, Rich } from '../components';
import { SearchField } from './SearchField';
import { PageHeader } from './PageHeader';
import { EpisodeTitleStatus } from './EpisodeTitleStatus';
import { Breadcrumbs } from './Breadcrumbs';
import { EntryCard } from './EntryCard';
import { PointerTooltip } from './PointerTooltip';
import { DownloadControl } from './DownloadControl';
import { DownloadButton } from './DownloadButton';
import { FileActions, Original } from './FileActions';
import { SyncNotification } from './SyncNotification';
import { TabNav } from './TabNav';
import { AssetMedia } from './AssetMedia';
import { AssetMediaCard } from './AssetMediaCard';
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
import { ReleaseFilms } from './ReleaseFilms';
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
const imageDetails: FileItem = { kind: 'document', name: '图片详情示例', key: 'asset-details-demo', doc: { html: '<p>本地图片详情示例。</p>' } };
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
  const [continuous, setContinuous] = useState(false);
  const [repeat, setRepeat] = useState(false);
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
        <Breadcrumbs items={[{ label: '示例列表', href: '#/history', onClick: () => setText('已返回示例列表') }, { label: <>EP001 · 组件演示集 <EpisodeTitleStatus status="最终定名" /></> }]} />
        <p role="status">{text || '试试右侧操作或路径链接。'}</p>
      </ComponentExample>
      <ComponentExample title="入口卡片与搜索" rule="搜索框支持长文字、清空与禁用，窄容器不越界。输入文字筛选示例；点击卡片按正常链接跳转至网站入口页，会离开展示页。" usage="首页、资料目录、资产与风格库">
        <button onClick={() => setSearch('中文长搜索条件' + 'LongSearchReference'.repeat(8))}>填入长搜索文字</button>
        <div className="component-demo-stack"><SearchField label="搜索示例入口" placeholder="搜索示例与较长的关键词说明…" value={search} onChange={setSearch} />
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
      <ComponentExample fullWidth title="发布成片选集与播放" rule="按实际一级目录提供片头、片尾、成片三个固定子标签，默认片头；根目录或其他目录有旧视频时额外显示未分类，不按文件名猜类别、不移动文件。各类递归读取视频，沿用原路径自然数字排序及片头／片尾同名视频优先规则，每页5个实际文件名（不带扩展名）。分类不超过5个视频时只显示文件名，超过5个才显示上一页和下一页，末页不足5个也保留翻页。切类卸载原播放器并回到第一页。选集靠左，右侧下载当前选集；窄屏可换行，文件名单行滚动。项目标题显示全部视频总数；视频居中保留原比例，不自动播放。这里只播放和下载固定示例媒体。" usage="项目发布成片；UnderlineTabs、Pagination、TabNav和DownloadButton的既有规格">
        <ReleaseFilms items={[
          { kind: 'group', name: '片头', children: [{ ...video, name: '先导版.webm', key: '示例/片头/先导版.webm' }] },
          { kind: 'group', name: '片尾', children: [{ ...video, name: '结束版.webm', key: '示例/片尾/结束版.webm' }] },
          { kind: 'group', name: '成片', children: Array.from({ length: 12 }, (_, index) => ({ ...video, name: `第${index + 1}集.webm`, key: `示例/成片/第${index + 1}集.webm` })) },
          { ...video, name: '旧导出示例.webm', key: '示例/旧导出示例.webm' },
        ]} />
      </ComponentExample>
      <ComponentExample fullWidth title="只读文件目录" rule="直接使用公共文件树，按文件与子目录浏览，保留空目录。列表只保留文件名预览入口，不显示确认状态；查看与下载放在预览弹窗中，不提供改名、移动或删除。示例不使用真实项目文件。" usage="仅文件名入口的目录资料">
        <FileTree showOriginal={false} showStatus={false} items={[{ kind: 'video', name: '示例发布成片.webm', url: video.url },
          { kind: 'group', name: '分平台', children: [{ kind: 'video', name: '示例竖屏版本.webm', url: video.url }] },
          { kind: 'group', name: '待导出空目录', children: [] }]} />
      </ComponentExample>
      <ComponentExample title="原文件与下载" rule="下载统一使用描边加图标，15px文字、7px圆角和相同内边距；准备中替换为转圈图标，禁用状态降低透明度。查看和下载使用固定示例文本。下载会保存component-sample.txt，不读取项目文件；支持自定义文案、仅下载及整行居中。图片预览使用居中的仅下载规格，其他文件默认保留查看和下载。" usage="文件目录、资料卡、制作资源下载">
        <div className="component-demo-row"><Original url={fileUrl} label="示例原文件" /><FileActions url={fileUrl} /></div>
        <DownloadButton url={fileUrl + '?download=true'} label="下载示例文件" title="组件示例文件" />
        <FileActions url={fileUrl} downloadOnly centered />
        <FileActions url={fileUrl} viewLabel="查看原图" downloadLabel="下载原图" />
        <DownloadButton url={null} file={{ text: "本地导出示例。\n", name: "component-export.md", type: "text/markdown;charset=utf-8" }} label="下载本地导出示例" title="本地导出示例" />
        <DownloadButton url={null} label="没有文件时禁用" title="暂无示例文件" />
        <DownloadControl label="正在准备…" busy title="准备中外观示例，不发起下载" />
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
      <ComponentExample fullWidth title="图片与候选卡片" rule="尺寸来自加载图片的真实像素宽高，网页计算并在括号显示最简比例。点击图片在公共预览中放大，只保留整行居中的下载入口；候选分组按类型展开。图片为随服务提供的示例图形。已登记但尚未生成时可通过emptyLabel说明空态。查看详情固定在底部右侧，生成记录保留左侧；下方记录和详情使用本地示例正文。" usage="人物、场景、道具、封面">
        <AssetMedia items={[imageRecord]} revision={1} formal />
        <AssetCandidateMedia items={[imageRecord]} revision={1} />
        <PreviewContext.Provider value={item => setPreview(item.kind === 'markdown' ? { ...item, kind: 'document', doc: { html: '<p>本地示例生成记录。</p>' } } : item)}>
          <div className="asset-media-grid">
            <AssetMediaCard title="仅有查看详情" item={imageRecord} revision={1} formal onDetails={() => setPreview(imageDetails)} />
            <AssetMediaCard title="已登记尚未生成" item={{ emptyLabel: '尚未生成图片' }} revision={1} onDetails={() => setPreview(imageDetails)} />
            <AssetMediaCard title="生成记录与查看详情" item={{ ...imageRecord, recordUrl: '/component-samples/files/示例生成记录.md', generation: '生成记录-示例' }} revision={1} formal onDetails={() => setPreview(imageDetails)} />
          </div>
        </PreviewContext.Provider>
      </ComponentExample>
      <ComponentExample title="音视频卡片与试听" rule="试听播放2秒轻提示音，可暂停；视频入口打开公共预览。无音频时按钮禁用。" usage="参考音视频、人物音色">
        <ReferenceMediaCard item={{ kind: 'reference', name: audio.name, media: audio, approvalHtml: '<span class="status-badge status-gray">示例</span>' }} audio playing={sound.playingId === 'sample'} progress={sound.progress} onPlay={() => sound.toggle('sample', audio.url!)} onSelect={() => setPreview(audio)} />
        <ReferenceMediaCard item={{ kind: 'reference', name: video.name, media: video }} audio={false} playing={false} progress={0} onPlay={() => setPreview(video)} onSelect={() => setPreview(video)} />
        <AudioPreviewButton name="缺少参考音频的示例" enabled={false} playing={false} progress={0} onClick={() => {}} />
      </ComponentExample>
      <ComponentExample fullWidth title="分段播放器" rule="示例使用制作页同一份布局；示例使用受控重复播放；业务页在同一集跨场、换段或换版本时保持播放偏好。重复播放默认关闭，勾选后循环当前视频；连续播放开启会关闭并禁用重复播放，取消连续播放后不自动恢复。业务页连续播放可按本集轮次跨场次接续；此处仅演示互斥开关，不播放项目队列。宽屏时显示右侧分段导航，手机操作区使用整行宽度。" usage="剧集制作分段视频">
        <SegmentLayout wide={wide} navigation={<SegmentStageStrip segments={segments} selected={segment} onSelect={setSegment} vertical newVideoSegments={new Set(['P001'])} previousEnding={null} previousSelected={false} onPreviousSelect={() => {}} />} player={<SegmentVideo repeatControl={{ checked: repeat, onChange: setRepeat }} current={videoRecord} onTimeChange={setTime} retainSource={retainSample} wide={wide} onToggleWide={() => setWide(!wide)} continuous={continuous} continuousControl={<label className="scene-continuous"><input type="checkbox" checked={continuous} onChange={event => setContinuous(event.target.checked)} />连续播放</label>} playerRef={playerRef} />}>
          <section className="segment-script"><Rich html="<h3>示例分镜</h3><p>切换宽屏可查看播放器与分段导航的共同布局。</p>" /></section>
        </SegmentLayout>
        <p>示例播放位置：{time.toFixed(1)}秒</p><button onClick={() => playerRef.current!.seekTo(1)}>跳到1秒</button>
      </ComponentExample>
    </>}
    {category === 'production' && <>
      <ComponentExample fullWidth title="选集按钮" rule="点击只更新示例选集；制作页最多两列，窄屏单列。可在制作状态前显示时长，*表示含计划值；大纲不显示时长。集名状态与制作进度独立。" usage="分集大纲、剧集制作">
        <div className="episode-grid episode-grid-pairs">{(['待定集名', '临时集名', '最终定名'] as const).map((titleStatus, i) => <EpisodeButton key={titleStatus} duration={['1分20秒', '2分5.5秒*', undefined][i]} item={{ kind: 'episode', name: `EP00${i + 1}`, title: titleStatus === '待定集名' ? '待定' : '组件演示集与很长的题名显示检查', titleStatus, statusHtml: '<span class="status-badge status-gray">未开始</span>' }} onSelect={setSelected} />)}</div><p>已选择：{selected === 'one' ? '尚未选集' : selected}</p>
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
      <ComponentExample title="全站框架就在当前页面" rule="这些组件在当前页面已真实运行，不重复嵌套。任务侧栏点击外部收起，侧栏菜单、详情和通知操作不误关；本地队列保持排序滚动位置，处理进度及结果使用左下角公共消息。交互回归使用隔离队列，不以演示操作真实任务。" usage="所有页面">
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
