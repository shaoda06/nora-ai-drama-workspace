# 通用 ComfyUI 执行工具

入口：[comfyui_client.py](comfyui_client.py)。Python 3.9+，仅标准库；安装位置属于短剧技能，代码不包含短剧业务。与 `comfyui-api` 技能结合使用：技能提供连接、接口与安全规则，脚本执行上传、提交、单轮查询、下载和原生导演包导出。节点／模型检查仍按 `comfyui-inventory`；故障按 `comfyui-troubleshooter`。

## 使用边界

- agent 按当前业务规范准备最终 **API 格式节点 JSON**、参考素材映射和全部参数；脚本不修改提示词、种子、节点或连线，不转换画布 JSON，不内置工作流模板。
- 上述已有能力必须复用此脚本，不按任务新写 Python／shell／内联 HTTP 实现。准备 API JSON 和人工审核仍由 agent 完成；视频批准后的文件移动和业务记录更新复用下方独立的采用工具。发现脚本缺陷先报告并集中修复，缺少接口则明确缺口后处理，不悄悄回退成一套临时执行器。
- 只处理当前获得授权的任务；不启动下一阶段、不自动重试提交、不管理定时器、不操作队列删除／中断／卸载／服务器配置。
- 通信客户端本身不决定项目路径、命名、审批或归档，不生成或维护项目工作稿，不移动候选至选定；视频批准后的业务收尾由下方独立采用工具承担。图片由agent核对文件与执行记录后交用户审核，默认不调用看图能力或自动重试；批准后超分沿用对应专项规则。视频直接交人工审核。
- 五个命令相互独立。已有远端素材可以复用；新本地素材由后台上传并把实际返回路径写入声明的API输入。接口验证／节点发现等不在这些命令内的只读操作仍可按对应技能执行。

## 视频批准后的采用收尾

入口：[video_adopt.py](../../scripts/video_adopt.py)。这是独立于通信客户端的短剧业务工具，Python 3.11+、仅标准库；复用客户端的严格JSON读取、JSON编码和本机带时区时间，不依赖 `tzdata`。用户批准具体视频后，用它移动文件、更新采用和审核记录；适用于已取回或本地修改完成的一采、二采、后处理视频。采用、替代和整集完成标准唯一从[逐集目录规范](../流程规范/逐集目录与资产管理规范.md#视频采用记录与批准依据)读取。

agent根据用户实际批准范围准备数据文件，不编写修改脚本。将计划命名为 `采用请求.json`，保存在对应真实执行附件；同一共同任务可以列多个获批分段，不要求它们全部获批。以下JSON示例的身份、实际执行映射、取回响应以及 `old` 原文须按项目现状替换：

```json
{
  "approval_text": "第7段通过了。",
  "approval_time": "2026-10-10T13:40:05+08:00",
  "items": [
    {
      "identity": "EP002-C001-P007-R005-二采",
      "mapping": "09-剧集制作/EP002/其他资料/执行附件/EP002-C001-P007-R005-二采/输入映射.json",
      "receipt": "09-剧集制作/EP002/其他资料/执行附件/EP002-C001-P007-R005-二采/取回响应-001.json",
      "execution_heading": "R005-二采"
    }
  ],
  "record_updates": [
    {
      "path": "09-剧集制作/EP002/其他资料/工作稿/EP002-生成说明-工作稿.md",
      "old": "- 当前状态：P007二采待审核；其他段见各工作稿。",
      "new": "- 当前状态：P007 R005二采已批准采用；其他段见各工作稿。"
    },
    {
      "path": "项目进度.md",
      "old": "| EP002 | 制作中；P007二采待审核 |",
      "new": "| EP002 | 制作中；P007 R005二采已采用 |"
    }
  ]
}
```

在工作区根目录运行（独立技能安装替换工具路径）：

```powershell
python .agents/skills/nora-ai-short-drama/scripts/video_adopt.py --project 'projects/荒院暴富' --plan '09-剧集制作/EP002/其他资料/执行附件/EP002-C001-P007-R005-二采/采用请求.json'
python .agents/skills/nora-ai-short-drama/scripts/video_adopt.py --project 'projects/荒院暴富' --plan '09-剧集制作/EP002/其他资料/执行附件/EP002-C001-P007-R005-二采/采用请求.json' --apply
```

参数与计划字段：

| 字段 | 含义及默认行为 |
| --- | --- |
| `--project` | 必填项目根；从当前工作目录解析。所有计划中的资料路径相对该项目根解析，也可传项目内绝对路径；资料越界路径拒绝。 |
| `--plan` | 必填采用计划JSON；相对路径按项目根解析，也可用绝对路径。正式计划存实际执行附件；只读检查可传项目外临时计划，计划中资料仍须位于项目内。默认只读预览，不写任何项目文件；`--apply` 才执行。 |
| `approval_text` | 必填用户批准原话。没有明确批准不能填；工具不推断批准范围。 |
| `approval_time` | 可选实际决定时间，带时区；省略时明确“实际决定时间未记录”，另记本次登记时间，不冒充历史决定时间。 |
| `items[].identity` | 必填完整 EP/C/P/R/阶段，阶段仅一采、二采、后处理；重复对象拒绝。不接受整集、全部、最新等模糊对象。 |
| `items[].mapping` | 必填实际执行输入映射，关联对应 `generation_contexts[].identity` 及本段输出。ComfyUI执行需真实prompt ID；本地修改使用下述实际修改记录，不借用来源任务ID。支持 `outputs`、`runtime_retrieved`，或单段 `output`；不修改请求、生成上下文或技术状态。 |
| `items[].receipt` | 必填实际输出凭据。远端取回复用固定下载响应的 `data.bytes/sha256/remote`；本地修改用下述输出记录。共同目录外的凭据必须已在映射中明确关联；不新增批准哈希。 |
| `items[].approval_scope` | 可选实际批准范围，默认所列具体文件；用户限定画面、音频或接受已知缺陷时必须传入原意，不扩大批准。 |
| `items[].review_entry` | 可选实际网页审核入口，写可读链接；缺省如实标为未记录，不编造已展示事实。 |
| `items[].source` | 可选，默认本集 `其他资料/候选视频/{identity}.mp4`。其他实际格式或旧位置须传实际路径，文件名须为本身份加实际扩展名；保留原格式和文件名，不转码。目标按阶段采用目录确定。 |
| `items[].execution_heading` | 可选，默认 `R编号-阶段`。旧章节如 `R004后处理故障接续-001` 应明确传完整标题；标题须唯一，章节字段须标明本次阶段。 |
| `items[].related_mappings` | 可选父映射路径数组。仅同步 `current_execution.mapping/prompt_id` 明确指向本次执行的父记录；原prompt、旧终态、历史输出凭据保留。 |
| `record_updates` | agent按当前事实准备的定点替换数组，字段为 `path/old/new`，只允许涉及集的生成说明工作稿和项目进度。正式采用要求两类入口均有更新；事实无变化可 `old=new`。原文匹配须唯一；已是唯一新文时不重复更新；他人改动导致失配就停止。可列多处，包含移动后需要更新的链接。 |

本地直接修改视频时，实际输入映射的 `local_edit` 记录 `tool/source/source_file/parameters`（工具、完整来源身份、项目内来源文件及实际参数），与 `generation_contexts` 的来源保持一致；本段输出记录 `path/bytes`，已有 `sha256` 时复用，没有不补造。`receipt` 可指实际输出响应，也可指含单段 `output` 的本地映射本身；不填ComfyUI prompt ID。仅采用已生成的文件，不执行视频修改。目录迁移后，实际文件、原输出凭据及现有批准关联一致时，可同步映射中的当前位置，保留原批准时间，不新增审核决定。

工具按现有格式自动更新：阶段选定行、具体审核章节及决定、该阶段执行条目的审阅引用、输出入口和取回核对状态、移动／替代记录、输入映射的 `adoptions`。审阅正文直接读取[现有模板](../模板/视频人工审阅区模板.md)，不另维护一份结构。每个分段的其他阶段保留；不更换R、不把生成成功当审核通过。返回JSON包含逐项 `adopt/already_adopted`、移动清单、受影响工作稿／映射、各阶段已采用数量；预览的 `required_record_updates` 列出缺少的收尾入口。标准输出供当轮留证，不为保存结果再运行一次。退出0表示预览或执行成功，退出1表示检查或I/O错误。

执行前完成本批所有检查。已采用同一文件且记录齐备时调用不会重复移动或新增审阅；目标文件与取回字节不同、候选／采用两处同时存在同名文件、记录失配或替代影响已选定下游时停止。磁盘写入使用同目录临时文件替换单个记录；跨文件操作不构成数据库事务。移动或写入期间I/O错误可能已有部分动作，按实际文件位置核对后收尾：例如视频已移入采用目录但文字未写完，同计划可完成登记；旧版本退回候选发生冲突时需先定点处理。不能因此重生成或覆盖冲突文件。

本工具始终离线，不调用ComfyUI、不处理媒体内容、不自动采用整集、不更新定时器。返回 `browser_sync=not_checked`，网页读取核对仍按[项目浏览入口规范](../流程规范/项目浏览入口规范.md)执行，不能把本地成功写成网页同步成功。项目进度中的“已完成”须由agent按正式分镜范围和批准事实确定；工具的工作稿计数只是核对辅助。

回归测试（临时目录，真实项目不写入）：

```powershell
python -m unittest discover -s .agents/skills/nora-ai-short-drama/scripts -p test_video_adopt.py -v
```

覆盖三阶段、部分批准、替换历史、输入／字节／记录冲突、重复调用及写入中断收尾。在完整工作区内还用现有网页解析器验证各阶段批准识别；独立技能安装不包含浏览服务时跳过该集成项。

## 场次阶段批准后的定稿留档

入口：[scene_finalize.py](../../scripts/scene_finalize.py)。Python 3.11+、仅标准库；复用采用工具的审核判定、现有画布/API配对工具和下方原生 `export-pack`，不另写HTTP或ZIP生成器。执行时机、保存位置及配置冲突处理以[导演包规范第5.1节](../生成规范/ComfyUI-MiniMaxH3导演包制作规范.md#51-场次各阶段定稿留档)为唯一业务规则。先落实用户对具体视频的批准和采用，再调用本工具；它不创设审批，不监听用户消息，也不生成视频。

Agent只准备 `阶段留档请求.json` 数据，放在该场该阶段最前P的实际共同执行附件中，不写临时汇总、导出或补记录脚本。`items` 填写当前整场全部采用身份及其实际执行文件，可跨批次；脚本按正式分镜索引排序。以下为两段场次的一采示例，真实场次按索引填写所有段，不能把局部批准填成整场：

```json
{
  "episode": "EP002",
  "scene": "C001",
  "stage": "一采",
  "items": [
    {
      "identity": "EP002-C001-P001-R001-一采",
      "mapping": "09-剧集制作/EP002/其他资料/执行附件/EP002-C001-P001-R001-一采/输入映射.json",
      "api": "09-剧集制作/EP002/其他资料/执行附件/EP002-C001-P001-R001-一采/实际.api.json",
      "canvas": "09-剧集制作/EP002/其他资料/执行附件/EP002-C001-P001-R001-一采/实际.workflow.json",
      "receipt": "09-剧集制作/EP002/其他资料/执行附件/EP002-C001-P001-R001-一采/取回响应-001.json"
    },
    {
      "identity": "EP002-C001-P002-R001-一采",
      "mapping": "09-剧集制作/EP002/其他资料/执行附件/EP002-C001-P001-R001-一采/输入映射.json",
      "api": "09-剧集制作/EP002/其他资料/执行附件/EP002-C001-P001-R001-一采/实际.api.json",
      "canvas": "09-剧集制作/EP002/其他资料/执行附件/EP002-C001-P001-R001-一采/实际.workflow.json",
      "receipt": "09-剧集制作/EP002/其他资料/执行附件/EP002-C001-P001-R001-一采/取回响应-002.json"
    }
  ]
}
```

在工作区根目录运行：

```powershell
python .agents/skills/nora-ai-short-drama/scripts/scene_finalize.py --project 'projects/荒院暴富' --plan '09-剧集制作/EP002/其他资料/执行附件/EP002-C001-P001-R001-一采/阶段留档请求.json'
python .agents/skills/nora-ai-short-drama/scripts/scene_finalize.py --project 'projects/荒院暴富' --plan '09-剧集制作/EP002/其他资料/执行附件/EP002-C001-P001-R001-一采/阶段留档请求.json' --apply
```

参数及输入格式：

| 字段 | 含义 |
| --- | --- |
| `--project` | 必填项目根，相对当前工作目录；数据中的路径均相对项目根，也可填项目内绝对路径。拒绝越界。 |
| `--plan` | 必填留档请求；相对项目根，也可用绝对路径。默认只读预览，预览不联网、不写项目；正式请求放既有共同执行附件。 |
| `--apply` | 执行原生导出及留档收尾。授权只涵盖导出，不调用 `/prompt`、上传、队列操作、缓存操作或媒体后处理。 |
| `--timeout` | 每次HTTP请求超时秒数，默认30；没有自动重试。服务地址从各实际内容来源映射的 `url` 读取，必须一致，不另选服务。 |
| `episode/scene/stage` | 必填完整EP、C编号和阶段名，阶段为一采、二采、后处理。 |
| `items[].identity` | 必填完整EP/C/P/R/阶段。与正式索引及当前选定表逐一对应；脚本读取所链接的具体人工批准决定，未获批、重复或缺段即停止。 |
| `items[].mapping/api/canvas/receipt` | 必填实际执行映射、实际API、配对画布、该段取回凭据；映射旁的 `请求.json` 和 `提交响应.json` 必须对应真实任务。取回凭据须在实际共同执行附件内，远端文件身份和采用文件字节均须一致。不使用历史汇总API冒充实际提交。 |
| `items[].content` | 后处理必填正文来源对象，包含 `identity/mapping/api/canvas` 四字段；指向后处理映射 `generation_contexts[].source` 所指定的同段实际二采。一采和二采不填写。 |
| `items[].source_video` | 后处理必填项目内原二采文件路径；按后处理记录的 `source_bytes/source_sha256` 及实际LoadVideo上传映射核对。保留原文件，不用当前另一版本替换实际输入。 |
| `edition` | 可选三位留档序号，如 `002`，在文件名加 `-002`。来源发生变化或明确授权重新导出时另存，保留原附件；不增加生成R编号。 |

准备和核对全部成功后，整场汇总只保留实际获批各P；根时间线、r2v编辑工作区、组序和计划帧数同步。公共正文／引用不同而其他配置兼容时，把原公共正文和媒体移入各自组，保留绝对标签和本组覆盖公共同槽的对应关系。模型链、SIGMAS、Refine、种子、尺寸或其他必要控件冲突时，返回具体来源身份并停止，不自动统一。当前支持原生r2v分组；带源视频或关键帧时间轴的工程、旧公共referenceVideo差异、含子图的后处理分支不自动改造，需先解决说明中的具体缺项。

后处理配对画布并列保存各段实际超分／插帧分支，同时保留沿实际二采追溯的导演台汇总内容；API和画布节点、连线及参数配对核对。画布注明是整场汇总工程，不是某一次原执行，也不是恢复缓存的二采工程。处理输入视频继续使用各原任务的真实远端路径；导演包只携带时间线引用的媒体，不把模型、处理节点或所有视频输入写成包已携带。

目录和文件名按业务真源确定，不提供第二份输出路径。定稿ZIP与配对画布直接写入对应阶段 `C编号-场次/导演包/`；汇总API、`-导出响应.json`、`-留档记录.json` 保存在最前P的实际共同执行附件。留档记录保存逐P身份、实际API／画布、映射、任务ID、种子、采用文件及批准入口，不新建进度台账。原请求、源API、源画布、生成上下文和批准事实保持；在各实际输入映射登记 `scene_finalizations` 入口，在各P工作稿、本集生成说明工作稿、项目进度的 `定稿留档-EP编号-C编号-阶段` 段落补全配对文件和核对链接，不擅自把整集改为已完成。

原生包核对包括ZIP完整性、格式版本、包内控件、输出配置、完整时间线、公共／各组文件，以及路径改写后素材与冻结文件的实际字节；不解码审片。全部通过且记录写完才标 `completed`。JSON标准输出含 `ready/completed`、来源、目标和留档记录入口；`browser_sync=not_checked`，本地完成不冒充网页同步成功。退出0为预览或收尾成功，退出1为明确检查、网络或I/O错误。

重复执行同一请求会核对现有附件并补齐中断的记录，不重复导出或新增一套定稿文件。已有包来源不同、配对文件不同或包无本次准备记录时拒绝覆盖；网络／原生导出失败保存真实错误响应并停止，已有失败响应但没有包时不自动再导出。需要重新导出时先取得相应授权，用新 `edition`；坏包或字节不符保留问题且不登记完成。单文件记录使用临时文件替换，跨文件不构成事务；包已发布但响应尚未写入的中断，可凭已有准备记录、包内容和素材字节核对恢复本地凭据，标明原远端导出时间未记录。修复记录写入错误后同请求收尾即可，不重新生成。

测试使用隔离临时项目、正式基准画布和模拟原生导出，不访问真实远端：

```powershell
python -m unittest discover -s .agents/skills/nora-ai-short-drama/scripts -p test_scene_finalize.py -v
```

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

正式阶段定稿导出时，`--output`直接指向[场次各阶段定稿留档](../生成规范/ComfyUI-MiniMaxH3导演包制作规范.md#51-场次各阶段定稿留档)规定的对应阶段包路径；配对画布保存到同一定稿目录，`--result`指向既有执行附件内的导出响应路径。原生导出命令不生成配对画布，调用方须按同一汇总工程保存画布并完成配对核对；不先在执行附件留一份包再复制到定稿目录。

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

入口：[comfyui_dispatch.py](../../scripts/comfyui_dispatch.py)。Agent调用此入口登记后台本地队列，不向远端上传或提交，不等待生成。项目配置及调度、按钮语义读取[服务配置与任务提交规范](../流程规范/ComfyUI-服务配置与任务提交规范.md)。上方comfyui_client.py为后台复用的通信模块，普通Agent任务不直接调用upload／submit／download绕过队列。

```sh
python /实际技能目录/scripts/comfyui_dispatch.py \
  --project /实际项目目录 --task-type image \
  --workflow /实际执行附件/本任务-工作流.json \
  --record-dir /实际执行附件 --task-title 'CH001 · 首次生成' \
  --attempt-name 本任务-提交尝试.json --request-name 本任务-请求.json \
  --response-name 本任务-提交响应.json --history-name 本任务-执行结果.json \
  --output-plan /实际执行附件/成果取回映射.json
```

| 参数 | 含义 |
| --- | --- |
| --project、--workflow、--record-dir | 项目根目录、最终API副本、既定执行附件；必填，建议绝对路径 |
| --task-type | image、image-upscale、video-first-pass、video-second-pass、video-postprocess，按实际获授权阶段 |
| --task-title | 必填非空标题，格式由Agent遵守[标题规则](../流程规范/ComfyUI-服务配置与任务提交规范.md#任务显示标题)，后台不补目录名 |
| --eligible-url | 可选已核对主节点地址，提供时须与项目第一项一致 |
| --uploads | 可选本机素材与节点输入绑定JSON，后台准备时实际上传 |
| --output-plan | 必填JSON数组，普通输出明确节点、字段、序号和本机目标；导演台使用空数组及segment-plan |
| --segment-plan | 原生H3分段必填，含导演台、报告节点、核实output根目录及每个选中组的显式本机目标 |
| --attempt-name、--request-name、--response-name、--history-name | 各种证据的单个文件名，不能重复或占用后台任务状态.json、后台过程记录.json |
| --timeout | 单次网络操作超时，默认30秒，不是排队或生成时限 |
| --monitor | 仅支持browser，服务缺失时报告接入问题，不回退legacy |
| --start-paused | 可选，仅在已授权手动转移等需要先暂停的操作中使用；登记时直接为paused，恢复前不上传或提交；默认不传，自动排队 |
| --thread-id | 默认真实CODEX_THREAD_ID；通知其他会话须有用户授权 |

### 浏览服务监控接入

先启动[浏览服务](../../../../../工作区浏览服务/README.md#日常启动)，在真实Codex执行环境调用入口。Node、已安装桌面适配器、CODEX_THREAD_ID及CODEX_APP_TOOLS_PIPE_PATH用于来源会话通知，不伪造。连接上下文只存本机runtime，不暴露到项目证据或网页。专用接口接受本机Agent凭证，不接受浏览器Origin。SQLite、runtime及本机连接不随技能分享；缺少完整工作区后台时不能执行这条入队流程。

普通成果映射示例：

```json
[{"node_id":"实际保存节点ID","output_key":"images","index":0,
  "path":"C:/工作区/projects/项目/候选/CH001-本次版本.png",
  "response_name":"本任务-取回响应.json"}]
```

path是Agent指定的项目内绝对路径及文件名，不是远端路径，不放执行附件。节点、output_key和从0开始的index选择真实结果；后台完成后再从history取得远端filename／subfolder／type。普通任务不得空映射；导演台原生分段使用output-plan空数组并提供如下segment-plan。文件名与路径须换成真实项目值：

```json
{"director_node":"502","report_node":"403","output_root":"E:/实际ComfyUI/output",
 "targets":[{"index":0,
  "path":"C:/工作区/projects/项目/09-剧集制作/EP001/其他资料/候选视频/EP001-C001-P001-R000-一采.mp4",
  "response_name":"P001-最终取回.json"}]}
```

targets必须逐一对应输入映射selected_indices，保留原始组序，不压缩未选组。report_node必须连接director_node的report槽位5；output_root按远端实际配置核实。后台只从成功任务最终报告取回正式分段，不用运行日志或猜测目录，不覆盖已有文件。

入队成功返回dispatch_state=enqueued、local_task_id（UUID4）、monitor_id及status=local_queued（使用--start-paused时为paused）；此时还没有远端prompt_id。对同一执行附件、相同入队资料重复登记返回原ID；资料不同拒绝，不能改目录绕过原任务。后台真正提交后保存远端ID和实际请求。完成、失败、重启与通知规则读取[任务监控规范](../流程规范/ComfyUI-任务监控规范.md)。

Agent结果处理接口（均使用本机内部凭证）：

```sh
python /实际技能目录/scripts/browser_tasks.py status --task-id 本地UUID
python /实际技能目录/scripts/browser_tasks.py retry-collection --task-id 本地UUID
python /实际技能目录/scripts/browser_tasks.py ack --notification-id 通知批次UUID
```

retry-collection只允许取回失败任务，复用原终态结果和成功下载凭据，不上传素材、不重新生成。收到通知先ack，再读后台任务状态.json、后台过程记录.json及实际附件；ack要求当前真实来源会话。

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

映射中的本地路径以项目根目录解析，也可使用项目内绝对路径；不得越出项目。`uploads` 记录已有远端素材的本机来源映射；本轮新上传素材由后台依据下方上传绑定及实际响应补充到资料保存模块，`input_path` 分别与API的 `imageFile`、`videoFile`、`audioFile` 对应，复用旧上传也须记录本轮真实本地输入版本。它与下方 `--uploads` 的节点输入上传接口不同，不能相互替代。正式一采／二采沿用原生r2v导演台，公共开关 `global.commonEnabled` 显式填写；API实际选择状态、公共／本组正文及三类素材槽位决定保存内容。按 `refs`、`refVideos`、`refAudios` 依次保存图片、视频、音频，各类型按index排序且编号独立；本组同类型同槽位覆盖的公共素材不记作本段实际输入，公共开关关闭时不保存公共素材或正文。既有单视频 `referenceVideo` 兼容为视频index 0，存在原生同槽位时采用原生项，与[节点实际输入规则](../生成规范/ComfyUI-MiniMaxH3导演台节点使用规范.md)一致。

二采在每个实际执行组中另填 `source`，指向同P获批来源的完整执行身份；二采保存自己的当次输入并保留来源。后处理只需场次、实际组序及含 `segment`、`round`、`source` 的分段项，来源为本次实际使用的完整执行身份，不另生成空提示词或参考素材。

可选的 `storyboard_file` 指定项目内已冻结分镜，仍核对 `scene_storyboard_version`；不填写时读取正式分镜。同R故障补做按[修订与过程规则](../流程规范/逐集目录与资产管理规范.md#视频修订编号与执行过程)使用阶段目录内 `执行-YYYYMMDD-HHmmss/`，`--record-dir` 及各选中组的 `local_execution_dir` 对应该次位置；提交命令、文件名和防重检查不变，建立新位置不能代替旧任务的活动／接受核对。

每个 `segments` 项可选填写 `materials_from: {"mapping": "项目内原输入映射.json", "identity": "EP001-C001-P001-R000-一采"}`，引用同分段原关联的分镜、提示词与实际参考素材。工具按当前实际输入逐项核对正文、文件字节与槽位后引用旧冻结文件，差异时报错，不冒充沿用；新工作流/API仍单独保存。若素材有修改，不填写整套复用字段，按新输入冻结。复用不继承视频批准，也不递归推断最新资料。

后台轮到任务、完成素材上传后，在POST前核对并保存：正式场次分镜版本须与映射一致，全文冻结为共同目录 `分镜脚本.md`；各P的实际公共＋本组英文保存为其执行目录 `模型提示词.txt`；实际图片、视频和音频参考素材冻结于共同目录 `输入素材/`；已有当次 `中文提示词参考版.txt` 关联读取，没有时如实缺项，不现场补译。最后自动补齐共同映射的 `generation_contexts`、记录时间与依据，保留原字段值。缺文件、映射不符或试图覆盖不同冻结资料时暂停任务并保存原因，不发送生成POST；同一准备输入重复检查不改写快照。保存资料不代表服务器已经接受任务，仍以提交结果的真实prompt_id为准。

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

节点编号、输入名及上传来源按实际API填写。后台向任务当前归属节点上传后使用真实返回的input_path连接；响应保存在record-dir内，成功响应的url必须与该任务实际节点一致才可复用。节点归属及手动转移读取[服务配置与任务提交规范](../流程规范/ComfyUI-服务配置与任务提交规范.md#本地队列与按钮)。上传状态不明、响应为空或失败时停止并核对，不自动重复上传；原上传证据不覆盖。映射属于生成前准备或技术执行附件，不改变现有生成／审阅记录模板。此映射不是视频模型的Picture／Audio／Video标签表，业务标签仍须按既有规范核对。

标准输出为JSON。退出0且data.dispatch_state为enqueued表示本地入队成功，保存local_task_id；不代表远端已经接受或任务完成。接口或配置错误退出1，先查询后台记录，不自动重试远端POST。

工作流仍按本次声明的任务类型校验；原生H3任务继续核对阶段、输入映射及分段计划，不读取远端其他任务的工作流判断是否可提交。

后续查询、取回重试及通知确认使用上方browser_tasks.py接口；后台负责原远端地址、提交证据和防重复。

调度回归测试使用模拟响应及临时目录，不连接服务器、不生成媒体：

```sh
python3 -B -m unittest discover -s '/实际技能目录/scripts' -p 'test_comfyui_dispatch.py' -v
```

退出0并报告OK表示通过。Agent入口测试覆盖纯入队、主节点配置、素材绑定、本地ID和不访问远端；后台队列、通知及取回测试在工作区浏览服务/tests维护。真实模型兼容性仍需实际任务验证。

导演台素材藏在timeline_data JSON内时，上传映射可加json-path数组；每个组件为字段名或数组下标，绑定必须已经存在。例如：

```json
[{"file":"C:/项目/素材/参考.png","node":"502","input":"timeline_data",
  "subfolder":"本次任务","response-name":"上传-001.json",
  "json-path":["global","refs",0,"imageFile"]}]
```

后台使用实际返回的input_path替换这一字段，保持原工作流副本和大整数种子。新上传素材的本机来源同时交给资料冻结模块；已有远端素材仍按输入映射uploads核对来源。
