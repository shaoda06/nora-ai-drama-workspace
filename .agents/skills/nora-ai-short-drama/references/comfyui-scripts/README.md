# 通用 ComfyUI 执行工具

入口：[comfyui_client.py](comfyui_client.py)。Python 3.9+，仅标准库；安装位置属于短剧技能，代码不包含短剧业务。与 `comfyui-api` 技能结合使用：技能提供连接、接口与安全规则，脚本执行上传、提交、单轮查询、下载。节点／模型检查仍按 `comfyui-inventory`；故障按 `comfyui-troubleshooter`。

## 使用边界

- agent 按当前业务规范准备最终 **API 格式节点 JSON**、参考素材映射和全部参数；脚本不修改提示词、种子、节点或连线，不转换画布 JSON，不内置工作流模板。
- 上述四类已有能力必须复用此脚本，不按任务新写 Python／shell／内联 HTTP 实现。准备 API JSON、整理业务记录和审核仍由 agent 完成。发现脚本缺陷先报告并集中修复，缺少接口则明确缺口后处理，不悄悄回退成一套临时执行器。
- 只处理当前获得授权的任务；不启动下一阶段、不自动重试提交、不管理定时器、不操作队列删除／中断／卸载／服务器配置。
- 不决定项目路径、命名、审批或归档，不生成 `生成记录.md`，不移动候选至选定。图片由agent核对文件与执行记录后交用户审核，默认不调用看图能力或自动重试；批准后超分沿用对应专项规则。视频直接交人工审核。
- 四个命令相互独立。已有远端素材可以复用；新本地素材先上传，agent 再把返回路径写入 API JSON。接口验证／节点发现等不在四个命令内的只读操作仍可按对应技能执行。

## 调用

以下相对路径示例在本 README 所在目录执行；跨会话优先使用脚本绝对路径。每个命令的参数以 `python3 comfyui_client.py COMMAND --help` 为准。

所有命令支持 `--url`、`--timeout`、`--result`：

- `--url` 优先，其次 `COMFYUI_URL`；均未提供就报错。脚本没有默认服务器。agent 从当前任务或 `comfyui-api` 配置确定地址再传入，不自行改全局设置。
- `--timeout` 默认30秒，表示网络阻塞操作超时，不是整个生成任务的时限。大素材可按实际情况明确设置更长值；不自动重试 HTTP。禁止带凭据的 URL，不跟随 HTTP 重定向。
- `--result` 可指定一个**尚不存在**的 JSON 文件。调用前独占创建，避免网络操作成功后才发现目标冲突；异常结果也会保存。省略时仅写标准输出，agent负责留存。现有记录不可覆盖，每次查询可用新的快照文件或只读取标准输出。
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

未指定`--result`时查询仅返回标准输出，不新增文件；需要留存时可保存本次完整输出，无需再发一次查询。

先查指定history，非明确终态再核对queue。只返回本任务证据，不保存其他任务的提示词。状态为 `queued`、`running`、`success`、`failed`、`unknown`。`running`仅表示在运行队列，不证明采样步数正在推进；`success`须服务端明确completed与success且无错误／中断事件，**不等于业务要求的输出齐备或内容获批**。

`data.files`列出返回文件的node_id/output_key/index及原始文件信息；不替agent选择输出。agent核对本次预期节点及具体文件后再下载。原始任务history保留于返回JSON。网络故障是工具错误，不把任务标成失败。不自动等待、定时或启动下一阶段。

### download：明确指定文件

```sh
python3 comfyui_client.py download --url 'http://SERVER:8188' \
  --filename 'actual-file.mp4' --subfolder 'actual/subfolder' --type output \
  --output '/absolute/path/candidate.mp4' --result '/absolute/path/download-response.json'
```

三个远端字段来自上传响应或指定任务的输出。`--type`必须显式为input/output/temp；支持服务器返回的Windows子目录分隔符及Unicode、空格，按真实值URL编码。不得猜测文件名或替换成别的任务输出。

流式下载至目标同目录临时文件，核对HTTP长度（如提供）并计算SHA-256；可用 `--sha256` 核对已知传输哈希。完整后采用不可覆盖的原子发布；中断／失败清理本次临时文件，不留下伪装完成的目标。目标已有文件则拒绝，不自行替换、比较后采用或重命名。文件系统不支持原子硬链接时报告错误，不退回覆盖写入。

这些是传输完整性检查，不读取媒体内容、不调用ffprobe／ASR、不解码视频、不进行图片视觉审核。返回 `data.path/bytes/sha256/remote`；业务元数据及审批由agent维护。

## 回归测试与验证边界

纯函数／文件安全回归测试（不启动本地服务、不访问远端）：

```sh
python3 -B -m unittest discover -s '/absolute/path/comfyui-scripts' -p 'test_*.py' -v
```

覆盖请求不改写、大整数种子、重复提交、POST超时不重试、状态分类、不泄漏其他任务、半下载清理及并发落盘防覆盖。POST响应丢失和并发下载边界使用单元测试注入，不通过破坏远端制造故障。真实任务排队中／运行中状态、长时间网络中断、任意自定义节点和认证网关不据此宣称全部实测。

## Nora 项目配置与分享边界

Nora 流程先读取当前项目根目录的 `comfyui-config.json`，仅取 `remote-url` 并显式传入 `--url`。缺少时按技能入口询问用户，默认提议为 `http://127.0.0.1:8188`，不静默创建或使用其他项目地址。本工具作为通用客户端保留的环境变量能力不覆盖此项目规则。工具不管理服务端模型、节点和依赖。新记录使用执行机器本地时区及偏移；协议原始时间戳如实保存。

Nora执行附件的留存范围按[监控模板的精简留档规则](../模板/ComfyUI-任务监控提示词模板.md#执行附件精简留档)执行；普通查询与提交摘要不默认另存JSON。通用工具的可选`--result`接口及防重凭据保持原有用途。
