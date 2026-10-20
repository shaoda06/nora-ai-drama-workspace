# ComfyUI-文生图执行规范

状态：现行执行规范。\
版本：v1.48。更新日期：2026-10-20。

适用于无参考图片的Qwen Image 2.1文生图。生成方式及正文按[图片类型索引](../../nora-drama-assets/references/Qwen-Image-2.1-提示词规范.md#11-图片类型专用模板索引)选择，接收`rewritten_prompt`与`wh_ratio`，不重新优化已备正文。带实际参考图时使用[图生图执行规范](ComfyUI-图生图执行规范.md)。

## 1. 输入与工作流文件

| 文件 | 用途 |
| --- | --- |
| [原始画布](../../nora-ai-short-drama/references/comfyui-workflow/Qwen-image-2-1/Qwen2.1-文生图-普通版.workflow.json) | 用户提供文件的原样副本，仅保存在规定的workflow目录，不修改内容，不生成修改过的任务画布 |
| [API执行版](../../nora-ai-short-drama/references/comfyui-workflow/Qwen-image-2-1/Qwen2.1-文生图-普通版.api.json) | Agent执行用基准；每个任务复制后填写本节允许的参数，实际副本保存到项目执行附件 |

API基准含占位正文及输出前缀，不可直接提交。画布保留原有文字、布局、节点及控件；API独立维护，不要求与画布逐项相等，不执行配对、一致性或差异比较。用户更新画布时，由用户与Agent共同调整执行API和调用说明。

### 共用模型组合

文生图与图生图共用主模型`qwen_image_2.1_int8_convrot.safetensors`、编码器`qwen3vl_8b_bf16.safetensors`、VAE `qwen_image_2.1_vae_bf16.safetensors`。用户未明确调整时保持。普通任务不查询远端节点／模型库存；执行条件由远端实际响应确定，异常按[服务规范](ComfyUI-服务配置与任务提交规范.md#远端能力与错误返回)处理。

## 2. 提示词与参数映射

API有效链包含10个节点。文本节点672接编码器522；主模型523经TE加速653接采样器515；空latent 514提供输出画布；520解码后由508保存PNG。旁路增强器、文字显示和LoRA不进入API；界面按钮与装饰标签不进入请求。尺寸选择器512和随机种子节点524不进入API，宽高及种子直接使用明确数值。此转换不回写原始画布。

| 参数 | API位置 | 允许操作 |
| --- | --- | --- |
| 最终正向正文 | `672.inputs.value` | 每任务填`rewritten_prompt`，不把整个JSON送入模型 |
| 宽、高 | `514.inputs.width`、`height` | 每任务填对应图片类型既定送审尺寸；均为32倍数 |
| 种子 | `515.inputs.seed` | 每任务填[项目类别种子规则](../../nora-drama-assets/references/Qwen-Image-2.1-提示词规范.md#26-项目七类图片默认种子)确定的整数，不使用-1随机标记 |
| 输出前缀 | `508.inputs.filename_prefix` | 每任务按[远端输出目录](ComfyUI-服务配置与任务提交规范.md#远端输出目录与命名)填写，不加扩展名 |
| 反向提示词 | `522.inputs.negative_prompt` | 默认空；本次已明确需要时通过`parameters.negative_prompt`填写并记录 |
| 图片数量 | `514.inputs.batch_size` | 固定1；多候选使用独立任务，仍按种子规则执行 |
| 参考预处理 | `522.inputs.resolution` | 保留0；本工作流没有参考图输入 |
| 采样 | `515.inputs` | 固定`steps=40`、`cfg=1`、`sampler_name=euler`、`scheduler=simple`、`denoise=1` |
| TE加速 | `653.inputs` | 固定`attention=kitchen_int8`、`step_cache=te_predictor`、`reuse_threshold=0.06`、`start_percent=0`、`end_percent=0`、`predictor_error_limit=0.08`、`verbose=true` |
| 输出 | 节点508，`images`第0项 | 1张PNG；按真实返回的filename/subfolder/type取回 |

模型组合、连接、节点类型、采样和加速参数均为固定执行配置，日常任务不自行修改。需要改变时先取得具体配置变更授权，再维护API与说明；不借`parameters`覆盖固定值，不自动启用提示词增强器或4步LoRA。CFG为1时反向条件不发挥常规引导作用。

## 3. 分辨率设置

`wh_ratio`使用明确宽高的最简整数比；它是任务元数据，不直接添加到节点输入。画布原文件中的16:9和2.2 megapixels不决定API任务尺寸。

| 用途 | 送审尺寸与比例的规则入口 |
| --- | --- |
| 人物上半身正面肖像、服装正背面图 | [人物专项规则](../../nora-drama-assets/references/人物参考图制作与记录规范.md#2-规格背景与布局) |
| 定位画风样例 | [定位画风验证流程](../../short-drama-develop/references/项目定位与画风规范.md#项目画风展开示例验证与复用) |
| 道具三视图、虚拟道具基础界面 | [道具规则](../../nora-drama-assets/references/道具资料与参考图规范.md#3-三视图与状态规则) |
| 场景图 | [场景规格](../../nora-drama-assets/references/场景资料与参考图规范.md#41-画面要求) |
| 剧集专用参考图 | [集内素材规则](../../nora-ai-short-drama/references/流程规范/逐集目录与资产管理规范.md#21-剧集专用参考图) |

上述图片尺寸、生成方式和批准后处理不因工作流替换而改变。[图片超分规范](ComfyUI-图片超分执行规范.md)仍独立执行。实际输出尺寸由后台取回时核对，不能用目标参数冒充真实尺寸。

## 4. 执行流程

使用[任务清单入口](../../nora-ai-short-drama/references/comfyui-scripts/README.md#一次装配与批量入队)，不手工制作重复的技术附件。Python 3.9及以上；路径以实际技能和项目位置为准。

```sh
python /实际技能目录/scripts/comfyui_dispatch.py \
  --project /实际项目目录 \
  --plan 03-人物资料/其他资料/执行附件/肖像制作/任务清单.json \
  --prepare-only
```

示意任务清单（正文必须替换为实际已完成内容核对的文本）：

```json
{"tasks":[{
  "task_type":"image","object":"CH001","title":"CH001 · 肖像",
  "kind":"人物","image_type":"人物上半身正面肖像图","state":"成年",
  "draft":"03-人物资料/其他资料/工作稿/CH001-参考图-工作稿.md",
  "authorization":"本次真实的生成授权","basis":"当前已确认人物资料",
  "prompt":{"rewritten_prompt":"这里填写已核对的完整中文正文","wh_ratio":"1:1"}
}]}
```

`--prepare-only`只在本地生成API、素材／成果映射、收尾计划和执行记录并检查本次参数，不入队、不上传、不生成；不修改原画布或复制任务画布。已有生成授权且准备完成后，使用相同命令去掉`--prepare-only`入队。输出成功须为prepared或enqueued；失败按报告具体缺项处理，不自动重发生成。

工具自动填写类别种子、原定尺寸、输出目录及实际模型／采样／加速参数。普通图片清单没有参考图时选择本API；需要图片输入时使用图生图分支。基准只读，项目记录保留真实API、请求、任务身份及响应。

## 5. 检查与验收

日常准备只执行任务参数、API基本结构、输入／输出身份及既有审批关联等必要检查，不比较原画布与API。提交和结果职责按[图片执行分工](ComfyUI-服务配置与任务提交规范.md#图片执行分工)。

后台完成取回、真实尺寸／格式核对及候选记录后通知；Agent读取report并展示delivery，画面由用户审核。正常结果不重复技术核对、不自动看图或重试。维护API或脚本时运行受影响的API与任务装配测试，不以离线通过声称远端已执行成功。

## 本地配套基准

地址读取[工作区配置规则](ComfyUI-服务配置与任务提交规范.md#工作区-comfyui-配置)；原画布与API的维护边界读取[维护规范](../../nora-ai-short-drama/维护规范.md#工作流基准与任务副本)。图生图和视频后续工作流替换需分别落实，不因本文改变其现行生成配置。
