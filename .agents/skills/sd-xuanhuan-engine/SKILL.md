---
name: sd-xuanhuan-engine
description: 为 Nora 的修仙、仙侠、法术对轰、剑阵法相与大场面提供动作编排、双向受力、特效材质和尺度方法。
---

# Nora 玄幻打戏专项

## Nora 接入与阶段边界

本技能提供专项动作与视听设计，由[剧本写作](../short-drama-write/SKILL.md)或[分镜设计](../short-drama-storyboard/SKILL.md)按任务调用。只写剧情时读取构思、动作因果及必要招式方法；设计镜头时再读取相关摄影、空间与节奏章节。直接调用也沿Nora当前项目、批准依据和交付规则。

方法落实到当前剧本、SH镜头和P段，不创建另一套记录。故事与对白由写作负责，镜头和分段由分镜负责，[视频提示词](../nora-video-prompts/SKILL.md)按实际模型格式转写，[生成执行](../nora-generation/SKILL.md)调用固定工具。参考库中的short-drama-director、validate_prompt.py、图N、固定整秒、默认反杀、输出封装和机检门仅属于原套装上下文，不构成Nora的格式、权限或必须剧情；适用模型的真实限制仍须执行。

镜头与节奏统一按[场次分镜选择方法](../short-drama-storyboard/references/场次分镜制作规范.md#运镜构图与切镜的选择)落到正文并自检。专项库和案例中的秒数、镜数、交替组合或拍法禁令不作通用门槛；固定、重复构图、慢镜、特写、正反打与长镜均按实际表达判断。修改须指出具体信息、表演、空间或节奏损失，不为变化强制切镜或加运镜。

优先级遵循[Nora主控](../nora-ai-short-drama/SKILL.md#外部技能协作与规则优先级)。各规则中的强度、镜数、贴身比例、静止或手绘化建议须连同档位、适用条件及不适用情形读取，不把某档或个案结论扩大到全部题材和模型。保留可用方法；具体冲突按当前项目处理，不凭措辞绝对就否定，也不自动将其升为通用硬限制。完整制作按下列流程读取必要方法，局部问题按表定位；不默认通读铁律全表或其他两种专项。

## 完整制作与局部修改

先确定本次是剧本动作设计、场次分镜，还是已确认动作的提示词转写。首次完整制作一场打戏或大幅重排攻防时，按下列顺序完成本阶段适用部分；已读且未变的方法复用。只写剧本时落实人物目的、动作因果、状态和结果，摄影与模型转译留到对应阶段。分镜设计落实到现有SH镜头和P段，覆盖来源剧本中的动作、对白与声音。选镜与安排时长前，读取[力度与节奏默认建议](../sd-combat-engine/references/combat-intensity-guardrails.md)及[动作负荷与可读性](../sd-combat-engine/references/combat-rhythm-and-load-guardrails.md)的适用部分，用于起稿；自检再回到已写的动作、受力、构图和时长核对，不以“拍法自由”跳过检查。

1. **明确依据与战斗规模**：核对已确认剧情目的、胜负走向、角色与法器、开场状态、空间、画风及本场适用强度；R3方法只用于对应规模，不把所有仙侠场面都做成最高强度。动机、强弱、赌注或环境作用尚未落实时，直读[打斗构思](../sd-combat-engine/references/combat-construction.md)相应部分。
2. **编排双向攻防**：读[核心法则](references/core-combat-laws.md)第二、四、五节，按动作节拍拆出攻击、防守或闪避、接触及实际反馈，用八步写作法明确每拍的作用和衔接。法术被躲开也须交代去向；防守方的抵抗及状态变化有具体过程。攻守次数、默认反杀及固定整秒不替代已确认剧情和Nora分镜时长。涉及近身拆招时再读[近战方法](references/close-quarters-engine.md)。
3. **落实材质、尺度与摄影**：涉及法术和能量表现时读[xuanhuan-elements-vfx](references/xuanhuan-elements-vfx.md)，写清形态、来源、路径、碰撞和环境作用；剑阵、法相、巨兽或宏观战场补[尺度方法](references/grand-scale-domains.md)。分镜阶段同时落实核心法则第一节的节奏、镜头和情绪方法，结合本段实际长度与已确认剧情适配；读[camera-specs-15modes](references/camera-specs-15modes.md)的适用机位与空间要求，按实际需求补群战、武器变化或一镜到底规则。新法术造型、招式及参数按下表选取，不把候选当成项目已采用设定。
4. **收束与合并自检**：先按已确认结局选择方法：需要交代败者或残局时，读核心法则第三节的适用协议；需要双人错身远离或单人冲镜的打斗硬切时，读协议D对应解法。已有结尾与这些协议均不匹配时，直接保留已确认的收尾动作和切点，核对人物位置、法器去向、能量及残留物状态、动作时序和必要的下一镜起点，完成空间与状态接续；不为套用协议补造胜负、受击、残局或改换收尾动作。只有已确认反杀或大招才读第八节对应方法。检查动作颗粒度、双方受力、尺度参照、镜头可读性及核心法则第七节适用打磨项；分镜阶段直读通用[节奏负载](../sd-combat-engine/references/combat-rhythm-and-load-guardrails.md)与[力度与节奏参考](../sd-combat-engine/references/combat-intensity-guardrails.md)的适用条件，涉及特效笔法时补[介质分层](../sd-combat-engine/references/vfx-rendering-mandate.md)。与负责业务的自检合并订正。

**局部修订**：保留已成立的构思和未受影响设计，按下表定位本次动作、受力、摄影或特效问题，只补读对应方法及必要的前后状态；修改牵动整场攻防或空间结构时，覆盖受影响的完整链条。只改错字、格式不重新做动作设计。仅转写已确认分镜时由视频提示词技能沿既有动作与素材映射完成，缺少动作依据才回本专项定位补齐，不重做整场。

## 按任务选择规则

| 当前问题 | 方法文件 |
| --- | --- |
| 攻防、颗粒度与收束方法，按当前问题选段 | [core-combat-laws](references/core-combat-laws.md) |
| 机位、运镜与空间 | [camera-specs-15modes](references/camera-specs-15modes.md) |
| 近身连续拆招 | [close-quarters-engine](references/close-quarters-engine.md) |
| 元素、材质与能量形态 | [xuanhuan-elements-vfx](references/xuanhuan-elements-vfx.md) |
| 剑阵、法相、巨兽与宏观尺度 | [grand-scale-domains](references/grand-scale-domains.md) |
| 具体法武招式 | [arsenal-moves-library](references/arsenal-moves-library.md) |
| 写实与修仙参数对照 | [arsenal-parameter-library](references/arsenal-parameter-library.md) |
| 角色、场景与风格候选 | [character-scene-presets](references/character-scene-presets.md) |
| 群战、武器变化和一镜到底 | [epic-battlefield-protocols](references/epic-battlefield-protocols.md) |
| 法术外观及环境作用的补充候选 | [仙侠法术与特效造型参考库](references/仙侠法术与特效造型参考库.md) |

跨专项需要节奏负载或激烈度判断时，直接选读[节奏与负载](../sd-combat-engine/references/combat-rhythm-and-load-guardrails.md)或[力度与节奏参考](../sd-combat-engine/references/combat-intensity-guardrails.md)的当前档位；需要特效笔法时读[介质与分层](../sd-combat-engine/references/vfx-rendering-mandate.md)。不因跨专项引用再加载通用技能的全部方法。

## 交付

把方法落实到本次获授权正文，由负责业务技能合并自检；只提出确实影响当前任务的缺项。素材查看、自动重试、模型切换、生成及采用沿主控边界，专项设计本身不授予这些权限。
