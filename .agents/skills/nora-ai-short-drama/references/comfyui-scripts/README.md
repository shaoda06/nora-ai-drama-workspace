# 通用 ComfyUI 执行工具

入口：[comfyui_client.py](comfyui_client.py)。Python 3.9+，仅标准库；安装位置属于短剧技能，代码不包含短剧业务。与 `comfyui-api` 技能结合使用：技能提供连接、接口与安全规则，脚本执行上传、提交、单轮查询、下载和原生导演包导出。节点／模型检查仍按 `comfyui-inventory`；故障按 `comfyui-troubleshooter`。

## 使用边界

Nora项目的调用入口和授权边界统一见[固定通信工具与证据](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#固定通信工具与证据)；按该规范使用下方队列入口或工作区认证适配入口。本文原生客户端命令用于独立通信和底层接口说明。

- agent 按当前业务规范准备最终 **API 格式节点 JSON**、参考素材映射和全部参数；脚本不修改提示词、种子、节点或连线，不转换画布 JSON，不内置工作流模板。
- 上述已有能力必须复用此脚本，不按任务新写 Python／shell／内联 HTTP 实现。准备 API JSON 和人工审核仍由 agent 完成；视频批准后的文件移动和业务记录更新复用下方独立的采用工具。发现脚本缺陷先报告并集中修复，缺少接口则明确缺口后处理，不悄悄回退成一套临时执行器。
- 只处理当前获得授权的任务；不启动下一阶段、不自动重试提交、不管理定时器、不操作队列删除／中断／卸载／服务器配置。
- 通信客户端本身不决定项目路径、命名、审批或归档，不生成或维护项目工作稿，不移动候选至选定；视频批准后的业务收尾由下方独立采用工具承担。图片由agent核对文件与执行记录后交用户审核，默认不调用看图能力或自动重试；批准后超分沿用对应专项规则。视频直接交人工审核。
- 五个命令相互独立。已有远端素材可以复用；新本地素材由后台上传并把实际返回路径写入声明的API输入。接口验证／节点发现等不在这些命令内的只读操作仍可按对应技能执行。

## Imagegen子代理交接与固定收尾

入口：[imagegen_results.py](../../scripts/imagegen_results.py)。生图能力选型及每批确认仍由[统一分流入口](../../SKILL.md#当前参考图生成选型)负责；固定代理、实际调用及父子交付边界见[Imagegen规范](../../../nora-generation/references/Imagegen生成与尺寸处理规范.md#子代理执行与父代理交付)。本脚本不生图、不超分、不远端入队、不发消息，也不自动批准；复用共享图片记录应用、审核模板和项目网页解析核验。需要完整工作区及浏览服务Python运行环境，独立技能包缺少该运行环境时说明限制，不伪装已同步网页。

使用当前工作区浏览服务的Python环境，macOS／Linux为`工作区浏览服务/.venv/bin/python`，Windows为`工作区浏览服务/.venv/Scripts/python.exe`。以下示例解释器和技能路径替换为当前安装的实际绝对路径。主控在该项目既有执行附件保存一份请求JSON，字段如下；图片类型、目录、名称和创作字段仍沿原专项，不由脚本决定设计。

```json
{
  "kind": "场景",
  "object": "SC001",
  "image_type": "场景参考图",
  "title": "办公室工位无人总览",
  "purpose": "总览／基础图",
  "draft": "04-场景资料/其他资料/工作稿/SC001-参考图-工作稿.md",
  "output": "04-场景资料/其他资料/工作稿/素材/SC001-EP001-C001-V001-场景参考图-候选-v01.png",
  "prompt": "本次准备好的完整实际提示词",
  "ratio": "16:9",
  "formal_size": [2752, 1536],
  "authorization": "本批Imagegen选择、生成范围及一次调用的真实授权",
  "fields": {"场景编号与名称": "SC001 办公室", "视图编号与名称": "V001 工位总览"},
  "references": []
}
```

`kind`为人物、场景、道具或剧集素材。`prompt`为最终正文，不是要求子代理继续编写的任务描述。`ratio`为请求比例，`formal_size`仅记录获批后正式目标，不限制原生结果像素。`output`必填且不得占用已有文件；不自动推断用户想覆盖哪个候选。`fields`可填原模板创作字段；`references`按既有清单的`file/purpose/approval`或`user_reference/basis`提供项目内真实输入，原批准及来源要求保持，不要求Imagegen提供种子。`record_dir`可选，默认沿原工作稿的既有执行附件及对象／生成序号；`record_updates`可选，原记录须同步的关联内容用`path/old/new`明确提供，支持`{{outputs}}`和`{{specs}}`，不让子代理手写更新。

```sh
/实际浏览服务/.venv/bin/python /实际技能/scripts/imagegen_results.py prepare \
  --project /实际项目目录 --request 相对执行附件/请求.json
```

`prepare`只准备既有生成条目、实际提示词文件与Imagegen执行清单，不调用工具或创建ComfyUI任务。新交接返回`manifest`、`executor`、`generation`、`candidate`、`prompt_file`、`generation_call_file`、`result_store_key`、`report`入口及`complete_command`参数数组。主控将执行清单、内置调用文件和此数组交给固定子代理；执行时只追加`["--source", 实际原生输出路径]`，用参数列表启动，不重新拼写项目、清单或提示词长路径。相同请求复用交接，不重复分配生成编号。已交接请求改变时另存新请求，不覆盖原调用依据。准备好后未执行的条目如实保留待执行，不记生成成功。

`generation_call_file`是项目相对路径，内容用于子代理原样提交到functions.exec，不在shell或Node中调用真实生图。固定正文已包含实际提示词和按用途清单顺序排列的绝对参考图路径；同次exec先`store(result_store_key, 完整返回值)`，再`generatedImage(完整返回值)`。内置Imagegen结果不按MCP的`content`数组解析，不打印base64或用字段名代替实际结果。需要恢复显示时只执行`generatedImage(load(result_store_key))`；原生文件定位和父子交付边界仍按Imagegen规范。历史清单没有这两个字段时保留原记录与complete恢复入口，不因此新增一次生图。

子代理取得原生PNG后，使用上述`complete_command`数组追加`--source`并执行。以下仅展示`complete`的参数含义，不作为手工重拼路径的步骤：

```sh
/实际浏览服务/.venv/bin/python /实际技能/scripts/imagegen_results.py complete \
  --project /实际项目目录 --manifest 相对执行附件/请求-Imagegen执行清单.json \
  --source /工具实际返回的原生输出.png
```

`--source`为实际工具原生文件的绝对路径，保持原文件并复制原字节，不裁切、缩放或转换。脚本从执行清单中的`prompt_file`读取本次逐字提交的正文，并与准备正文核对；不再要求执行者重复填写该路径。已有命令仍可显式传`--actual-prompt-file`，但它是兼容选项而非默认步骤；不把重新改写的文本登记为原请求。固定脚本保存真实来源凭据、实际尺寸／数量、原生候选与待确认审阅，核验该项目解析后确实含本候选，再返回`user_message_ready=true`和交付入口。普通生产项目使用其真实项目根目录；隔离测试项目只核验其独立项目解析结果，不表示生产网站新增该测试项目。

生图失败时使用`fail --project ... --manifest ... --error-file /实际错误.txt`，只记录错误，不追加生图。收尾失败时子代理回传错误；获授权修复后重新调用原`complete`只恢复未完成的登记／网页核验，不再次生成。候选已存在不同内容、提示词不符或记录并发改变时停止，不覆盖用户反馈。已完成结果重复调用复用原报告；不借收尾入口替代已有候选或新一轮生成。

父代理收到完成消息后读取子代理报告即可。报告入口也可用`report --project ... --manifest ...`读取；该命令不重新测图、登记或扫描网页。失败报告返回实际问题，未完成时不能以已有文件推断可交付。超分沿原批准后处理入口执行，不交给本脚本重画。

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
| `summary` | 可选单集既有业务汇总入口，限本集生成说明或分镜索引工作稿；缺省使用生成说明。多集采用计划保持各集默认入口。 |
| `record_updates` | agent按当前事实准备的定点替换数组，字段为 `path/old/new`，只允许涉及集的业务汇总工作稿（默认生成说明，单集可由 `summary` 指定既有分镜索引工作稿）和项目进度。正式采用要求两类入口均有更新；事实无变化可 `old=new`。原文匹配须唯一；已是唯一新文时不重复更新；他人改动导致失配就停止。可列多处，包含移动后需要更新的链接。 |

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

入口：[scene_finalize.py](../../scripts/scene_finalize.py)。Python 3.11+、仅标准库；复用采用工具的审核判定、现有画布导出工具和下方原生 `export-pack`，不另写HTTP或ZIP生成器。执行时机、保存位置及配置冲突处理以[导演包规范第5.1节](../../../nora-generation/references/ComfyUI-MiniMaxH3导演包制作规范.md#51-场次各阶段定稿留档)为唯一业务规则。先落实用户对具体视频的批准和采用，再调用本工具；它不创设审批，不监听用户消息，也不生成视频。

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
| `items[].mapping/api/canvas/receipt` | 必填实际执行映射、实际API、配对画布、该段取回凭据；映射旁的 `请求.json` 和 `提交响应.json` 必须对应真实任务。取回凭据在实际共同执行附件内，或已由输入映射明确关联到分段附件；远端文件身份和采用文件字节均须一致。不使用历史汇总API冒充实际提交。 |
| `items[].content` | 后处理必填正文来源对象，包含 `identity/mapping/api/canvas` 四字段；指向后处理映射 `generation_contexts[].source` 所指定的同段实际二采。一采和二采不填写。 |
| `items[].source_video` | 后处理必填项目内原二采文件路径；按后处理记录的 `source_bytes/source_sha256` 及实际LoadVideo上传映射核对。保留原文件，不用当前另一版本替换实际输入。 |
| `edition` | 可选三位留档序号，如 `002`，在文件名加 `-002`。来源发生变化或明确授权重新导出时另存，保留原附件；不增加生成R编号。 |
| `summary` | 可选已有的本集业务汇总工作稿路径，默认 `其他资料/工作稿/EP编号-生成说明-工作稿.md`；已有项目使用分镜索引工作稿汇总时明确指定它，不创建第二份记录。 |
| `configuration_batches` | 仅用于用户明确允许的按配置分批例外，数组中每项为 `{"name":"标准版","parts":["EP001-C001-P001"]}`。各批合计必须完整覆盖该场全部P段且各段仅归属一批；同批必要配置仍须一致。批次名只允许字母、数字、汉字、下划线和连字符，用于定稿文件名及记录章节。默认不分批。 |
| `configuration_batch_authorization` | 使用上述分批时必填本次用户明确允许的依据；脚本不能自行填写授权。先核对全部批次，再逐批导出，已有批次按原中断恢复机制核对复用，不自动重导。 |

准备和核对全部成功后，整场汇总只保留实际获批各P；根时间线、r2v编辑工作区、组序和计划帧数同步。公共正文／引用不同而其他配置兼容时，把原公共正文和媒体移入各自组，保留绝对标签和本组覆盖公共同槽的对应关系。模型链、SIGMAS、Refine、种子、尺寸或其他必要控件冲突时，返回具体来源身份并停止，不自动统一。当前支持原生r2v分组；带源视频或关键帧时间轴的工程、旧公共referenceVideo差异、含子图的后处理分支不自动改造，需先解决说明中的具体缺项。

组与P的对应关系读取实际输入映射的 `segments` 原组序及完整执行身份，并核对 `selected_indices` 和实际时间线执行范围；组ID独立保留，不要求等于P编号，也不通过去掉前缀猜测对应关系。后处理优先使用输入映射的 `uploads`；该字段缺失或为空时，读取同一执行附件 `后台过程记录.json` 中的成功上传记录，核对已有传输凭据的字节数、校验值及本地来源，再关联实际 `input_path`。不扫描猜测响应文件名，不仅凭请求中的路径认定上传成功；关联只用于本次留档核对，不改写原输入映射。缺少记录或来源不符时停止留档。

后处理配对画布并列保存各段实际超分／插帧分支，同时保留沿实际二采追溯的导演台汇总内容；执行参数以实际API为准，不进行画布与API比较。画布注明是整场汇总工程，不是某一次原执行，也不是恢复缓存的二采工程。处理输入视频继续使用各原任务的真实远端路径；导演包只携带时间线引用的媒体，不把模型、处理节点或所有视频输入写成包已携带。

汇总导出副本按实际API填写相关画布控件，不比较来源画布与API，也不覆盖来源文件。后处理准备稿若仅LoadVideo路径早于上传，依据同任务实际请求及上传映射恢复该路径；API与实际获批请求的身份和参数核对继续保留。

目录和文件名按业务真源确定，不提供第二份输出路径。定稿ZIP与配对画布直接写入对应阶段 `C编号-场次/导演包/`；汇总API、`-导出响应.json`、`-留档记录.json` 保存在最前P的实际共同执行附件。留档记录保存逐P身份、实际API／画布、映射、任务ID、种子、采用文件及批准入口，不新建进度台账。原请求、源API、源画布、生成上下文和批准事实保持；在各实际输入映射登记 `scene_finalizations` 入口，在各P工作稿、本集生成说明工作稿、项目进度的 `定稿留档-EP编号-C编号-阶段` 段落补全配对文件和核对链接，不擅自把整集改为已完成。

原生包核对包括ZIP完整性、格式版本、包内控件、输出配置、完整时间线、公共／各组文件，以及路径改写后素材与冻结文件的实际字节；不解码审片。全部通过且记录写完才标 `completed`。JSON标准输出含 `ready/completed`、来源、目标和留档记录入口；`browser_sync=not_checked`，本地完成不冒充网页同步成功。退出0为预览或收尾成功，退出1为明确检查、网络或I/O错误。

重复执行同一请求会核对现有附件并补齐中断的记录，不重复导出或新增一套定稿文件。已有包来源不同、配对文件不同或包无本次准备记录时拒绝覆盖；网络／原生导出失败保存真实错误响应并停止，已有失败响应但没有包时不自动再导出。需要重新导出时先取得相应授权，用新 `edition`；坏包或字节不符保留问题且不登记完成。单文件记录使用临时文件替换，跨文件不构成事务；包已发布但响应尚未写入的中断，可凭已有准备记录、包内容和素材字节核对恢复本地凭据，标明原远端导出时间未记录。修复记录写入错误后同请求收尾即可，不重新生成。

测试使用隔离临时项目、正式基准画布和模拟原生导出，不访问真实远端：

```powershell
python -m unittest discover -s .agents/skills/nora-ai-short-drama/scripts -p test_scene_finalize.py -v
```

## 独立通信调用

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

后台的工作流基础结构、提交证据名称合法性及名称冲突属于准备阶段固定检查，资料未变复用既有报告，入队和本工具发送时不再重复检查；独立文件调用在本工具入口检查一次。提交证据存在性与独占保护统一在本工具执行，上层不重复扫描三份提交证据。提交前先独占保存防重标记、完整请求，随后只发送一次 POST；返回 `data.prompt_id`、`data.client_id`、实际响应和记录目录。记录默认名称：

| 文件 | 内容 |
| --- | --- |
| `submit-attempt.json` | 服务地址、时间、client ID、请求哈希；保留即阻止重复提交 |
| `request.json` | 实际发送的完整请求 |
| `response.json` | 原始成功响应，或拒绝／不明状态及错误证据 |

agent 可通过 `--attempt-name`、`--request-name`、`--response-name` 指定当前业务规定的文件名（均为单个文件名，不能是路径）。例如视频使用 `提交尝试.json`、`请求.json`、`提交响应.json`；图片使用该任务规定的带编号附件名，**不要求新建额外管理目录**。这些名称只是调用参数，不是脚本内置业务规则。`--result` 不可与上述文件重名。

**同一逻辑提交必须沿用同一记录目录与文件名。** 发现任一证据已存在即拒绝提交，包括超时和先前被拒绝的请求；独占创建发生冲突也停止。两者返回`submission_guard`及`submission_state=not_sent`，表示本次未发送生成POST。后台记录拦截，待执行任务暂停，已有终态／未知状态和原始错误保留，不把拦截误记为新的远端拒绝或提交结果未知。不要换目录、换证据文件名或删除防重标记绕过检查；这是本地记录范围的保护，不是服务器全局幂等，也不能保证跨目录“恰好一次”。

请求超时、响应丢失、无有效prompt ID或服务器5xx时视为提交状态不明；用已保存client ID／请求核对队列及必要历史，不自动重发。正常 `status` 需要真实prompt ID；尚未找回ID时按 `comfyui-api` 做只读核对。只有确认原任务未接受且获得相应方向后才建立新的提交尝试。明确4xx拒绝也保留记录，修正后的新尝试不可覆盖旧证据。

### status：单轮查询

```sh
python3 comfyui_client.py status --url 'http://SERVER:8188' \
  --prompt-id 'REAL-PROMPT-ID'
```

先查指定history，非明确终态再核对queue。只返回本任务证据，不保存其他任务的提示词。状态为 `queued`、`running`、`success`、`failed`、`unknown`。`running`仅表示在运行队列，不证明采样步数正在推进；`success`须服务端明确completed与success且无错误／中断事件，**不等于业务要求的输出齐备或内容获批**。

`data.files`列出返回文件的node_id/output_key/index及原始文件信息；不替agent选择输出。agent核对本次预期节点及具体文件后再下载。原始任务history保留于返回JSON。网络故障是工具错误，不把任务标成失败。不自动等待、定时或启动下一阶段。

### 只读诊断与重启证据

CLI的status已查询history／queue，诊断不要为保存响应重复调用。其他只读核对复用本模块的`Client(url, timeout)`：`client.json(route)`读取JSON，`with client.open(route) as response`读取有界原始日志／响应头；不提供data时为GET，不写另一套HTTP通信。保存当轮返回和本地观察时间，重复错误沿用既有证据。具体次数、间隔及判定由[监控规范](../../../nora-generation/references/ComfyUI-任务监控规范.md#31-异常检查与连接恢复)维护，客户端自身不循环或判断是否补做。

`/system_stats`是连通性／设备快照，没有本工具保证的进程ID、启动时间或每次启动变化的实例标识；相同GPU、版本、URL不能证明同一实例或发生重启。`/internal/logs/raw`及`/vhs/getpath`属于执行端可选接口，仅在实际已确认可用时读取；目录列表限任务已绑定绝对目录，不扫描猜目录。原始日志读取限定大小（例如最多1 MiB），接口缺失如实报告，不安装节点、修改服务或臆造启动标识接口。没有直接进程证据时，按[视频恢复规则](../../../nora-generation/references/ComfyUI-任务监控规范.md#51-后端故障后的视频接续)核对组合证据，不能由客户端的请求成功代替业务判定。

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

源文件不改写；网页尚未保存的编辑内容不会包含在包里。调用方先按[导演包制作规范](../../../nora-generation/references/ComfyUI-MiniMaxH3导演包制作规范.md)核对时间线与素材，并选取这些远端素材实际所在的服务。

正式阶段定稿导出时，`--output`直接指向[场次各阶段定稿留档](../../../nora-generation/references/ComfyUI-MiniMaxH3导演包制作规范.md#51-场次各阶段定稿留档)规定的对应阶段包路径；配对画布保存到同一定稿目录，`--result`指向既有执行附件内的导出响应路径。原生导出命令不生成配对画布，调用方须按同一汇总工程保存画布；不先在执行附件留一份包再复制到定稿目录。

先向 `/minimax/director/export_pack` POST `dryRun=true` 核对缺失素材，再向同一接口POST实际导出。服务读取素材并创建临时ZIP，命令接收JSON/base64或二进制ZIP响应，在本机保存包与可选响应JSON；不调用 `/prompt`、不导入包、不运行生成或改动模型。远端临时导出文件的生命周期由原生接口管理，不操作采样缓存。

缺失素材会报 `missing_assets` 并停止；HTTP拒绝／超时按通用错误返回，不自动重试。传输长度、ZIP条目CRC及原生格式标识检查通过后，才以不可覆盖的原子方式发布文件。失败清理本次本地临时文件，已有包不覆盖。检查ZIP不解码媒体，也不代表网页导入已实测。

成功返回 `data.path/bytes/sha256/source_workflow/node_id/download_name/preflight/zip_entries`。响应不留存大段base64；`preflight.fileCount`是原生接口收集的媒体条目数，可能包含编辑草稿中的副本，不等于去重后素材数。模型、Refine及SIGMAS等完整画布设置不在包内，网页导入步骤和边界读取上述规则。

## 回归测试与验证边界

纯函数／文件安全回归测试（不启动本地服务、不访问远端）：

```sh
python3 -B -m unittest discover -s '/absolute/path/comfyui-scripts' -p 'test_*.py' -v
```

覆盖请求不改写、大整数种子、重复提交、POST超时不重试、状态分类、不泄漏其他任务、半下载清理及并发落盘防覆盖；导演包覆盖JSON/base64与二进制响应、原时间线与大种子保留、缺素材停止、错误节点、已有文件及坏包／截断不落成品。POST响应丢失和并发下载边界使用单元测试注入，不通过破坏远端制造故障。真实任务排队中／运行中状态、长时间网络中断、任意自定义节点和认证网关不据此宣称全部实测。

## Nora 工作区配置与分享边界

Nora服务配置与任务地址绑定读取[工作区ComfyUI配置](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#工作区-comfyui-配置)。新任务经下方统一入口调用本工具；本工具不另维护业务配置规则。新记录使用执行机器本地时区及偏移，协议原始时间戳如实保存。

明确获授权直接查询、取回或诊断时，使用[配置适配入口](../../scripts/comfyui_config.py)，复用本客户端的命令、输出及错误语义，并从指定工作区为实际地址读取认证，不在命令行传账号密码：

```powershell
python -X utf8 '.agents/skills/nora-ai-short-drama/scripts/comfyui_config.py' --workspace '.' status --url 'https://comfy.example.com' --prompt-id '实际任务ID'
```

命令从工作区根目录执行；`--workspace` 相对当前目录，必须显式提供。支持 `status`、`download`、`export-pack`、`inventory`；子命令参数分别与原通信工具、库存工具说明一致，`--url` 必填。调用范围及地址处理按[固定通信工具与证据](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#固定通信工具与证据)。适配入口只加载凭据并调用原工具，不改配置、不自动重试。独立通信的Python接口为 `Client(url, timeout, basic_auth=(username, password))`，HTTP和WS可复用实例的 `headers`，不将其写入证据。正常后台队列及阶段定稿导出已使用共用配置，无需每个任务另传认证。

获授权盘点库存时使用以下命令；输出与退出码见[库存工具](../../dependencies/comfyui-inventory/SKILL.md)。默认缓存仍在该库存工具的 `state/inventory.json`，可用 `--output` 指定本次保存位置：

```powershell
python -X utf8 '.agents/skills/nora-ai-short-drama/scripts/comfyui_config.py' --workspace '.' inventory --url 'https://comfy.example.com'
```

配置与入口回归使用临时工作区和本机模拟HTTP服务，不读取真实凭据、不调用远端：

```powershell
python -X utf8 -m unittest discover -s .agents/skills/nora-ai-short-drama/scripts -p 'test_comfyui_config*.py'
```

退出0且报告OK表示通过；覆盖跨项目共用配置、逐节点认证、凭据不泄露、禁用直接上传／提交、强制实际地址、库存失败保留旧缓存。

Nora任务准备、查询和取回时，读取[监控规范的精简留档规则](../../../nora-generation/references/ComfyUI-任务监控规范.md#执行附件精简留档)，据此确定附件留存及当前检查时间的维护。

## 后台任务查询与结果处理

入口：[browser_tasks.py](../../scripts/browser_tasks.py)，Python 3.9+、仅标准库。下面各命令共用本节的调用条件，再按实际动作读取对应小节；无需读取上传、提交和素材映射章节。

依赖已启动的[本机浏览服务](../../../../../工作区浏览服务/README.md#日常启动)。脚本自动读取工作区 `工作区浏览服务/runtime/task-service.json` 中的本机接口地址与内部凭证，不手填或输出凭证；各命令均不接收 `--url` 或 `--project`，远端绑定由后台按原任务记录处理。将示例中的技能目录和ID替换为本次真实值。配置缺失、服务不可达或接口拒绝时命令非零退出并输出错误，按[异常处理](../../../nora-generation/references/ComfyUI-任务监控规范.md#31-异常检查与连接恢复)核对，不改走重新提交。

### 后台状态查询

适用于用户主动查询已有任务进度，或处理结果时核对最新后台状态。读取原入队响应的 `local_task_id` 或后台记录的本地任务 `id`；它不是远端 `prompt_id`。

```sh
python "实际技能目录/scripts/browser_tasks.py" status --task-id 本地任务UUID
```

此命令只读本机后台，单次返回任务JSON，不启动监控或轮询。核对 `status`、`updated_at`、`progress`、`collected`／`expected`、`error` 及 `record_dir`；失败阶段存在时读取 `failure_stage`。退出0表示查询成功，生成和取回是否完成仍看任务状态与实际成果。跟进方式见[查询规则](../../../nora-generation/references/ComfyUI-任务监控规范.md#11-待提交跟进方式与间隔)。

### 后台最终报告读取

收到真实后台通知后，在真实来源会话执行；参数是通知批次UUID，脚本读取`CODEX_THREAD_ID`并由后台核对归属。只访问本机后台，不查询远端、不生成、不触发登记或网页扫描：

```sh
python "实际技能目录/scripts/browser_tasks.py" report --notification-id 通知批次UUID
```

后台在发送前已自动完成图片、超分及视频的技术收尾和网页核验，或保存具体失败结果。通知只提供任务身份和报告入口；命令按后台已有的最新任务状态刷新持久报告并自动记录收到，异常修复后的旧通知也返回当前结果，不重新收尾、扫描或发送。原通知和错误经过保留在过程记录。正常图片及超分默认只返回`notification_id`、`status=acknowledged`、`reused`、`user_message_ready`和`delivery`，避免展开重复的状态／收尾内容；`delivery`包含完成任务数、图片数，以及每项标题、任务类型`task_type`、本地任务ID、成果绝对路径、候选路径、实际宽高／格式／字节数、工作稿／收尾报告绝对路径和可直接打开的`review_url`。普通图片按[批次通知规则](../../../nora-generation/references/ComfyUI-任务监控规范.md#图片批次通知与超分静默)集中展示，不再拼路径、数文件、翻记录或查网页；正常超分不发送通知，历史正常超分通知只读确认，不输出进度、完成消息或图片。只有`user_message_ready=true`才能按入口已可审汇报，成功读取不表示用户批准。历史图片／超分缺少展示字段时保留完整报告，按任务类型处理，不补做收尾。正常视频同样只返回`delivery`：`video_count`为本批实际完成数量，`tasks`含标题、阶段身份、文件绝对路径、媒体信息及可直接打开的审核链接；对话只汇报数量和入口。异常仍返回完整`tasks/results`，据失败阶段定位；显式追溯时可加`--details`读取完整报告，不触发重新核验或写记录。未带展示清单的历史报告保留原格式。重复读取`reused=true`且不重复确认事件。

旧通知没有持久报告时返回已有摘要、`legacy_report=true`和`user_message_ready=false`，不会在读取时补做收尾；核对具体缺项后才使用兼容修复入口。

### 后台通知确认

仅供旧通知兼容；正常通知只调用上方report，不另调用ack。使用真实通知批次ID；主动查询没有通知ID时不调用。必须在真实来源会话内执行，脚本读取当前 `CODEX_THREAD_ID`，后台核对通知归属；不伪造会话上下文。

```sh
python "实际技能目录/scripts/browser_tasks.py" ack --notification-id 通知批次UUID
```

成功返回`notification_id`、`status=acknowledged`和本批`tasks`摘要。正常流程读取report已同时确认，不再调用此命令。重复确认返回`reused=true`，不重复追加事件。它只确认Agent收到，不表示用户已批准；图片、超分及视频统一按[监控规范](../../../nora-generation/references/ComfyUI-任务监控规范.md)的对应结果分支交付，异常才展开证据。

### 后台视频待审登记

供旧任务兼容或明确登记／同步异常修复，在真实来源会话内显式调用；正常完成已由后台执行，不需要Agent调用。不提交、下载或生成，不作内容审批：

```sh
python "实际技能目录/scripts/browser_tasks.py" register-results --notification-id 通知批次UUID
```

工具复用取回结果中的本批身份与资料关联（普通保存节点缺少身份时，仅按[精简收尾](../../../nora-generation/references/ComfyUI-任务监控规范.md#视频完成通知后的精简收尾)补取已有检查依据），集中更新既有各P工作稿的成果／凭据入口，不重读固定映射；当前文件／凭据存在性和最终替换前的源文档变化仍核对，并用既有视频审阅模板登记待审；已有审阅决定和旧版本保留。共同状态归共同入口，各P不重复登记共同摘要。工具沿用原执行附件中的`结果收尾报告.json`保存处理进度；中断和重复调用按[收尾规则](../../../nora-generation/references/ComfyUI-任务监控规范.md#视频完成通知后的精简收尾)恢复，不新建临时收尾脚本。

常规成果及待审事实由后台自动登记。异常修复确需本批项目进度行、制作前检查或生成说明的精确业务更新时，可准备UTF-8 JSON数组，在兼容修复调用提供`--record-updates 实际更新文件.json`。每项为`{"path":"项目根相对路径","old":"唯一原文","new":"准备好的替换文字"}`；仅限本批剧集既有对应资料，不支持跨项目混合更新，不修改正式剧本、提示词或批准事实。工具保存这份精确更新的处理进度，恢复调用可不重传；不同方案不能覆盖尚未完成的更新。源文字变化／不唯一时报告`registration_failed`，保留已完成登记及用户文字，不全文件覆盖。

摘要与登记共用稳定成果条目，状态／错误实时读取；取记录目录不展开完整入队参数。网页同步冷启动复用首次扫描，热缓存按本批更新扫描一次，规则见[精简收尾](../../../nora-generation/references/ComfyUI-任务监控规范.md#视频完成通知后的精简收尾)。成功返回本批`results`、每项登记报告和`browser`核验结果；`user_message_ready=true`才表示本批视频网页入口核验通过。报告含登记开始`recorded_at`、完成`registered_at`及`browser.verified_at`。只有网页同步失败时返回`browser_pending`及原报告／源文件入口，重复调用只接续未完成环节。退出0表示接口调用成功，不代替报告中各项状态；登记不齐或异常须说明缺项，不声称全部可审。图片返回`image-review-workflow`，不改变图片审核及展示方式。

### 后台取回重试

后台在整项生成成功后取回全部成果；暂时性下载故障最多自动重试3次，间隔10、30、60秒，HTTP 429遵从有效Retry-After。自动重试期间保持 `collecting`，不重复唤醒Agent；达到上限或发现资料、HTTP权限／缺项、本机文件等不可重试问题后，才进入 `collection_failed` 并通知。次数、等待时间、每轮原因及成功凭据持久保存，后台重启接续原周期，详见[异常处理与授权](../../../nora-generation/references/ComfyUI-任务监控规范.md#31-异常检查与连接恢复)。

以下入口仅用于后台状态为 `collection_failed` 的原任务。Agent核对并处理原因后，用原本地任务ID请求新一轮取回（重新获得最多3次自动重试）：

```sh
python "实际技能目录/scripts/browser_tasks.py" retry-collection --task-id 本地任务UUID
```

成功返回 `local_task_id` 和 `status=collecting`，仅表示后台接受了取回重试，最终结果由后台状态和通知确认。后台复用原终态结果及成功下载凭据，不上传素材、不重新生成；其他状态会被拒绝，不换ID绕过。需要主动核对时用[后台状态查询](#后台状态查询)。

### 后台异常结案

适用条件及业务边界读取[监控规范的异常结案](../../../nora-generation/references/ComfyUI-任务监控规范.md#已核查旧异常的结案)。本机Agent通过以下入口提交已核查的结案请求，不直接编辑运行中的SQLite。

```sh
python "实际技能目录/scripts/browser_tasks.py" resolve --task-id 本地任务UUID --resolution "实际执行附件/异常结案请求.json"
```

`--resolution` 为UTF-8 JSON文件，其路径相对当前目录；字段如下：

| 字段 | 含义 |
| --- | --- |
| `expected_prompt_id` | 原远端任务ID，提交时与后台再次匹配 |
| `summary` | 本次结案说明，分别说明恢复与补齐的范围 |
| `outcome` | `recovered`（原成果已取回）、`superseded`（后续任务已补齐）或`recovered_and_superseded`（两者并存） |
| `evidence` | 已核对的本项目内文件路径数组，相对项目根目录或项目内绝对路径；至少一项 |
| `replacement_task_ids` | 后续补齐任务的本地ID数组；后两种outcome必填，要求同项目且已完成 |

成功返回`status=resolved`；相同请求重复调用返回`duplicate=true`，不再追加结案事件。任务不在适用状态、原ID不符、依据文件缺失／越出项目或替代任务未完成时拒绝，不覆盖既有不同结案决定。工具只写本地任务状态、结案事件及原执行附件中的后台摘要和过程记录，不连接远端，不修改批准记录，不触发通知。原请求、异常和原成果计数仍可在任务详情核对。

## Nora统一分配与提交

入口：[comfyui_dispatch.py](../../scripts/comfyui_dispatch.py)。Agent调用此入口登记后台本地队列，不向远端上传或提交，不等待生成。工作区配置及调度、按钮语义读取[服务配置与任务提交规范](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md)。上方comfyui_client.py为后台复用的通信模块，调用边界见该规范的[固定通信工具与证据](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#固定通信工具与证据)。


### 一次装配与批量入队

默认入口只传项目和一份项目内任务清单；相同一批图片、超分或视频可混合放在`tasks`数组。提示词先按对应技能及固定模板完成内容核对，以下示例正文是字段示意，不可作为最终模型正文。

```sh
python /实际技能目录/scripts/comfyui_dispatch.py \
  --project /实际项目目录 \
  --plan 03-人物资料/其他资料/执行附件/首集角色提交/任务清单.json
```

执行职责读取[图片执行分工](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#图片执行分工)。固定检查由共用准备入口执行一次，Agent不重读种子表或对工作流节点；同批重复输入共用元数据读取，记录中的模型、采样、缓存及预处理字段从实际API生成。

文生图和图生图只复制执行API，不读取、改写或复制原画布；视频沿用现行装配入口。所有类型取消画布与API一致性比较。可配置输出由工具按[远端输出目录](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#远端输出目录与命名)填写；本地执行附件和上传input目录不跟随改变。

图片条目示例：

```json
{"tasks":[{
  "task_type":"image", "object":"CH001", "title":"CH001 · 首集角色六视图",
  "kind":"人物", "image_type":"角色多视角参考图", "state":"大学", "costume":"首集",
  "draft":"03-人物资料/其他资料/工作稿/CH001-参考图-工作稿.md",
  "authorization":"当前用户要求按已批准本体和服装生成首集角色六视图",
  "basis":"已确认人物资料、当前状态与服装批准记录", "description":"按已核对的完整提示词制作六视图",
  "references":[
    {"file":"03-人物资料/CH001-男主/参考图/已采用本体.png","purpose":"人物身份与体型","approval":"03-人物资料/其他资料/工作稿/CH001-参考图-工作稿.md#审阅-生成记录-003-001"},
    {"file":"03-人物资料/CH001-男主/参考图/已采用服装.png","purpose":"首集衣装","approval":"03-人物资料/其他资料/工作稿/CH001-参考图-工作稿.md#审阅-生成记录-004-001"}
  ],
  "prompt":{"rewritten_prompt":"这里填已完成内容核对的完整中文正文","wh_ratio":"1:1","ratio_follow":""}
}]}
```

- `kind`为人物／场景／道具／剧集素材，沿用各自既有工作稿模板。工具自动建工作稿或追加下一生成编号、候选版本及同前缀执行附件；不另建人工调度台账。`fields`可提供该模板中特有的已确认业务内容，技术字段由工具填写。`record_dir`、`generation`、`output`只在明确指定既定入口时填写。
- 人物肖像默认1024×1024、本体六视图和角色六视图默认2048×2048、服装默认1152×864；其他类型或用户明确变更须填`size:[宽,高]`，沿用原规格。`prompt`仍按Qwen规则填写文生图两字段／编辑三字段及准确画幅；工具只注入正文，不优化或扩写。文生图`parameters`只接受已明确的`negative_prompt`；其模型、40步和TE加速等固定值按[文生图说明](../../../nora-generation/references/ComfyUI-文生图执行规范.md#2-提示词与参数映射)维护，配置变更另行授权。图生图`parameters`同样只接受`negative_prompt`；按[图生图说明](../../../nora-generation/references/ComfyUI-图生图执行规范.md#3-参数映射)保留40步、TE加速、参考条件缓存和每张1.5MP缩放。支持1–10张参考图，由工具按清单顺序生成加载、缩放及上传绑定，直接保存解码原图。
- 同一清单的所有`task_type:image`由工具登记相同`image_batch_id`及完整`image_batch_size`；这两个后台关联字段无需Agent手填，不影响生成参数。超分和视频不计入本批图片范围。恢复同清单保留原关联，正常结果按[图片批次通知规则](../../../nora-generation/references/ComfyUI-任务监控规范.md#图片批次通知与超分静默)等齐集中通知。无批次关联的历史或旧式单任务按单任务处理，不追溯猜测合批。
- 不传`seed`时由工具读取项目七类默认种子表；首次类别选定、登记并在同批复用，输入原始种子从批准记录读取。七类之外的图传`supplementary:true`，每次选择新种子，不新增类别默认值。来源／类别冲突停止，不暗中改已确认种子。用户指定参考图改用`user_reference:true,basis:"真实指定依据"`；可提供`source_seed`，非生成图写`source_kind:"非生成"`，生成来源种子未知须有`unknown_seed_basis:"用户明确允许按未知继续的依据"`。既有审批与未知来源处理规则保持。

超分条目只需关联已批准原图及正式目标，不手填RTX工作流、上传／输出映射、收尾JSON或正式表的整行替换：

```json
{"task_type":"image-upscale","object":"CH002","title":"CH002 · 首集服装批准后2倍超分",
 "kind":"人物","draft":"03-人物资料/其他资料/工作稿/CH002-参考图-工作稿.md",
 "authorization":"具体原图已获用户批准，按既定流程2倍超分",
 "references":[{"file":"03-人物资料/其他资料/工作稿/素材/已批准候选.png","purpose":"获批原图",
 "approval":"03-人物资料/其他资料/工作稿/CH002-参考图-工作稿.md#审阅-生成记录-008-001"}],
 "formal":"03-人物资料/CH002-女主/参考图/CH002-首集-服装参考图.png",
 "adoption_fields":{"适用范围":"首集"}}
```

超分条目可选`size:[目标宽,目标高]`，单位为像素，须为两个正整数；未传时沿用原图宽高各2倍。Imagegen获批原图到正式尺寸时必填本类型已确定的正式宽高，例如场景图`"size":[2752,1536]`；不填Qwen原生送审尺寸。工具复用RTX图片基准，在任务副本同步`target dimensions`及宽高控件、API和成果计划，基准仍保留2倍。实际文件必须达到明确目标；不强求原图恰好一半大，不先裁边。画布与API保留ULTRA、strength=1.0、8-bit RGB，批准、源图上传绑定、正式采用及异常规则不变。

工具从原生成条目读取图片类型／状态等字段，生成既有“当前正式资产”表采用更新，版本指向原候选与超分编号，审阅仍指原批准；该表缺少的业务内容在`adoption_fields`按原表头补充，不猜适用场次／状态。需替换已有正式文件时提供`archive`原规则下的历史保存路径。确有额外关联文字须修改时，可选`adoption_updates:[{path,old,new}]`补充具体关联，常规正式表无需提供。原图、历史批准与超分后再审等特殊要求沿用原规则，不借精简提前采用。

视频条目复用已配置好内容、时间线、编辑状态及运行范围的导演台画布；技术API不再由Agent平行编辑。标准版先按[四种配置与生成前询问](../../../nora-generation/references/ComfyUI-H3视频执行规范.md#标准版四种配置与生成前询问)取得用户选择，按该节配置表同时设置本次画布的采样步数和128及342／344／345的启用／旁路状态；53与343常开，343默认3.0。工具沿用画布中已配置的步数，不根据LoRA开关自动选择步数。默认随包API对应选项1；其他选项由本入口从配置后的画布导出。已有一采接二采沿用来源实际参数，不套用新默认值。视频条目示例：

```json
{"task_type":"video-first-pass","title":"EP001-C001 · 一采","authorization":"用户明确授权本次一采",
 "canvas":"09-剧集制作/EP001/其他资料/执行附件/EP001-C001-P001-R001-一采/任务.workflow.json",
 "record_dir":"09-剧集制作/EP001/其他资料/执行附件/EP001-C001-P001-R001-一采",
 "output_nodes":["403","504","506"],"report_node":"403","output_root":"E:/ComfyUI/output",
 "references":[{"file":"03-人物资料/CH001-男主/参考图/当前角色.png","placeholder":"planned/CH001.png"}]}
```

视频执行职责见[视频执行分工](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#视频执行分工)。任务清单自动建立或补齐各P本R本阶段的技术条目，已有非空说明、用户反馈及决定保持；记录从实际API、语义映射和后台事实生成，不手填模型参数、ID、秒数／帧数或冻结资料入口。

- 新一采可传`sync_timing:true`，以内容画布中已核定的各组durationSec计算17k+5帧格、start、length、总帧数并同步根字段及r2v编辑区。使用新的执行目录保存副本，原内容画布不改写；二采、返修或带历史source／materials_from的任务不使用此选项，保持来源与缓存身份。
- 新核对可在任务条目的`content_review`传逐组语义注释：`groups`中每项含`index`、`chinese:{file}`、`subjects`、四类`checks`及各自真实note／prompt_quote／chinese_quote／sources的file和quote；单导演台可省node。**不手填input_sha256、中文或依据sha256**，脚本按本次实际API和文件绑定。既有已绑定记录继续在原mapping使用，不自动刷新，不由脚本补passed；未做语义核对仍会失败。详细字段含义见[内容核对检查](#h3正文与内容核对检查)。
- 标准单段H.264 MP4后处理可不传outputs，工具从唯一VHS_VideoCombine保存节点和已选P／R派生目标及取回凭据；其他保存结构须显式提供实际输出映射，不猜节点。
- 清单视频任务自动带媒体信息读取计划：通知前仅用本机ffprobe读取一次stream／container事实，将实测值写入原结果收尾报告和分段记录；网页重试复用未变化的测量，report读取不再测量。缺少ffprobe、无法读视频轨或文件变化返回技术异常，不转交Agent手测或自动重生成；不安装依赖、不抽帧或运行内容／质量评价。既有已接受任务不追溯补测。

`output_nodes`为本次画布的实际执行输出节点；标准版示例的403／504／506不能照搬到不同工作流。`output_root`为已核实的远端真实目录。既有`输入映射.json`复用，不复制粘贴；新映射可在`mapping`传入既定语义信息。分镜版本、场次修改轮次、组与P／R对应、内容核对证据仍须准备；工具不替代这些内容决定。工具导出配套API，按已选原始组序、P／R／阶段派生候选路径与取回凭据，按`references`中的占位值定位图片／音视频素材槽位、组装上传映射；原映射和冻结资料仍由既有后台保存。二采使用指定来源画布及既有批准关系，不能换成新的基准。后处理或特定输出可显式提供原格式的`outputs`／`segment_plan`／`uploads`，仍共用本次装配、准备和入队。

`references`是素材占位值到源文件的单一填写入口。工具同时建立技术上传槽位和`输入映射.json`的`uploads:[{input_path,file}]`来源索引；同占位值、同源文件只登记一条来源，重复的`references`条目复用同一套槽位绑定，同占位值对应不同文件则在写入前报错。已有来源索引保持兼容，不要求Agent重复填写。画布控件修改由工具同步`widgets_values`和`widgets_values_named`，保留预览等界面字段；执行范围按[视频执行分工](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#视频执行分工)处理。

返回与接续：

- 成功：`status=enqueued,tasks:[{local_task_id,title,task_type,status,record_dir}],next_action=end-turn`。**立即汇报数量并结束本轮**，不再补ID、进度、技术记录或检查网页；后台保存动态状态和成果。
- 仅准备：同一命令加`--prepare-only`，返回`status=prepared`；不入队／上传／生成。内容不变时可只补充各条`authorization`再正式调用；模型正文、素材或范围变更属于新的准备，不能覆盖已接受清单。原逐项入口也保留仅准备能力。
- 异常：整批先完成准备，任一准备失败则不入队；若登记中断，`partial`返回已接受ID及错误。`任务清单-装配结果.json`保存装配及已接受项；同清单恢复先找回原ID，只登记尚未接受部分，不重复POST。已登记任务的内容或来源不能覆盖原装配记录；尚未登记的准备修正按下方接口办理。只在异常时查这些附件，不在正常成功后再读一遍。

#### 未登记清单的重新准备

准备失败或仅准备后修改内容时，先在原任务清单及独立内容画布中修正输入，再显式重新准备：

```sh
python /实际技能目录/scripts/comfyui_dispatch.py \
  --project /实际项目目录 \
  --plan 09-剧集制作/EP001/其他资料/执行附件/本次任务/任务清单.json \
  --prepare-only --reprepare
```

`--reprepare`仅与`--plan --prepare-only`合用，不上传、不入队、不生成。限同一来源会话、整份清单尚无已登记任务；即使装配记录漏存已接受ID，只要后台存在对应执行目录，也拒绝重装。工具将原装配记录（含原写入内容）及当时检查报告保留在同目录的`任务清单-装配结果-准备归档-NNN.json`，从原始输入重新装配并在原执行目录检查，不因重新准备增加候选轮次。任一原准备文件被其他会话修改时停止，不覆盖。原地重装失败仍不入队；缺少原装配记录时按常规命令准备。重新准备返回`status=prepared`后，复用未变化的授权依据，以不带两个准备参数的原命令正式入队；本轮仅获准准备时保持不入队。已有本地ID的资料修正按[原任务重新准备与恢复](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#重新调度与失败恢复)处理，不用此参数重装清单。

### 已备资料的逐项参数入口

已有完整API、上传／成果／收尾计划的任务可继续使用下列参数方式；正常新任务优先使用上方`--plan`，不先由Agent手工制造这些技术附件。

```sh
python /实际技能目录/scripts/comfyui_dispatch.py \
  --project /实际项目目录 --task-type image \
  --workflow /实际执行附件/本任务-工作流.json \
  --record-dir /实际执行附件 --task-title 'CH001 · 首次生成' \
  --attempt-name 本任务-提交尝试.json --request-name 本任务-请求.json \
  --response-name 本任务-提交响应.json --history-name 本任务-执行结果.json \
  --output-plan /实际执行附件/成果取回映射.json \
  --image-plan /实际执行附件/图片收尾计划.json
```

| 参数 | 含义 |
| --- | --- |
| --project、--workflow | 当前设备项目根目录、最终API任务副本；必填，命令行可使用当前设备绝对路径。H3副本按[任务参数来源](../../../nora-generation/references/ComfyUI-H3视频执行规范.md#12-任务参数来源与准备提交)制作，入口不自动加载基准或覆盖生成参数 |
| --record-dir | 项目内既定执行附件；必填，相对路径以--project指定的项目根目录解析，也可用项目内绝对路径；后台保存相对路径 |
| --task-type | image、image-upscale、video-first-pass、video-second-pass、video-postprocess，按实际获授权阶段 |
| --task-title | 必填非空标题，格式由Agent遵守[标题规则](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#任务显示标题)，后台不补目录名 |
| --eligible-url | 可选预期主节点地址，仅与项目第一项比对，不核验远端能力 |
| --prepare-only | 只作工具准备检查并写报告；不入队／上传／生成 |
| --uploads | 可选本机素材与节点输入绑定JSON，后台准备时实际上传 |
| --output-plan | 必填JSON数组，普通输出明确节点、字段、序号和本机目标；导演台使用空数组及segment-plan |
| --image-plan | image及image-upscale必填；见下节。图片收尾的章节、目标规格及批准后正式保存关联；非图片任务不传 |
| --segment-plan | 原生H3分段必填，含导演台、报告节点、核实output根目录及每个选中组的显式本机目标 |
| --attempt-name、--request-name、--response-name、--history-name | 各种证据的单个文件名，不能重复或占用后台任务状态.json、后台过程记录.json |
| --timeout | 单次网络操作超时，默认30秒，不是排队或生成时限 |
| --monitor | 仅支持browser，服务缺失时报告接入问题，不回退legacy |
| --start-paused | 可选，仅在已授权手动转移等需要先暂停的操作中使用；登记时直接为paused，恢复前不上传或提交；默认不传，自动排队 |
| --thread-id | 默认真实CODEX_THREAD_ID；通知其他会话须有用户授权 |

### 图片及超分收尾计划

`--plan`由工具装配本节计划及既有生成条目；下列为旧式参数入口和异常定位所用格式，正常新任务不手填。与API、上传及成果映射一起在准备阶段写入原执行附件；`--prepare-only`与正式入队使用同一计划。技术及审批分工以[监控规范第4节](../../../nora-generation/references/ComfyUI-任务监控规范.md#4-图片处理)为准。路径相对项目根目录，宽高单位为像素。`images`必须与output-plan一一对应；`kind`选择人物、场景、道具或剧集素材，引用对应既有工作稿模板，不改变图片画风。工作稿须已有本次生成条目及审阅区；后台在成功取回后建立实际审阅记录。

```json
{
  "draft": "03-人物资料/其他资料/工作稿/CH001-参考图-工作稿.md",
  "kind": "人物",
  "generation": "生成记录-001",
  "review": "审阅-生成记录-001-001",
  "images": [{"path": "03-人物资料/其他资料/工作稿/素材/CH001-服装参考图-候选-v01.png", "width": 1152, "height": 864}],
  "record_updates": []
}
```

`record_updates`可选，默认空数组；需要同步本批项目进度、资料卡或索引时，在生成前提供实际Markdown的`path`、唯一`old`原文和`new`目标文字，后台在结果成功后执行，不在通知后让Agent补写。支持`{{outputs}}`、`{{specs}}`、`{{evidence}}`、`{{time}}`；超分还支持`{{file}}`。链接按每个目标文档的位置计算。原文不唯一、并发改变或未知占位符停止对应更新，不覆盖其他修改。

获批超分使用原生成及批准章节，images填写超分候选路径和正式尺寸，并增加`upscale`对象：

```json
{
  "number": "超分-001",
  "source": "03-人物资料/其他资料/工作稿/素材/CH001-服装参考图-候选-v01.png",
  "approval": "03-人物资料/其他资料/工作稿/CH001-参考图-工作稿.md#审阅-生成记录-001-001",
  "formal": "03-人物资料/CH001-人物/参考图/CH001-日常-服装参考图.png",
  "archive": "03-人物资料/其他资料/历史版本/CH001-日常-服装参考图-归档-实际时间戳.png",
  "record_updates": [{"path": "03-人物资料/其他资料/工作稿/CH001-参考图-工作稿.md", "old": "实际待替换的唯一正式资产表行或表头", "new": "实际更新后的表行，正式文件使用{{file}}并引用原批准章节"}]
}
```

此对象填入计划的`upscale`字段；示意文字及路径须替换为当次真实值。`source`必须是原批准章节明确批准的具体候选，并实际绑定节点2上传；节点1按实际计划执行2倍或指定宽高、节点3保存PNG。指定尺寸API使用`resize_type:"target dimensions"`及`resize_type.width`、`resize_type.height`，与`images`计划宽高一致；倍数模式仍为`scale by multiplier`和`resize_type.scale:2`。`formal`为实际正式路径；首次保存可省略archive，替换已有正式图时必须给出真实、未占用的历史路径。`upscale.record_updates`必填，准备当前正式资产表及受影响卡片／索引的实际更新，不改写用户反馈、批准或旧版本事实。后台补超分子记录，保留原审批图，不增加默认画面审批；用户明确要求超分后再审时不得使用自动正式采用计划。

正常结果直接读取report。缺少计划的旧任务只报告缺项，不自动搜索或猜测；明确核对原关联后，可将`{本地任务UUID: 完整计划}`写入原附件，通过`browser_tasks.py register-results --notification-id 通知UUID --image-plans 旧图片收尾关联.json`显式修复。此命令仅允许本通知中的图片任务，不覆盖已有不同关联，不重新生成；返回真实登记及网页结果，不改写已发送的历史报告。

### 工作稿当前正文集中同步

入口：[sync_current_documents.py](../../scripts/sync_current_documents.py)，Python 3.9及以上标准库。用于将明确选定的工作稿“`## 1. 当前内容`”正文同步到对应正式文件；准备与检查时机执行[集中同步与检查规则](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#准备资料的集中同步与检查)。仅同步已编写的内容，不生成或审核正文、不改变确认状态、不联网、不修改工作稿、任务库、凭证、媒体或执行记录。文档采用及工作稿接替仍按[工作稿管理规则](../共用规则/文件版本与工作稿规范.md#工作稿管理规则)处理；运行工具不等于采用。

```sh
python -X utf8 /实际技能目录/scripts/sync_current_documents.py \
  --project /实际项目根目录 --plan /本批同步计划.json \
  --archive-dir 09-剧集制作/EP001/其他资料/历史版本/正文同步-YYYYMMDD-HHmmss
```

计划为UTF-8 JSON数组，只填写本批需要同步的文件：

```json
[{"draft":"09-剧集制作/EP001/其他资料/工作稿/EP001-本集剧本-工作稿.md",
  "target":"09-剧集制作/EP001/02-剧集剧本/EP001-本集剧本.md"}]
```

`--project`为当前设备项目根；`--plan`文件地址相对当前工作目录或为绝对地址。计划中的`draft`、`target`和`--archive-dir`相对项目根，也接受项目内绝对路径，不重复`projects/项目名`。归档目录须位于项目的`其他资料/历史版本`，本批使用未占用的时间戳目录；旧正式文件按原项目相对目录完整保存。计划支持多文件，工具预先解析整批后再写入；任何缺章节、代码围栏不闭合、目标重复、越界或归档冲突均报错，不发布已预检但尚未写入的条目。实际写入时的IO失败须按错误及已有归档核对，不声称整个批次已完成。

同步正式场次分镜或本集分镜索引时，写入前自动检查该集索引的完整分段编号、所属场次一致性及场次是否存在于剧本正文；具体编号执行[层级编号规则](../共用规则/层级编号与时长规范.md#1-层级编号与时长)。同批包含剧本或索引时检查本批转换后的正文，其余读取现行正式文件；缺少所需剧本／索引、没有可读取的分段表或编号不符时，整批在归档和写入前报错，不自动改号。此检查复用同一工作区`工作区浏览服务/backend/parsers/project.py`的表格与编号校验函数，须配套提供该文件，但不要求服务运行或联网；非分镜资料的同步不加载该依赖。

工具只提取当前章节，遇到下一个同级编号章节才结束；代码围栏中的标题、模型正文和链接保持原文。文档标题层级提升两级，相对文件链接按正式文件位置换算，正文内镜头／章节锚点保留，正文外审阅锚点指回完整工作稿。结果使用UTF-8／LF；源与目标分别按唯一文件读取，同批复用，写前检查是否被其他写入者改变。内容相同不重写、不改变修改时间、不新增归档；不同内容保留旧正式文件后再替换。

成功退出0并返回`ok=true`、`written`、`unchanged`、`archives`路径列表；失败退出非0并给出具体错误，不能当作采用、生成或网页同步成功。按既有浏览规范集中核验本批条目，不逐文件触发页面检查。

回归测试仅使用临时项目目录，不读取正式服务凭证或任务库；覆盖正文与链接转换、整批预检及归档，以及分镜编号／剧本场次关联、同批正文优先和失败不发布：

```sh
python -X utf8 -B -m unittest discover -s /实际技能目录/scripts -p test_sync_current_documents.py -v
```

覆盖嵌套编号标题、代码围栏、正文内／审阅锚点、相对链接、中文和CRLF、整批预检失败、项目范围、同源文件只读一次、重复执行不改时间及旧正式文件留存；退出0且全部通过才表示这些行为验证通过，不替代内容核对。

### 准备检查与提交复用

同一命令在准备阶段加`--prepare-only`，由后台检查并在原`--record-dir`写`执行检查报告.json`，不上传、不入队、不生成。参数、计划文件与正式提交相同；准备命令不要求已有生成授权。返回`dispatch_state=prepared`和`prepared=true`才表示工具检查成功；失败报告写具体错误，不等于内容审核通过。

```sh
python /实际技能目录/scripts/comfyui_dispatch.py \
  --project /实际项目目录 --task-type image \
  --workflow /实际执行附件/本任务-工作流.api.json \
  --record-dir /实际执行附件 --task-title 'CH001 · 首次生成' \
  --output-plan /实际执行附件/成果取回映射.json --prepare-only
```

用户授权后调用相同命令、移除`--prepare-only`即可登记队列，不再次展开内容或人工核对技术项目。登记只确认调用身份、项目／路径范围、后台登记记录和重复任务，不读取准备报告，不检查上传映射字段／类型／json-path或文件名称，也不运行基础结构、节点绑定或分段／输出身份等固定检查；三份提交证据的存在性检查及独占保护集中到底层通信工具，具体错误语义见[submit调用说明](#submit只提交一次)。后台轮到实际执行时统一比较一次准备输入及相关文件的存在性／大小／修改时间；未变复用，变化则停止，先在准备阶段修改并重新检查。新登记任务开工必须具备通过且完整的准备报告，缺失、失败或缺项时暂停，先显式使用`--prepare-only`完成准备，不在开工补跑；该要求随登记状态持久保存，重启及恢复不放宽。只有要求启用前已登记的旧任务才可在开工补检并标明`checked_during=execution`；范围见[执行前检查与复用](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#执行前检查与复用)。已有报告仅缺资料关联时，准备入口与获准的旧任务开工补检复用已覆盖的分段计划结论，只检查未覆盖项，具体范围见[执行前检查与复用](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#执行前检查与复用)。上传后直接使用本次上传结果核对被绑定的公共／分组槽位及编辑区镜像、实际路径和文件字段，只同步受影响的API输入，以及视频、超分或历史任务已有任务画布的相应控件；文生图和图生图不生成任务画布、不回写原画布，不重建整张工作流或比较画布与API，绑定未变时不读取或改写API／画布。实际输入映射和冻结资料仍由后台保存，不需要Agent另跑关联脚本。职责与检查范围以[执行前检查与复用](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#执行前检查与复用)为准。

正常准备与提交不查询远端`/object_info`、`/models`或系统能力清单，不以库存时效决定能否提交。目标端默认可执行所提供工作流；真实节点／模型／参数错误由远端返回，工具保留原始详情及失败阶段，Agent读取报告，不自行重试。明确要求能力盘点或依赖诊断时才调用inventory工具。队列、阶段缓存和实际上传响应仍按本次执行需要处理，它们不属于能力预检。

固定 `--prepare-only` 入口还执行已知RTX节点必填输入的本地检查，要求见[RTX节点共用必填输入](../../../nora-generation/references/ComfyUI-图片超分执行规范.md#rtx节点共用必填输入)；API缺少必填输入时停止。此检查由准备工具承担，不由Agent另查远端，不在普通入队时重复；其他结构、素材、资料关联和准备报告检查继续由后台执行。接口差异的定点诊断与基准维护按[远端能力与错误返回](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#远端能力与错误返回)处理。

目录占用不按自定义文件名在入队时扫描：后台登记状态／过程记录与SQLite任务身份用于防止覆盖另一个登记；API、画布、映射等准备文件允许存在。准备报告匹配后，已有上传凭据由上传环节按端点和文件指纹恢复，同进程资料未变复用核验、重启首次恢复按唯一文件核验；已有终态／下载凭据由提交环节阻止新生成。底层三份提交证据和实际成果的防覆盖继续在各自操作环节执行。

上传映射的字段／类型／json-path（含末级字段存在性）、上传目录、源文件名和证据名称统一由准备工具检查。上传绑定直接写入已确认的字段，不重查其存在性；项目路径直接复用接收入口的解析结果。分段取回与生成资料共用一次分段检查结果；逐段显式成果目标在准备时检查，H3阶段检查按是否有分段计划选择一个调用位置；具体分工见[固定检查与动态条件](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#固定检查与动态条件)。后台传入准备后的源路径和工作流对象，通信不重复计划输入检查；真实上传响应的文件身份仍须核对。独立CLI文件调用保留其输入检查，无新增跳过检查的命令参数。

尚未提交的已登记任务需要修正资料时，先暂停，再显式运行同一命令并加`--prepare-only`。同来源、同阶段、同端点及成果范围，且没有提交／成果证据时，成功响应包含原`local_task_id`，更新原任务及准备报告，保持暂停；失败不替换原输入。之后从网页恢复原任务。普通恢复按钮不会重新加载修改后的JSON。已有提交证据或远端ID不得这样修改或重发。

旧报告补项的原来源与新增关联文件共用本次状态读取，重合项直接复用、只读取新增文件；范围及变化处理见[执行前检查与复用](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#执行前检查与复用)。开工比对本次实际读取的素材文件状态直接供上传环节复用，上传后的变化检查继续保留；适用范围见[固定检查与动态条件](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#固定检查与动态条件)。因队列变化重新调度时复用已完成上传、绑定、执行副本及冻结资料，只核对文件变化和当前队列／H3缓存。准备报告与阶段恢复共用同一次开工的文件状态读取，API／画布等重合文件不重读，两份依据仍分别比对；未读取的文件按需读取一次，上传前基准直接复用，后续必要变化检查保留，具体边界见[重新调度与失败恢复](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#重新调度与失败恢复)。重启按现有凭据恢复必要阶段，未变化的固定检查不重做；实际文件状态及已完成阶段信息保存在既有任务状态。执行记录保存复用本任务已核验的路径转换，新路径仍核验范围；适用边界见[固定检查与动态条件](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#固定检查与动态条件)。技术职责及异常处理统一见[重新调度与失败恢复](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#重新调度与失败恢复)。

提交前资料处理直接复用首次字段路径验证取得的绑定值，同一准备／保存阶段共用已核验的路径解析结果；实际读写仍核验真实目标与项目范围。输入映射保留首次原文供本轮变更比较，冻结快照共用唯一路径的存在性与内容；保存前仍检查目标变化并独占创建新文件。独立调用及旧报告补项只补未取得的结果，不跨调用复用；完整边界见[固定检查与动态条件](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#固定检查与动态条件)。

`执行检查报告.json`保留实际登记输入、准备时的源文件大小／修改时间、API结构、H3各组字符数／标签／容量结论，不保存私有桌面连接信息。它是本次工具技术报告，不能占用提交／下载凭据名称。后台任务详情的记录列表可直接打开该报告。准备中的内容判断及审批依据仍在既有业务文档；报告不替代它们。

### 浏览服务监控接入

`--record-dir`、上传绑定的`file`、普通成果的`path`及分段`targets.path`共用项目根目录基准，与当前工作目录无关。例如`--project /工作区/projects/示例项目`时，执行目录填写`09-剧集制作/EP001/其他资料/执行附件/本任务`，不能填写`projects/示例项目/09-剧集制作/...`或再次加上项目名。也可填写该项目内的完整绝对路径。Agent入口和后台在入队前拒绝重复前缀及越界路径，明确报错，不猜测或自动剥掉前缀；失败时不会登记任务、创建执行目录或开始上传。`--workflow`、`--output-plan`、`--uploads`等JSON文件参数仍按当前工作目录定位，计划文件中的本机素材和成果路径才按项目根目录解析。已有历史证据兼容读取，不把新入队校验用于改写原始响应。

先启动[浏览服务](../../../../../工作区浏览服务/README.md#日常启动)，在真实Codex执行环境调用入口。Node、已安装桌面适配器、CODEX_THREAD_ID及CODEX_APP_TOOLS_PIPE_PATH用于来源会话通知，不伪造。连接上下文只存本机runtime，不暴露到项目证据或网页。专用接口接受本机Agent凭证，不接受浏览器Origin。SQLite、runtime及本机连接不随技能分享；缺少完整工作区后台时不能执行这条入队流程。

普通成果映射示例：

```json
[{"node_id":"实际保存节点ID","output_key":"images","index":0,
  "path":"候选/CH001-本次版本.png",
  "response_name":"本任务-取回响应.json"}]
```

path是Agent指定的项目根目录相对路径及文件名，不是远端路径，不放执行附件。当前设备的项目内绝对路径仍可作为入队参数，但后台转换为相对路径保存；上传映射file及分段targets.path使用同一规则。节点、output_key和从0开始的index选择真实结果；后台完成后再从history取得远端filename／subfolder／type。普通任务不得空映射；导演台原生分段使用output-plan空数组并提供如下segment-plan。文件名与路径须换成真实项目值：

```json
{"director_node":"502","report_node":"403","output_root":"E:/实际ComfyUI/output",
 "targets":[{"index":0,
  "path":"09-剧集制作/EP001/其他资料/候选视频/EP001-C001-P001-R001-一采.mp4",
  "response_name":"P001-最终取回.json"}]}
```

targets必须逐一对应输入映射selected_indices，保留原始组序，不压缩未选组。report_node必须连接director_node的report槽位5；output_root按远端实际配置核实。后台按[任务完成后取回全部成果](../../../nora-generation/references/ComfyUI-任务监控规范.md#2-留档与收尾)读取成功任务的最终报告，将全部预期文件保存到targets指定位置；不使用运行日志或猜测目录，不覆盖已有文件。

入队成功返回dispatch_state=enqueued、local_task_id（UUID4）、monitor_id及status=local_queued（使用--start-paused时为paused）；此时还没有远端prompt_id。对同一执行附件、相同入队资料重复登记返回原ID；资料不同拒绝，不能改目录绕过原任务。后台真正提交后保存远端ID和实际请求。完成、失败、重启与通知规则读取[任务监控规范](../../../nora-generation/references/ComfyUI-任务监控规范.md)。

入队后的Agent操作直接进入[后台任务查询与结果处理](#后台任务查询与结果处理)，按当前动作只读对应工具小节。

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

映射中的本地路径以项目根目录解析，也可使用项目内绝对路径；不得越出项目。`uploads`记录素材的本机来源映射；清单准备阶段可由`references`自动建立`planned/...`占位来源索引，上传后由后台关联真实远端路径及凭据。本轮新上传素材由后台依据下方上传绑定及实际响应补充到资料保存模块，`input_path` 分别与API的 `imageFile`、`videoFile`、`audioFile` 对应，复用旧上传也须记录本轮真实本地输入版本。它与下方 `--uploads` 的节点输入上传接口不同，不能相互替代。正式一采／二采沿用原生r2v导演台，公共开关 `global.commonEnabled` 显式填写；API实际选择状态、公共／本组正文及三类素材槽位决定保存内容。按 `refs`、`refVideos`、`refAudios` 依次保存图片、视频、音频，各类型按index排序且编号独立；本组同类型同槽位覆盖的公共素材不记作本段实际输入，公共开关关闭时不保存公共素材或正文。既有单视频 `referenceVideo` 兼容为视频index 0，存在原生同槽位时采用原生项，与[节点实际输入规则](../../../nora-generation/references/ComfyUI-MiniMaxH3导演台节点使用规范.md)一致。

二采在每个实际执行组中另填 `source`，指向同P获批来源的完整执行身份；二采保存自己的当次输入并保留来源。后处理只需场次、实际组序及含 `segment`、`round`、`source` 的分段项，来源为本次实际使用的完整执行身份，不另生成空提示词或参考素材。

可选的 `storyboard_file` 指定项目内已冻结分镜，仍核对 `scene_storyboard_version`；不填写时读取正式分镜。同R故障补做按[修订与过程规则](../流程规范/逐集目录与资产管理规范.md#视频修订编号与执行过程)使用阶段目录内 `执行-YYYYMMDD-HHmmss/`，`--record-dir` 及各选中组的 `local_execution_dir` 对应该次位置；提交命令、文件名和防重检查不变，建立新位置不能代替旧任务的活动／接受核对。

每个 `segments` 项可选填写 `materials_from: {"mapping": "项目内原输入映射.json", "identity": "EP001-C001-P001-R001-一采"}`，引用同分段原关联的分镜、提示词与实际参考素材。工具按当前实际输入逐项核对正文、文件字节与槽位后引用旧冻结文件，差异时报错，不冒充沿用；新工作流/API仍单独保存。若素材有修改，不填写整套复用字段，按新输入冻结。复用不继承视频批准，也不递归推断最新资料。

分镜版本、执行身份及正文对应在准备检查中确认，资料未变复用结论。后台完成素材上传后，在POST前按实际输入保存：正式场次分镜全文冻结为共同目录 `分镜脚本.md`；各P按[语言适配](../../../nora-video-prompts/references/视频提示词制作规范.md#h3模型正文的语言与命名)编写的实际公共＋本组正文保存为其执行目录 `模型提示词.txt`；实际图片、视频和音频参考素材冻结于共同目录 `输入素材/`；中文按[生成版本的资料关联](../流程规范/逐集目录与资产管理规范.md#生成版本的资料关联)从本组已核对文档自动提取、冻结为各P执行目录内的 `中文提示词参考版.txt` 并关联；历史冻结或复用资料保持原来源，无依据的旧任务不补译。最后自动补齐共同映射的 `generation_contexts`、记录时间与依据，保留原字段值。缺文件、映射不符或试图覆盖不同冻结资料时暂停任务并保存原因，不发送生成POST；同一准备输入重复检查不改写快照。保存资料不代表服务器已经接受任务，仍以提交结果的真实prompt_id为准。

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

节点编号、输入名及上传来源按实际API填写。后台向任务当前归属节点上传后使用真实返回的input_path连接；响应保存在record-dir内，成功响应的url必须与该任务实际节点一致才可复用。节点归属及手动转移读取[服务配置与任务提交规范](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#本地队列与按钮)。上传状态不明、响应为空或失败时停止并核对，不自动重复上传；原上传证据不覆盖。映射属于生成前准备或技术执行附件，不改变现有生成／审阅记录模板。此映射不是视频模型的Picture／Audio／Video标签表，业务标签仍须按既有规范核对。

标准输出为JSON。退出0且data.dispatch_state为enqueued表示本地入队成功，保存local_task_id；不代表远端已经接受或任务完成。接口或配置错误退出1，先查询后台记录，不自动重试远端POST。

工作流仍按本次声明的任务类型校验；原生H3任务继续核对阶段、输入映射及分段计划，不读取远端其他任务的工作流判断是否可提交。

后续查询、取回重试及通知确认使用[后台任务查询与结果处理](#后台任务查询与结果处理)中的对应接口；后台负责原远端地址、提交证据和防重复。

调度回归测试使用模拟响应及临时目录，不连接服务器、不生成媒体：

```sh
python3 -B -m unittest discover -s '/实际技能目录/scripts' -p 'test_comfyui_dispatch.py' -v
```

退出0并报告OK表示通过。Agent入口测试覆盖纯入队、主节点配置、素材绑定、本地ID和不访问远端；后台队列、通知及取回测试在工作区浏览服务/tests维护。真实模型兼容性仍需实际任务验证。

导演台素材藏在timeline_data JSON内时，上传映射可加json-path数组；每个组件为字段名或数组下标，绑定必须已经存在。例如：

```json
[{"file":"素材/参考.png","node":"502","input":"timeline_data",
  "subfolder":"本次任务","response-name":"上传-001.json",
  "json-path":["global","refs",0,"imageFile"]}]
```

后台使用实际返回的input_path替换这一字段，保持原工作流副本和大整数种子。新上传素材的本机来源同时交给资料冻结模块；已有远端素材仍按输入映射uploads核对来源。

## 视频阶段编号迁移

编号规则由[逐集目录规范](../流程规范/逐集目录与资产管理规范.md#视频修订编号与执行过程)维护。已有记录须有明确迁移授权；固定工具 `../../scripts/video_revision_migrate.py` 只整理本地身份和引用，不联网、不生成、不变更审批。请求JSON包含 `episode` 和 `identities` 数组，每项填写完整的 `old`、`new`，下游另填写真实上游 `source`；先核对修订沿革，不以执行次数自动推算版本。

```powershell
python .agents/skills/nora-ai-short-drama/scripts/video_revision_migrate.py --project "projects/项目名" --request "项目内的迁移请求.json" --database "工作区浏览服务/runtime/comfy-tasks.sqlite"
```

默认只读预览，返回身份对应、文件移动、记录及后台任务数量。确认预览与授权一致后，停止本工作区浏览服务，再用相同参数加 `--apply --report "项目名/99-综合资料/其他资料/历史版本/编号迁移-实际时间.json"` 执行；数据库参数指向该已停止服务的真实任务库。脚本拒绝活动任务、越出本集的身份、跨片段／阶段修改及覆盖无关目标。保留迁移前文本与任务行、旧新身份和路径对照；视频及原请求、工作流、响应、下载凭据只移动、不改字节。生成资料关联、当前取回映射、工作稿、审批链接、网页修改意见、后台当前结果入口随身份更新，原通知和事件不重发。导演包及画布是已导出的执行档案，保留原字节，来源引用按旧新身份对照追溯。

返回 `state=completed` 才表示本地迁移完成；恢复服务后还须核对网页各阶段候选号、原审批状态、来源资料与下载入口。失败按报告中的原记录和移动对照恢复，不再次执行同一迁移报告。不使用该工具迁移仍在运行的任务。验证命令：`python -m unittest discover -s .agents/skills/nora-ai-short-drama/scripts -p test_video_revision_migrate.py`，覆盖跨阶段来源、编号重叠、原媒体／请求字节、审批／备注保留和活动任务拒绝。

## 场次修改轮次登记

规则见[场次修改轮次](../共用规则/场次版本组合规范.md#场次修改轮次)，计划字段见[模板](../模板/场次修改轮次模板.md)。在当前集中修改形成送审或执行方案后调用一次；不是每次保存、失败重试或结果取回都调用。完整计划列出全部分段；局部计划明确`base_round`及完整的`segment_changes`条目，由工具展开沿用项。未提供的剧本／分镜引用沿用基轮，不能增加、删除或重排分段；新布局必须提供完整`segments`。两种计划互斥，不从执行时间线或R最大值拼造播放组合。

```powershell
python -X utf8 .agents/skills/nora-ai-short-drama/scripts/scene_rounds.py --project "项目根目录绝对路径" --episode EP003 --scene C001 --plan "完整组合计划.json"
```

从工作区根目录运行，Python标准库即可。`--project`指定实际项目根目录，`--episode`和`--scene`为目标集／场次；`--plan`是UTF-8 JSON文件路径。工具核对文件范围、文档版本和分段身份，保留剧本分镜副本并调整相对链接，向唯一组合JSON追加下一轮；原R、提示词、输入素材、执行和审核记录不改。未变文档复用上一轮副本，旧轮次不覆盖。成功输出组合文件、轮次整数和分段数，错误以非零退出，不联网、不生成媒体、不登记后台任务。新视频任务输入映射必须使用输出的轮次整数填写`scene_modification_round`，并填写`screenplay_version`、`scene_storyboard_version`及选中组的`duration_seconds`（兼容既有`durationSec`）。准备报告保存所引用的组合，校验选中组身份、版本和计划时长；未选中组仍可保留原缓存时间线，不用它确定整场播放候选。后续增加其他轮次不会使该报告失效。只有原先已登记的旧任务保留无此字段的恢复兼容，不改原执行证据、不补造轮次归属；旧报告不能用于跳过新任务准备。

回归检查（工作区根目录，隔离临时项目与模拟端点）：

```powershell
工作区浏览服务/.venv/Scripts/python.exe -X utf8 -B -m unittest discover -s 工作区浏览服务/tests -t 工作区浏览服务 -p test_scene_rounds.py -q
```

此项覆盖完整与局部组合、沿用项、执行旧缓存组与播放身份分离、版本与时长不符；准备复用、旧任务恢复和只回写实际成果分别由`tests.test_submission_lifecycle`、`tests.test_result_closeout`覆盖，从`工作区浏览服务`目录运行相应unittest模块。退出码0且显示OK为通过，不调用真实服务、不生成媒体。


## H3正文与内容核对检查

用于原生H3导演台一采、二采的正文准备；业务顺序与证据含义由[内容核对规范](../../../nora-video-prompts/references/视频提示词制作规范.md#提示词编写与检查顺序)维护。逐组优先读取`taskType`／`task_type`，未指定时沿用公共区及导演台模式；同一画布不同模式分别检查。r2v／v2v／rv2v使用Ref2VA六节及Subject对应；t2v／i2v／fl2v使用基础三节，按实际首尾图槽位检查首行对齐说明、结束时点和镜号。基础模式不强制Subject表，可填写`subjects:{}`；四类内容核对及中英文对应仍完整保留。fl2v支持首尾、仅首、仅尾及无图文本组，不将普通r2v参考误当作首尾帧。具体正文结构按[h3-prompt-writing模式指南](../../../h3-prompt-writing/SKILL.md)执行。

独立离线入口只读本机文件，不联网、不上传、不入队、不调用模型。正常生成仍用已有`--prepare-only`，同一检查自动纳入`执行检查报告.json`的`content_checks`；不能用离线报告代替正式准备报告。模式与首尾图包含在本次内容绑定中，修改后需重新准备；不回写历史任务的原正文或批准事实。

在工作区根目录使用可用Python 3.10＋运行，Windows加`-X utf8`。路径参数相对当前目录；`--basis-file`和输入映射内证据路径相对`--project`且必须在项目内。

```powershell
python -X utf8 .agents/skills/nora-ai-short-drama/scripts/h3_prompt_checks.py --project "projects/项目名" --workflow "projects/项目名/执行附件/工作流.api.json" --mapping "projects/项目名/执行附件/输入映射.json" --basis-file "09-剧集制作/EP编号/02-本集剧本/本集剧本.md"
```

`--output`可指定一个尚不存在的JSON报告文件；默认只向标准输出报告，不改写任何输入或历史报告。`--basis-file`可重复，用于返回所选依据文件的指纹，不替Agent填写判断。退出码0表示确定性检查和证据绑定通过，1表示失败；查看`issues`及各`groups[].issues`。输出的`input_sha256`用于标识本次实际启用的公共区与原组输入（含正文、素材、时长和接续）；变化后须先核对再更新记录，不直接刷新指纹冒充检查。

既有`输入映射.json`中的`content_review`使用以下结构。每个选中原组一项，未选中组不纳入；`node`为字符串节点ID，`index`为从0开始的真实原组序。下例是字段说明，示例省略号不能提交。

```json
{
  "content_review": {
    "version": 1,
    "groups": [{
      "node": "实际导演台节点ID",
      "index": 0,
      "input_sha256": "离线检查返回的当前输入指纹",
      "subjects": {"1": "来源中的准确中文名称"},
      "chinese": {
        "file": "项目内既有提示词文档.md",
        "sha256": "当前中文正文指纹"
      },
      "checks": {
        "identity": {
          "status": "pending",
          "note": "实际检查范围、判断以及问题处理结果",
          "prompt_quote": "当前模型英文中的准确片段",
          "sources": [{"file": "上游依据的项目相对路径.md", "sha256": "依据指纹", "quote": "文件内实际原文"}]
        },
        "space_action": {"status": "pending", "note": "...", "prompt_quote": "...", "sources": []},
        "continuity_sound": {"status": "pending", "note": "...", "prompt_quote": "...", "sources": []},
        "translation": {"status": "pending", "note": "...", "prompt_quote": "...", "chinese_quote": "对应中文准确片段", "sources": []}
      }
    }]
  }
}
```

`subjects`覆盖所有已定义Subject，包括人物、场景、道具；来源名称不能根据模型译名反造。四类检查全部完成且有具体依据后才填写`passed`；`sources`引用相应采用剧本、分镜、资产或项目定位，不能引用核对记录自身作为证明。中文使用既有文档的“中文提示词参考版”text围栏；兼容已存在的冻结TXT，不为新任务另建中文正文。指纹按UTF-8解码、去BOM、统一换行为LF后的文本计算SHA-256；中文仅计算抽取后的正文并去除首尾空白。工具返回`chinese_sha256`；使用任务清单的新`content_review`注释方式时，工具自动填写这些既有指纹字段，不先运行离线检查取值再人工抄写。下方带指纹对象供已绑定映射及独立核对复用；独立检查仍可用`--basis-file`取得依据指纹，不能以刷新指纹代替实际核对。

确定性检查覆盖六节、Subject中文名称及引用、明确角色代称、全片无字幕指令、逐节中英文标签／镜号／数字对应，以及检查证据原文存在性、当前输入／中文／依据的绑定。空间合理性、动作可实现性、完整翻译语义和参考图身份本身不由正则或指纹证明；`three-quarter view`等正常镜头术语不作为禁词。`passed`、非空备注或摘录存在均不能替代Agent实际连读和推演。

新任务的提交条件与历史兼容只见[内容核对提交条件](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#内容核对的提交条件)。接口不提供跳过内容检查的参数，不自动修正文或制造通过结论。

回归命令（浏览服务目录）：

```powershell
.venv/Scripts/python.exe -X utf8 -B -m unittest tests.test_prompt_review tests.test_execution_checks tests.test_preparation_policy tests.test_submission_lifecycle -q
```

测试使用临时项目与模拟网络，覆盖英文违规、中文摘要、证据缺失、正文／依据变化、旧报告复用、新任务上传前停止及历史恢复，不生成视频。离线检查已有执行资料时使用独立新报告，不覆盖原执行检查报告。
