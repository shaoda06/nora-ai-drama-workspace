# ComfyUI API 速查

可移植适配日期：2026-09-26。原始结构来自 [ComfyUI-Expert](https://github.com/MCKRUZ/ComfyUI-Expert/blob/dee27dc3d69b609c0006a8a12e71aadfc475ae95/foundation/api-quick-ref.md)，接口依据 [ComfyUI 官方路由说明](https://docs.comfy.org/development/comfyui-server/comms_routes) 和 [消息说明](https://docs.comfy.org/development/comfyui-server/comms_messages)。

地址优先级：当前任务明确地址 → `COMFYUI_URL` → `http://127.0.0.1:8188`。调用方使用项目配置时须显式传入地址；本技能不约定项目配置文件布局。`127.0.0.1` 指运行客户端的机器。请求超时默认30秒；任务运行时间与单次HTTP请求超时分开处理。

| 方法与路径 | 用途 |
| --- | --- |
| GET `/system_stats` | 系统、版本和显存快照 |
| GET `/object_info` 或 `/object_info/{class}` | 注册节点及输入输出定义 |
| GET `/models` | 当前服务器支持的模型分类 |
| GET `/models/{category}` | 对应分类可见文件，分类名先从 `/models` 获取 |
| GET `/queue` | 排队与正在执行的任务 |
| POST `/prompt` | 提交 API 格式工作流，请求体为 `{"prompt": {...}, "client_id": "本次唯一ID"}` |
| GET `/history/{prompt_id}` | 指定任务的状态、消息和输出 |
| GET `/history` | 必要时排查提交结果不明的任务；避免无目的读取所有历史 |
| GET `/view` | 按 `filename`、`subfolder`、`type` 获取输出 |
| POST `/upload/image` | multipart上传参考图；使用响应中的实际名称与子目录配置工作流 |
| GET `/userdata` | 列出保存的工作流等用户文件 |
| GET `/userdata/{file}` | 读取保存的文件，路径正确URL编码 |
| WS `/ws?clientId=...` | 使用与提交相同的client ID监听进度；收到单节点输出不表示整个任务完成 |

POST `/prompt` 成功后保存 `prompt_id`；拒绝时检查 `error` 和 `node_errors`。API执行图是由节点ID索引的对象，不是带画布布局的UI导出文件。

## 执行与恢复

1. 保存本次请求、唯一client ID、提示词、参数及预期输出；从基准创建副本，不回写远端保存的工作流。
2. 提交一次请求。响应丢失先查队列和历史，不能按“超时就重试POST”处理。
3. 独立使用默认每5秒GET指定任务历史；任务或调用方已明确监控策略时按其间隔与方式执行，不额外启动轮询。空历史结合队列判断，不能认定完成。核对 `status.completed`、`status.status_str` 及错误/中断消息；成功还需预期保存节点有输出。
4. 下载时对文件名、子目录、类型分别URL编码，保留服务端返回值。下载到临时文件，成功后检查真实格式和尺寸，再保存到目标路径。
5. 将输入、响应、历史、输出路径和验收结论保存在任务目录。耗时超过预期时报告实际状态，保留可恢复的任务编号。

服务器支持WebSocket；默认REST方式不依赖额外WebSocket库，REST轮询是默认实现方式，并非CLI不支持WebSocket。

## 会影响服务状态的接口

- POST `/interrupt`：中断正在执行的工作流，不能当作只取消自己任务的通用方法。
- POST `/queue`：可删除指定待运行任务或清空队列；核实目标与授权，不能清除无关任务。
- POST `/free`：卸载模型/释放内存，可能影响共享服务；不作为只读检查的一部分。
- POST `/userdata/{file}`：保存/覆盖远端文件；执行临时工作流不需要调用。

按名称发现实际安装的 `comfyui-inventory`，读取其缓存位置与更新方法；不假定同级安装目录，不随技能分发缓存。
