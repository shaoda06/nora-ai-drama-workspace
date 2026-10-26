---
name: nora-generation
description: 为 Nora 调用固定工具准备和提交图片视频任务、查询后台状态、接收结果、恢复异常及执行获授权后处理和导演包；只按当前动作读取，不重做已备内容。
---

# Nora 生成执行

直接调用遵循[主控读取范围](../nora-ai-short-drama/SKILL.md#读取范围)、[规则优先级](../nora-ai-short-drama/SKILL.md#外部技能协作与规则优先级)及[看图边界](../nora-ai-short-drama/SKILL.md#看图能力调用边界)。先区分当前动作，查询和结果通知不加载创作、完整提交准备或远端API技能。

## 按动作直达

实际图片生成或编辑先执行[统一分流与生成前确认](../nora-ai-short-drama/SKILL.md#当前参考图生成选型)，能力已明确的本批任务再进入下表；获批后超分不重新选择生图能力。

| 本次动作 | 必要入口 |
| --- | --- |
| 封面生成、采用后的规格处理 | [封面专项](../nora-drama-assets/references/封面资料与制作规范.md)；默认Imagegen、Qwen备用，登记类型为“封面”，后处理只为达到目标规格 |
| 社交媒体头像／主页背景图生成、结果保存及尺寸处理 | [社交图片生成与记录](../nora-social-visuals/references/生成与记录规范.md)；按本批选定能力进入对应执行分支，按该用途交接与记录，不冒充旧登记类型 |
| 已明确选用Imagegen生成／编辑 | [Imagegen子代理执行](references/Imagegen生成与尺寸处理规范.md#子代理执行与父代理交付)；主控准备，固定6 Luna／medium执行；收尾按图片用途进入固定脚本或社交专项，不装配为Qwen任务 |
| 已备内容的ComfyUI图片或超分提交 | [一次装配入队](../nora-ai-short-drama/references/comfyui-scripts/README.md#一次装配与批量入队)、[图片执行分工](references/ComfyUI-服务配置与任务提交规范.md#图片执行分工)；当前任务数据与授权 |
| 已备内容的视频提交 | 先按[整段生成与剪辑授权](references/视频阶段与返修执行规范.md#整段生成与剪辑授权)确定本次制作方式；已有任务的局部返修再读[执行快照与素材路径](references/ComfyUI-MiniMaxH3导演台节点使用规范.md#611-局部返修的执行快照与素材路径)并落实来源副本和素材绑定；标准版按[标准版配置选择](references/ComfyUI-H3视频执行规范.md#标准版四种配置与生成前询问)确定项目默认与本批覆盖后的实际配置，仅在该节规定的选择条件下询问四选一，再用同一装配工具及[视频执行分工](references/ComfyUI-服务配置与任务提交规范.md#视频执行分工)；不重新读节点全规范 |
| 首次完整准备图片分支 | [图片执行](references/图片生成执行规范.md)，先按已选能力分支；Qwen再根据T2I／Edit进入对应执行规则；内容缺项交资产或首帧负责人 |
| 首次完整准备H3任务或调整导演台 | [H3执行](references/H3视频执行规范.md)及其按阶段引用；内容核对交[视频提示词](../nora-video-prompts/SKILL.md) |
| 仅准备ComfyUI任务、不生成 | [准备分工](references/ComfyUI-服务配置与任务提交规范.md#执行前检查与复用)，固定入口使用--prepare-only |
| ComfyUI准备失败后修正输入 | 未登记清单进入[清单重新准备](../nora-ai-short-drama/references/comfyui-scripts/README.md#未登记清单的重新准备)；已有本地ID进入[原任务重新准备与恢复](references/ComfyUI-服务配置与任务提交规范.md#重新调度与失败恢复) |
| 仅查ComfyUI任务进度 | [查询分支](references/进度查询与结果处理规范.md#主动查询进度)，读取实际任务状态和更新时间 |
| 收到Imagegen子代理完成或失败报告 | [父代理交付与异常处理](references/Imagegen生成与尺寸处理规范.md#子代理执行与父代理交付)，复用对应固定脚本报告或社交专项的执行结果，不进入ComfyUI通知分支 |
| 收到ComfyUI正常图片或超分结果 | [图片结果](references/进度查询与结果处理规范.md#正常图片结果)，沿[图片批次通知与超分静默](references/ComfyUI-任务监控规范.md#图片批次通知与超分静默)处理，普通图片读report后集中展示；正常超分静默 |
| 收到正常视频结果 | [视频结果处理](references/进度查询与结果处理规范.md#正常视频结果) |
| ComfyUI异常、取回失败或恢复 | [异常分支](references/进度查询与结果处理规范.md#异常与恢复)，定位失败阶段后读对应证据；仅取回失败使用取回重试 |
| 已批准图片超分和正式保存 | [图片批准后处理](references/图片批准后处理规范.md)及其专项；画风样例沿定位规则 |
| 视频采用收尾 | 按[采用记录与依据](../nora-ai-short-drama/references/流程规范/逐集目录与资产管理规范.md#视频采用记录与批准依据)确定对象，使用[一次收尾工具](../nora-ai-short-drama/references/comfyui-scripts/README.md#视频批准的一次收尾)；报告确认本集制作完成时接续[完集复盘](../nora-ai-short-drama/references/流程规范/逐集目录与资产管理规范.md#完集复盘与经验维护) |
| 视频阶段切换、返修或后处理 | 局部返修先落实[执行快照与素材路径](references/ComfyUI-MiniMaxH3导演台节点使用规范.md#611-局部返修的执行快照与素材路径)；再按[阶段与返修执行](references/视频阶段与返修执行规范.md)、[H3执行规范](references/ComfyUI-H3视频执行规范.md)的当前阶段；一采返修同时按[种子策略](references/ComfyUI-H3视频执行规范.md#场次基准种子与实际任务种子)判断是否主动建议换种子；平台要求、推荐值与选定值分别记录 |
| 导演包或场次阶段定稿 | [导演包](references/导演包规范.md)，按实际授权区分留档、导出与导入测试 |
| 服务节点配置 | [工作区配置](references/ComfyUI-服务配置与任务提交规范.md#工作区-comfyui-配置)，不因纯文本任务缺配置而阻塞 |

实际生成使用了表情参考写法时，复用提示词阶段已有告知；尚未告知的首次实际使用，按[首次使用提示](../facial-expression/SKILL.md#首次实际使用时的提示)简短补充，不新增确认。用户提供具体表情反馈后，进入[反馈复核](../facial-expression/SKILL.md#收到真实反馈后复核)，更新对应条目的验证情况；正常结果通知不触发自动审片或提前标记有效。

实际生成采用镜头候选写法或技巧组合时，复用提示词阶段已有告知，缺少时按[镜头使用与反馈](../camera-language/SKILL.md#实际使用与反馈复核)补充。用户提供针对性镜头反馈后沿该入口更新指南；下载成功或整体采用不自动验证运镜、构图或焦点，也不触发额外查看或生成。

## 工具与依赖

准备、提交或获授权直接操作远端API时，读取随包[comfyui-api](../nora-ai-short-drama/dependencies/comfyui-api/SKILL.md)及当前调用说明；普通后台查询和通知不需要它。异常按需使用[comfyui-troubleshooter](../nora-ai-short-drama/dependencies/comfyui-troubleshooter/SKILL.md)，明确要求能力盘点或依赖诊断时才使用[comfyui-inventory](../nora-ai-short-drama/dependencies/comfyui-inventory/SKILL.md)。沿现有真源，不另复制安装。

标准版视频生成前按[四种配置与生成前询问](references/ComfyUI-H3视频执行规范.md#标准版四种配置与生成前询问)取得本次配置与画幅，沿该节选择LoRA、采样与尺寸参数及超分／裁切后处理分支；需要询问时使用该节规定的完整选项及推荐标记；已有项目默认或本批选择时按该节直接沿用。

Imagegen原生生成与编辑由固定执行子代理调用内置工具，保存与交付职责见[Imagegen分支](references/Imagegen生成与尺寸处理规范.md#子代理执行与父代理交付)；主控接收报告后交付，不重复收尾。以下API装配、入队和后台收尾适用于ComfyUI任务。

Agent确定内容、实际素材用途、必要业务字段及授权；固定工具装配API／画布、映射、技术记录并检查入队。默认一次--plan完成装配检查与入队，只有单独准备才加--prepare-only；技术报告不能代替内容判断。规范与调用接口详见[职责分工](references/ComfyUI-服务配置与任务提交规范.md#agent与工具的职责)。

返回enqueued及本批ID后简要汇报提交数量并结束；后台负责上传、远端提交、取回、技术收尾和网页核验。收到正常结果先按[整轮汇总规则](references/ComfyUI-任务监控规范.md#3-跟进与通知)判断交付时机，再进入上表对应分支；异常沿原身份恢复，不整批重提，不创建同任务轮询或heartbeat。

本技能不决定故事、机位、画风、素材批准或下一阶段授权。接续已备提示词时按[提示词自检与执行授权](../nora-ai-short-drama/references/共用规则/主控操作规范.md#提示词自检与执行授权)核对真实待决项，不从准备文档的通用确认字段推导额外审批。采用与本集完成时按[逐集目录与采用规则](../nora-ai-short-drama/references/流程规范/逐集目录与资产管理规范.md)定位对应章节；视频任务形成／引用场次组合时读取[场次版本组合](../nora-ai-short-drama/references/共用规则/场次版本组合规范.md)。固定脚本的日常调用边界见[工具调用](../nora-ai-short-drama/SKILL.md#固定脚本调用)。
