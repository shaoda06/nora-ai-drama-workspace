# 通用 ComfyUI 执行工具

入口：[comfyui_client.py](comfyui_client.py)。Python 3.9+，仅标准库；安装位置属于短剧技能，代码不包含短剧业务。与 `comfyui-api` 技能结合使用：技能提供连接、接口与安全规则，脚本执行上传、提交、单轮查询、下载和原生导演包导出。节点／模型检查仍按 `comfyui-inventory`；故障按 `comfyui-troubleshooter`。

## 使用边界

- agent 按当前业务规范准备最终 **API 格式节点 JSON**、参考素材映射和全部参数；脚本不修改提示词、种子、节点或连线，不转换画布 JSON，不内置工作流模板。
- 上述已有能力必须复用此脚本，不按任务新写 Python／shell／内联 HTTP 实现。准备 API JSON、整理业务记录和审核仍由 agent 完成。发现脚本缺陷先报告并集中修复，缺少接口则明确缺口后处理，不悄悄回退成一套临时执行器。
- 只处理当前获得授权的任务；不启动下一阶段、不自动重试提交、不管理定时器、不操作队列删除／中断／卸载／服务器配置。
- 不决定项目路径、命名、审批或归档，不生成或维护项目工作稿，不移动候选至选定。图片由agent核对文件与执行记录后交用户审核，默认不调用看图能力或自动重试；批准后超分沿用对应专项规则。视频直接交人工审核。
- 五个命令相互独立。已有远端素材可以复用；新本地素材先上传，agent 再把返回路径写入 API JSON。接口验证／节点发现等不在这些命令内的只读操作仍可按对应技能执行。

## 调用

以下相对路径示例在本 README 所在目录执行；跨会话优先使用脚本绝对路径。每个命令的参数以 `python3 comfyui_client.py COMMAND --help` 为准。

所有命令支持 `--url`、`--timeout`、`--result`：

- `--url` 优先，其次 `COMFYUI_URL`；均未提供就报错。脚本没有默认服务器。agent 从当前任务或 `comfyui-api` 配置确定地址再传入，不自行改全局设置。
- `--timeout` 默认30秒，表示网络阻塞操作超时，不是整个生成任务的时限。大素材可按实际情况明确设置更长值；不自动重试 HTTP。禁止带凭据的 URL，不跟随 HTTP 重定向。
- `--result` 可指定一个**尚不存在**的 JSON 文件。调用前独占创建，避免网络操作成功后才发现目标冲突；异常结果也会保存。省略时仅写标准输出，agent负责留存。文件不得覆盖；是否落盘由调用方的留档规则决定。
- 除 `--help` 外，标准输出为 JSON；退出码0表示本次工具操作成功，1表示工具错误。`status` 返回 `state=failed` 仍可能退出0，意为“查询成功、任务失败”，不是生成成功。

### upload：上传原始字节

```sh
python3 comfyui_client.py upload --url 'http://SERVER:8188' \
  --file '/absolute/path/reference.png' --subfolder 'unique-task-inputs' \
  --result '/absolute/path/upload-response.json'
```

通过 `/upload/image` 的 multipart `image` 字段提交文件，`type=input`、`overwrite=false`；不限制扩展名，但是否能由工作流加载需另行核对。使用临时磁盘流构建请求，不把整个视频读入内存；不转码、裁剪或处理媒体。

返回 `data.remote`（服务器的 name/subfolder/type）、`data.input_path`（正斜杠输入相对路径）、上传字节数及SHA-256。同名文件服务器可能重命名或复用，必须使用实际返回值，不按本地文件名推断。上传结果不明时先查已有响应／服务器文件，不能宣称文件未上传或无限重传。

### submit：只提交一次

```sh
python3 comfyui_client.py submit --url 'http://SERVER:8188' \
  --workflow '/absolute/path/task.api.json' \
  --record-dir '/absolute/path/execution-record'
```

接收节点对象，不接受画布格式或已经包了一层 `prompt` 的请求。只做JSON及基本结构检查，节点／模型存在性、允许参数、素材批准和生成授权由agent预先确认。原节点对象作为 `prompt` 原样封装，额外生成唯一 `client_id`。JSON数字使用Python整数，不把大种子转换成浮点。

提交前先独占保存防重标记、完整请求，随后只发送一次 POST；返回 `data.prompt_id`、`data.client_id`、实际响应和记录目录。记录默认名称：

| 文件 | 内容 |
| --- | --- |
| `submit-attempt.json` | 服务地址、时间、client ID、请求哈希；保留即阻止重复提交 |
| `request.json` | 实际发送的完整请求 |
| `response.json` | 原始成功响应，或拒绝／不明状态及错误证据 |

agent 可通过 `--attempt-name`、`--request-name`、`--response-name` 指定当前业务规定的文件名（均为单个文件名，不能是路径）。例如视频使用 `提交尝试.json`、`请求.json`、`提交响应.json`；图片使用该任务规定的带编号附件名，**不要求新建额外管理目录**。这些名称只是调用参数，不是脚本内置业务规则。`--result` 不可与上述文件重名。

**同一逻辑提交必须沿用同一记录目录与文件名。** 发现任一证据已存在即拒绝提交，包括超时和先前被拒绝的请求。不要换目录、换证据文件名或删除防重标记绕过检查；这是本地记录范围的保护，不是服务器全局幂等，也不能保证跨目录“恰好一次”。

请求超时、响应丢失、无有效prompt ID或服务器5xx时视为提交状态不明；用已保存client ID／请求核对队列及必要历史，不自动重发。正常 `status` 需要真实prompt ID；尚未找回ID时按 `comfyui-api` 做只读核对。只有确认原任务未接受且获得相应方向后才建立新的提交尝试。明确4xx拒绝也保留记录，修正后的新尝试不可覆盖旧证据。

### status：单轮查询

```sh
python3 comfyui_client.py status --url 'http://SERVER:8188' \
  --prompt-id 'REAL-PROMPT-ID'
```

先查指定history，非明确终态再核对queue。只返回本任务证据，不保存其他任务的提示词。状态为 `queued`、`running`、`success`、`failed`、`unknown`。`running`仅表示在运行队列，不证明采样步数正在推进；`success`须服务端明确completed与success且无错误／中断事件，**不等于业务要求的输出齐备或内容获批**。

`data.files`列出返回文件的node_id/output_key/index及原始文件信息；不替agent选择输出。agent核对本次预期节点及具体文件后再下载。原始任务history保留于返回JSON。网络故障是工具错误，不把任务标成失败。不自动等待、定时或启动下一阶段。

### 只读诊断与重启证据

CLI的status已查询history／queue，诊断不要为保存响应重复调用。其他只读核对复用本模块的`Client(url, timeout)`：`client.json(route)`读取JSON，`with client.open(route) as response`读取有界原始日志／响应头；不提供data时为GET，不写另一套HTTP通信。保存当轮返回和本地观察时间，重复错误沿用既有证据。具体次数、间隔及判定由[监控规范](../流程规范/ComfyUI-任务监控规范.md#31-异常检查与连接恢复)维护，客户端自身不循环或判断是否补做。

`/system_stats`是连通性／设备快照，没有本工具保证的进程ID、启动时间或每次启动变化的实例标识；相同GPU、版本、URL不能证明同一实例或发生重启。`/internal/logs/raw`及`/vhs/getpath`属于执行端可选接口，仅在实际已确认可用时读取；目录列表限任务已绑定绝对目录，不扫描猜目录。原始日志读取限定大小（例如最多1 MiB），接口缺失如实报告，不安装节点、修改服务或臆造启动标识接口。没有直接进程证据时，按[视频恢复规则](../流程规范/ComfyUI-任务监控规范.md#51-后端故障后的视频接续)核对组合证据，不能由客户端的请求成功代替业务判定。

### download：明确指定文件

```sh
python3 comfyui_client.py download --url 'http://SERVER:8188' \
  --filename 'actual-file.mp4' --subfolder 'actual/subfolder' --type output \
  --output '/absolute/path/candidate.mp4' --result '/absolute/path/download-response.json'
```

三个远端字段来自上传响应或指定任务的输出。`--type`必须显式为input/output/temp；支持服务器返回的Windows子目录分隔符及Unicode、空格，按真实值URL编码。不得猜测文件名或替换成别的任务输出。

流式下载至目标同目录临时文件，核对HTTP长度（如提供）并计算SHA-256；可用 `--sha256` 核对已知传输哈希。完整后采用不可覆盖的原子发布；中断／失败清理本次临时文件，不留下伪装完成的目标。目标已有文件则拒绝，不自行替换、比较后采用或重命名。文件系统不支持原子硬链接时报告错误，不退回覆盖写入。

这些是传输完整性检查，不读取媒体内容、不调用ffprobe／ASR、不解码视频、不进行图片视觉审核。返回 `data.path/bytes/sha256/remote`；业务元数据及审批由agent维护。

### export-pack：从保存的API导出原生导演包

```sh
python3 comfyui_client.py export-pack --url 'http://SERVER:8188' \
  --workflow '/absolute/path/task.api.json' --node-id 'DIRECTOR-NODE-ID' \
  --output '/absolute/path/director.mmxpack.zip' \
  --result '/absolute/path/pack-export-response.json'
```

用于按需交付网页画布可导入的原生 `.mmxpack.zip`。`--workflow`、`--node-id`、`--output`均必填；输入必须是保存的API节点对象，指定节点必须为 `MiniMaxH3Director`。读取其 `timeline_data` 和原生导出使用的steps、sampler、scheduler、cfg、shift_video、shift_audio、seed、task_type控件。控件须为直接值，不接受外接连线代替值。相对路径按调用工作目录解析，建议传绝对路径；目标须以 `.mmxpack.zip` 结尾且尚不存在。

源文件不改写；网页尚未保存的编辑内容不会包含在包里。调用方先按[导演包制作规范](../生成规范/ComfyUI-MiniMaxH3导演包制作规范.md)核对时间线与素材，并选取这些远端素材实际所在的服务。

先向 `/minimax/director/export_pack` POST `dryRun=true` 核对缺失素材，再向同一接口POST实际导出。服务读取素材并创建临时ZIP，命令接收JSON/base64或二进制ZIP响应，在本机保存包与可选响应JSON；不调用 `/prompt`、不导入包、不运行生成或改动模型。远端临时导出文件的生命周期由原生接口管理，不操作采样缓存。

缺失素材会报 `missing_assets` 并停止；HTTP拒绝／超时按通用错误返回，不自动重试。传输长度、ZIP条目CRC及原生格式标识检查通过后，才以不可覆盖的原子方式发布文件。失败清理本次本地临时文件，已有包不覆盖。检查ZIP不解码媒体，也不代表网页导入已实测。

成功返回 `data.path/bytes/sha256/source_workflow/node_id/download_name/preflight/zip_entries`。响应不留存大段base64；`preflight.fileCount`是原生接口收集的媒体条目数，可能包含编辑草稿中的副本，不等于去重后素材数。模型、Refine及SIGMAS等完整画布设置不在包内，网页导入步骤和边界读取上述规则。

## 回归测试与验证边界

纯函数／文件安全回归测试（不启动本地服务、不访问远端）：

```sh
python3 -B -m unittest discover -s '/absolute/path/comfyui-scripts' -p 'test_*.py' -v
```

覆盖请求不改写、大整数种子、重复提交、POST超时不重试、状态分类、不泄漏其他任务、半下载清理及并发落盘防覆盖；导演包覆盖JSON/base64与二进制响应、原时间线与大种子保留、缺素材停止、错误节点、已有文件及坏包／截断不落成品。POST响应丢失和并发下载边界使用单元测试注入，不通过破坏远端制造故障。真实任务排队中／运行中状态、长时间网络中断、任意自定义节点和认证网关不据此宣称全部实测。

## Nora 项目配置与分享边界

Nora服务配置与任务地址绑定读取[项目ComfyUI配置](../流程规范/ComfyUI-服务配置与任务提交规范.md#项目-comfyui-配置)。新任务经下方统一入口调用本工具；已有任务查询与下载将其实际提交地址显式传入 `--url`。本工具不另维护业务配置规则。新记录使用执行机器本地时区及偏移，协议原始时间戳如实保存。

Nora任务准备、查询和取回时，读取[监控规范的精简留档规则](../流程规范/ComfyUI-任务监控规范.md#执行附件精简留档)，据此确定附件留存及当前检查时间的维护。

## Nora统一分配与提交

入口：[comfyui_dispatch.py](../../scripts/comfyui_dispatch.py)，Python 3.9+标准库。项目新任务使用此入口；配置字段、选端条件、例外和任务地址绑定以[项目服务配置](../流程规范/ComfyUI-服务配置与任务提交规范.md#项目-comfyui-配置)为准。本节只维护调用接口，不另定义调度规则。脚本在单次调用中读取配置与队列，按已核对的候选范围选端并上传；默认交给工作区浏览服务提交、监听和取回，显式legacy模式直接复用submit。不生成提示词、不审批素材、不刷新库存、不创建heartbeat，不等待生成、不循环重试。

调用前准备最终API副本，并分别核对候选远端的节点、模型、接口与素材。将本次实际已核对可用的地址通过重复 `--eligible-url` 提供；这不是脚本自行发现的能力保证。若API已经含有上传路径，仅将这些路径在该远端已核实可用的服务列入候选；需要跨远端使用的本地素材通过下方上传映射绑定，不能把A的文件名直接带到B。

```sh
python3 /实际技能目录/scripts/comfyui_dispatch.py \
  --project '/实际项目目录' --task-type image \
  --workflow '/实际附件目录/本任务-工作流.json' \
  --eligible-url 'http://已核对远端A:8188' \
  --eligible-url 'http://已核对远端B:8188' \
  --record-dir '/实际附件目录' \
  --attempt-name '本任务-提交尝试.json' \
  --request-name '本任务-请求.json' \
  --response-name '本任务-提交响应.json' \
  --history-name '本任务-执行结果.json' \
  --output-plan '/实际附件目录/成果取回映射.json'
```

所有路径以调用时工作目录解析，建议使用绝对路径。完整参数可用 `python3 /实际技能目录/scripts/comfyui_dispatch.py --help` 查询：

| 参数 | 含义 |
| --- | --- |
| `--project` | 含项目配置的根目录；必填 |
| `--task-type` | 当前获授权阶段；必填，采用下表固定值 |
| `--target-url` | 用户明确指定的执行地址；可选，必须已配置且已核对能力，限定一台端且不回退；不从eligible范围推断用户指定 |
| `--allow-queue` | 仅用户明确允许本任务排队时使用；跳过已有视频任务及等待数量门槛的忙碌判断，仍核对可连接、能力、素材、原提交证据及锁，不改变默认选端或未来任务策略 |
| `--workflow` | 最终API节点JSON，必填；只在内存替换声明上传的输入路径，原文件不改写；实际请求保存完整最终图 |
| `--eligible-url` | 已核对能力及现有素材的候选地址；必填，可重复；必须属于项目列表 |
| `--uploads` | 可选本地素材上传映射JSON；省略时不上传，API中的远端路径必须已核实 |
| `--record-dir` | 本任务既定证据目录，必填；视频任务先准备输入映射，提交入口自动保存当次资料，不另建调度台账 |
| `--attempt-name`、`--request-name`、`--response-name` | 单个证据文件名；默认沿用通用submit的三个名称，实际项目传入既定命名 |
| `--timeout` | 每次网络操作超时秒数，默认30；不是生成或排队时限 |
| `--monitor` | 默认browser：由已启动的工作区浏览服务提交与监控；legacy：明确使用原有会话轮询／heartbeat，不静默切换 |
| `--output-plan` | browser模式必填，JSON数组，结构见下方；文件放在该任务既定执行附件内 |
| `--segment-plan` | 原生H3分段导出的browser任务必填；JSON对象绑定director_node、report_node、output_root，组序及本地目标从既有输入映射读取 |
| `--history-name` | 终态完整响应的单个文件名，默认执行结果.json；图片任务传入规定的任务前缀，不能与其他附件名重复 |
| `--task-title` | 全局进度栏显示的任务名称；Agent按[任务显示标题规则](../流程规范/ComfyUI-服务配置与任务提交规范.md#任务显示标题)显式填写。工具未填写时默认采用record-dir目录名 |
| `--thread-id` | 已获准通知的目标会话ID，默认真实CODEX_THREAD_ID；指定其他会话须有用户授权，不覆盖模型／思考等级 |

### 浏览服务监控接入

完整工作区先按[服务README](../../../../../工作区浏览服务/README.md#日常启动)启动浏览服务，再在Codex执行环境中调用统一入口。后台依赖浏览服务已有的Python虚拟环境、websockets；桌面通知使用Node及本机已安装的codex-app-tools适配器。启动服务不要求继承Codex环境：提交入口将本次真实连接上下文交给后台，仅保存在被忽略的runtime目录，不写入项目证据或网页。专用提交接口只接受本机Agent凭证，不向浏览页面提供操作入口。复制技能到其他环境时，不携带runtime、本机连接、数据库或项目资料；显式选择legacy模式。

调用前从实际API及预期结果确定取回身份，创建`--output-plan`指定的JSON文件：

```json
[
  {
    "node_id": "实际保存节点ID",
    "output_key": "images",
    "index": 0,
    "path": "C:/实际工作区/projects/实际项目/规定的候选目录/实际文件.png",
    "response_name": "本任务-取回响应.json"
  }
]
```

node_id、output_key及从0开始的index明确选择该任务history输出；path为项目内尚不存在的绝对文件路径，按专项规则命名，不能写入执行附件；response_name为该任务执行附件内单个下载证据文件名，必须与请求及其他附件名不同。后台不自行挑选输出、不改名、不覆盖已有文件、不写审批记录。其他无法确定标准history输出的任务可显式为`[]`，后台终态后通知原会话核对取回；不以空映射冒充已取回。原生H3分段导出使用`[]`并同时登记下方segment-plan；后台拒绝缺少分段计划的原生分段任务，不静默转用旧监控。

原生H3分段导出的`--segment-plan`文件放在本轮既定执行附件，内容如下；节点ID及output根目录必须依据实际任务和远端配置核实，不照抄示例：

```json
{
  "director_node": "502",
  "report_node": "403",
  "output_root": "E:/实际ComfyUI目录/output"
}
```

report_node必须实际连接该导演台report输出（槽位5）。后台复用已有`输入映射.json`中的selected_indices及segments，保留原始零起始组序，读取segment、round、local_execution_dir；不压缩未选组。首次取回落各P执行附件，沿用真实远端文件名，下载凭据为`取回响应-001.json`起递增；完整文件发布到现有候选目录及固定EP/C/P/R/阶段文件名。下载SHA256沿用通信客户端的已有凭据。后续核对副本采用`收尾取回-002.mp4`等未占用名称，相同内容不重复发布，改写文件留在执行附件等待原会话按目录规范处理批准与替换。只保存本轮必要保存日志条目，不保存整份远端日志。

```powershell
python /实际技能目录/scripts/comfyui_dispatch.py --project /实际项目目录 --task-type video-first-pass --workflow /实际附件目录/工作流.api.json --eligible-url http://实际服务器:8188 --record-dir /实际附件目录 --output-plan /实际附件目录/空输出映射.json --segment-plan /实际附件目录/分段取回映射.json
```

空输出映射文件内容为`[]`。segment-plan只用于browser模式；后台支持原生segments导出，一采读取`_pre.mp4`，二采读取本轮正式MP4，不收取缓存、预览、一采对照或精修中间轮次。运行中只认绑定本轮目录的真实保存事件；无法绑定时留在同一后台等待最终报告。首次接入先核对远端`/internal/logs/raw`提供entries数组及t／m字段；接口不可用在POST前失败，不产生已提交任务。WS进度、补查频率、通知及断线处理统一执行[监控规范](../流程规范/ComfyUI-任务监控规范.md#1-监控方式与间隔)。

后台先连接WebSocket，再用同一个client_id提交。成功标准仍是dispatch_state=accepted及真实prompt_id；额外返回monitor=browser、monitor_id。服务不可达、参数错误或缺少Codex上下文时命令失败；已发生POST但结果不明时核对原提交证据及全局状态，不自动重试、换目录或降级重提。成功返回后后台负责监听；不要再为同一任务安排轮询或heartbeat。关闭网页不会停后台，重启后按原ID核对，通知状态及异常处理遵循[任务监控规范](../流程规范/ComfyUI-任务监控规范.md#1-监控方式与间隔)。

后台使用同一通信模块的submit/status/download，保留原有防重、终态分类、下载防覆盖及传输完整性检查。终态证据默认保存为record-dir内`执行结果.json`，图片任务通过`--history-name`传入规定前缀，各项取回响应采用登记名称。网页只展示运行状态，项目正式业务记录由收到通知的原会话维护。存在待通知但桌面连接已失效时，用户回到原会话读取证据接续；不凭通知状态判断素材已审核。

| `task-type` | 执行阶段 |
| --- | --- |
| `image` | 原生图片生成或图像编辑 |
| `image-upscale` | 图片超分 |
| `video-first-pass` | 视频一采 |
| `video-second-pass` | 视频二采 |
| `video-postprocess` | 视频超分插帧后处理 |

视频阶段按真实业务轮次填写；配套H3生成图误填为image或video-postprocess时，脚本在联网前拒绝。工作流两轮共用Refine节点，不凭节点存在自动判断一采／二采；提交前阶段核对按[项目选端规则](../流程规范/ComfyUI-服务配置与任务提交规范.md#新任务的选端与提交)执行。确有用户指定时增加 `--target-url 'http://用户指定且已配置的远端:端口'`，续轮沿用既有来源地址与指定依据。旧配置的默认端例外补齐范围按[项目服务配置](../流程规范/ComfyUI-服务配置与任务提交规范.md#项目-comfyui-配置)执行，不自动改写项目文件。

### 视频资料自动保存

一采、二采、后处理继续使用同一个提交命令，不增加手动关联命令。业务规则真源为[生成版本的资料关联](../流程规范/逐集目录与资产管理规范.md#生成版本的资料关联)，保存代码为[内部资料保存模块](../../scripts/generation_context.py)；网页自动读取其输出的同一 `generation_contexts` 字段。

调用前在 `--record-dir` 指定的共同证据目录准备 `输入映射.json`。以下是输入接口示例，路径与编号必须换成实际任务值；`segments` 保留导演台完整原组序，`selected_indices` 仅列本轮实际选择的零起始组序号，不压缩未选组：

```json
{
  "scene": "EP001-C001",
  "scene_storyboard_version": "v21",
  "selected_indices": [0],
  "segments": [
    {"segment": "EP001-C001-P001", "round": "R004", "local_execution_dir": "09-剧集制作/EP001/其他资料/执行附件/EP001-C001-P001-R004-一采"}
  ],
  "uploads": [
    {"file": "03-人物资料/CH001/参考图/CH001.png", "input_path": "本轮实际上传目录/CH001.png"}
  ]
}
```

映射中的本地路径以项目根目录解析，也可使用项目内绝对路径；不得越出项目。`uploads` 指已完成并核实的真实上传映射，`input_path` 分别与API的 `imageFile`、`videoFile`、`audioFile` 对应，复用旧上传也须记录本轮真实本地输入版本。它与下方 `--uploads` 的节点输入上传接口不同，不能相互替代。正式一采／二采沿用原生r2v导演台，公共开关 `global.commonEnabled` 显式填写；API实际选择状态、公共／本组正文及三类素材槽位决定保存内容。按 `refs`、`refVideos`、`refAudios` 依次保存图片、视频、音频，各类型按index排序且编号独立；本组同类型同槽位覆盖的公共素材不记作本段实际输入，公共开关关闭时不保存公共素材或正文。既有单视频 `referenceVideo` 兼容为视频index 0，存在原生同槽位时采用原生项，与[节点实际输入规则](../生成规范/ComfyUI-MiniMaxH3导演台节点使用规范.md)一致。

二采在每个实际执行组中另填 `source`，指向同P获批来源的完整执行身份；二采保存自己的当次输入并保留来源。后处理只需场次、实际组序及含 `segment`、`round`、`source` 的分段项，来源为本次实际使用的完整执行身份，不另生成空提示词或参考素材。

可选的 `storyboard_file` 指定项目内已冻结分镜，仍核对 `scene_storyboard_version`；不填写时读取正式分镜。同R故障补做按[修订与过程规则](../流程规范/逐集目录与资产管理规范.md#视频修订编号与执行过程)使用阶段目录内 `执行-YYYYMMDD-HHmmss/`，`--record-dir` 及各选中组的 `local_execution_dir` 对应该次位置；提交命令、文件名和防重检查不变，建立新位置不能代替旧任务的活动／接受核对。

每个 `segments` 项可选填写 `materials_from: {"mapping": "项目内原输入映射.json", "identity": "EP001-C001-P001-R000-一采"}`，引用同分段原关联的分镜、提示词与实际参考素材。工具按当前实际输入逐项核对正文、文件字节与槽位后引用旧冻结文件，差异时报错，不冒充沿用；新工作流/API仍单独保存。若素材有修改，不填写整套复用字段，按新输入冻结。复用不继承视频批准，也不递归推断最新资料。

统一入口选端成功后、POST前核对并保存：正式场次分镜版本须与映射一致，全文冻结为共同目录 `分镜脚本.md`；各P的实际公共＋本组英文保存为其执行目录 `模型提示词.txt`；实际图片、视频和音频参考素材冻结于共同目录 `输入素材/`；已有当次 `中文提示词参考版.txt` 关联读取，没有时如实缺项，不现场补译。最后自动补齐共同映射的 `generation_contexts`、记录时间与依据，保留原字段值。缺文件、映射不符或试图覆盖不同冻结资料时退出1且不发送生成POST；同一准备输入重复检查不改写快照。忙时 `deferred` 不保存本轮快照。保存资料不代表服务器已经接受任务，仍以提交结果的真实prompt_id为准。

图片任务不执行视频资料保存。原任务的防重复提交检查继续生效；已有历史缺项按业务规则核实证据后补记，不通过重新提交或从现行文档猜测恢复。

### 节点输入上传

有新本地素材时增加 `--uploads '/实际附件目录/本任务-上传映射.json'`。数组每项对应一次文件上传及一个既有节点输入，例如：

```json
[
  {
    "file": "/实际目录/已批准参考图.png",
    "node": "2",
    "input": "image",
    "subfolder": "本任务输入目录",
    "response-name": "本任务-上传响应-001.json"
  }
]
```

节点编号、输入名及上传来源按实际API填写。选端后使用真实上传返回的input_path连接；响应保存在record-dir内，成功响应的url必须与选中端一致才可复用。上传状态不明、响应为空或失败时停止并核对，不自动重复上传；原上传证据不覆盖。映射属于生成前准备或技术执行附件，不改变现有生成／审阅记录模板。此映射不是视频模型的Picture／Audio／Video标签表，业务标签仍须按既有规范核对。

标准输出为JSON。退出0时检查 `data.dispatch_state`：`accepted` 才表示取得真实prompt_id，`data.url`为实际服务；`deferred` 表示本轮未提交。checks保留候选地址、运行／等待数量、`video_jobs`数量及选端结论；忙的reason为 `video_generation` 或 `pending_threshold`，不保留其他任务提示词。将结论写入已有生成／执行记录；待提交不计入监控模板的已提交数量。接口异常或本地互斥锁被占用时退出1，读取error；锁占用意味着另一会话正在提交，稍后重新调用，不是生成失败。

队列识别读取ComfyUI队列条目的API节点类型，当前覆盖一采确认与二采工作流的 `MiniMaxH3Director`，并兼容识别旧版独立二采的 `MiniMaxH3ReferenceToVideo`；识别旧任务不表示将其作为默认入口，工作流用途读取[H3执行规范第0节](../生成规范/ComfyUI-H3视频执行规范.md#0-制作策略与工作流配置)。不依赖任务标题或本机台账；后续接入新的视频生成节点时，同步脚本识别和回归用例。队列条目缺少可读API图时，该端返回unknown结论。

一次调用最多提交一次POST；POST结果不明仍保留原提交证据，不分流重提。后续status、download沿用上方命令，从submit-attempt或项目对应“提交尝试”附件的url读取实际服务。脚本不提供绕过已有证据、强行重试或修改远端队列的参数。

调度回归测试使用模拟响应及临时目录，不连接服务器、不生成媒体：

```sh
python3 -B -m unittest discover -s '/实际技能目录/scripts' -p 'test_comfyui_dispatch.py' -v
```

退出0并报告OK表示通过。覆盖优先分配、等待门槛、运行及等待视频识别、一采／二采／视频后处理默认端限制、图片生成与超分分流、旧配置读取、用户指定、不具备能力的指定端、待提交后恢复提交、开关及例外、候选能力范围、本地互斥、选中端素材上传、地址绑定及提交不明时不向其他端重发；真实多机性能和节点兼容性仍需实际任务验证。通用通信函数的修改同时运行上方通信回归测试。
