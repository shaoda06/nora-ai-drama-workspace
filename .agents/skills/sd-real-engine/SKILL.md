---
name: sd-real-engine
description: 为 Nora 的写实格斗、警匪追逐、动作喜剧及小规模多人战斗提供步法、防守、动力链和真实受力方法。
---

# Nora 写实格斗专项

## Nora 接入与阶段边界

本技能提供专项动作与视听设计，由[剧本写作](../short-drama-write/SKILL.md)或[分镜设计](../short-drama-storyboard/SKILL.md)按任务调用。只写剧情时读取构思、动作因果及必要招式方法；设计镜头时再读取相关摄影、空间与节奏章节。直接调用也沿Nora当前项目、批准依据和交付规则。

方法落实到当前剧本、SH镜头和P段，不创建另一套记录。故事与对白由写作负责，镜头和分段由分镜负责，[视频提示词](../nora-video-prompts/SKILL.md)按实际模型格式转写，[生成执行](../nora-generation/SKILL.md)调用固定工具。参考库中的short-drama-director、validate_prompt.py、图N、固定整秒、默认反杀、输出封装和机检门仅属于原套装上下文，不构成Nora的格式、权限或必须剧情；适用模型的真实限制仍须执行。

镜头与节奏统一按[场次分镜选择方法](../short-drama-storyboard/references/场次分镜制作规范.md#运镜构图与切镜的选择)落到正文并自检。专项库和案例中的秒数、镜数、交替组合或拍法禁令不作通用门槛；固定、重复构图、慢镜、特写、正反打与长镜均按实际表达判断。修改须指出具体信息、表演、空间或节奏损失，不为变化强制切镜或加运镜。

优先级遵循[Nora主控](../nora-ai-short-drama/SKILL.md#外部技能协作与规则优先级)。各规则中的强度、镜数、贴身比例、静止或手绘化建议须连同档位、适用条件及不适用情形读取，不把某档或个案结论扩大到全部题材和模型。保留可用方法；具体冲突按当前项目处理，不凭措辞绝对就否定，也不自动将其升为通用硬限制。完整制作按下列流程读取必要方法，局部问题按表定位；不默认通读铁律全表或其他两种专项。

## 完整制作与局部修改

先确定本次是剧本动作设计、场次分镜，还是已确认动作的提示词转写。首次完整制作一场打戏或大幅重排攻防时，按下列顺序完成本阶段适用部分；已读且未变的方法复用。只写剧本时落实人物目的、动作因果、状态和结果，摄影与模型转译留到对应阶段。分镜设计落实到现有SH镜头和P段，覆盖来源剧本中的动作、对白与声音。选镜与安排时长前，读取[力度与节奏默认建议](../sd-combat-engine/references/combat-intensity-guardrails.md)及[动作负荷与可读性](../sd-combat-engine/references/combat-rhythm-and-load-guardrails.md)的适用部分，用于起稿；自检再回到已写的动作、受力、构图和时长核对，不以“拍法自由”跳过检查。

1. **明确依据与写实档位**：核对剧情目的、人物能力、武器持握、开场距离、站位、伤损、环境和风格。读[R1核心](references/r1-combat-core.md)的定位、节拍弧、开局、收尾与招式库从属要求；只有符合对应场景的节奏、情绪和收束方法才采用，不把案例时点套到所有场面。
2. **编排攻防动作**：读[动力链](references/kinetic-chain-11.md)和[基本技法](references/real-fight-techniques.md)，关键打击推导完整发力链，正文压缩到可读要件；过渡动作交代起势、接触与状态即可。结合[防守与闪避](references/defense-evasion-rules.md)写出抵抗、失衡、卸力或反应，不让对手只被动平移；受力不明确时补[impact-physics](references/impact-physics.md)。
3. **落实空间与镜头**：分镜阶段读[camera-action-specs](references/camera-action-specs.md)，让关键接触、步法、重心及防守变化看得清，镜长服从实际动作。用户点名武学或要求细化具体技法时读对应[martial-styles-extended](references/martial-styles-extended.md)；连招需要读[technique-combo-library](references/technique-combo-library.md)，多人战斗读[multi-opponent-rules](references/multi-opponent-rules.md)。执行R1核心“取神不取形”：采用技法的发力方向和接触反馈，不整套照搬招式顺序或箭头串。
4. **合并检查与转写交接**：按R1核心启发式自检和当前使用方法，核对攻防因果、受力、步法、状态接续及节拍变化；分镜阶段直读通用[节奏负载](../sd-combat-engine/references/combat-rhythm-and-load-guardrails.md)与[力度与节奏参考](../sd-combat-engine/references/combat-intensity-guardrails.md)中的R1适用条件，不套R3爆炸强度。只在明确转写Seedance时读[render-adapters](references/render-adapters.md)，其他模型由视频提示词技能转写。订正并入本次业务自检，不新增复验报告。

**局部修订**：保留已成立的构思和未受影响设计，按下表定位本次动作、受力、摄影或特效问题，只补读对应方法及必要的前后状态；修改牵动整场攻防或空间结构时，覆盖受影响的完整链条。只改错字、格式不重新做动作设计。仅转写已确认分镜时由视频提示词技能沿既有动作与素材映射完成，缺少动作依据才回本专项定位补齐，不重做整场。

## 按任务选择规则

| 当前问题 | 方法文件 |
| --- | --- |
| 写实定档、节拍与收束 | [r1-combat-core](references/r1-combat-core.md) |
| 关键打击的动力链 | [kinetic-chain-11](references/kinetic-chain-11.md) |
| 基本招式选择 | [real-fight-techniques](references/real-fight-techniques.md) |
| 镜头、空间与景别 | [camera-action-specs](references/camera-action-specs.md) |
| 防守、闪避及受击 | [defense-evasion-rules](references/defense-evasion-rules.md) |
| 受力与环境反馈 | [impact-physics](references/impact-physics.md) |
| 用户点名武学或需要具体技法 | [martial-styles-extended](references/martial-styles-extended.md) |
| 连招、踢击部位、情绪拐点及化劲 | [technique-combo-library](references/technique-combo-library.md) |
| 多人调度 | [multi-opponent-rules](references/multi-opponent-rules.md) |
| 明确采用Seedance时的封装参考 | [render-adapters](references/render-adapters.md) |
| 需要完整范例 | [storyboard-example](references/storyboard-example.md) |

跨专项需要节奏负载或激烈度判断时，直接选读[节奏与负载](../sd-combat-engine/references/combat-rhythm-and-load-guardrails.md)或[力度与节奏参考](../sd-combat-engine/references/combat-intensity-guardrails.md)的当前档位；需要特效笔法时读[介质与分层](../sd-combat-engine/references/vfx-rendering-mandate.md)。不因跨专项引用再加载通用技能的全部方法。

## 交付

把方法落实到本次获授权正文，由负责业务技能合并自检；只提出确实影响当前任务的缺项。素材查看、自动重试、模型切换、生成及采用沿主控边界，专项设计本身不授予这些权限。
