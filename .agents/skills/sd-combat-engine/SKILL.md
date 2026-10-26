---
name: sd-combat-engine
description: 为 Nora 的武侠和动作场面提供构思、攻防因果、力量反馈、摄影与节奏方法；玄幻和写实专门问题按需进入对应专项。
---

# Nora 通用打戏专项

## Nora 接入与阶段边界

本技能提供专项动作与视听设计，由[剧本写作](../short-drama-write/SKILL.md)或[分镜设计](../short-drama-storyboard/SKILL.md)按任务调用。只写剧情时读取构思、动作因果及必要招式方法；设计镜头时再读取相关摄影、空间与节奏章节。直接调用也沿Nora当前项目、批准依据和交付规则。

方法落实到当前剧本、SH镜头和P段，不创建另一套记录。故事与对白由写作负责，镜头和分段由分镜负责，[视频提示词](../nora-video-prompts/SKILL.md)按实际模型格式转写，[生成执行](../nora-generation/SKILL.md)调用固定工具。参考库中的short-drama-director、validate_prompt.py、图N、固定整秒、默认反杀、输出封装和机检门仅属于原套装上下文，不构成Nora的格式、权限或必须剧情；适用模型的真实限制仍须执行。

镜头与节奏统一按[场次分镜选择方法](../short-drama-storyboard/references/场次分镜制作规范.md#运镜构图与切镜的选择)落到正文并自检。专项库和案例中的秒数、镜数、交替组合或拍法禁令不作通用门槛；固定、重复构图、慢镜、特写、正反打与长镜均按实际表达判断。修改须指出具体信息、表演、空间或节奏损失，不为变化强制切镜或加运镜。

选用通用、写实或玄幻方法及处理冲突时，先按[Nora打戏方法的适用范围与优先级](../nora-ai-short-drama/SKILL.md#打戏方法的适用范围与优先级)判断；该处统一维护范围和优先关系。各规则中的强度、镜数、贴身比例、静止或手绘化建议须连同档位、适用条件及不适用情形读取，不把某档或个案结论扩大到全部题材和模型。保留可用方法；具体冲突按当前项目处理，不凭措辞绝对就否定，也不自动将其升为通用硬限制。完整制作按下列流程读取必要方法，局部问题按表定位；不默认通读铁律全表或其他两种专项。

## 完整制作与局部修改

先确定本次是剧本动作设计、场次分镜，还是已确认动作的提示词转写。首次完整制作一场打戏或大幅重排攻防时，按下列顺序完成本阶段适用部分；已读且未变的方法复用。只写剧本时落实人物目的、动作因果、状态和结果，摄影与模型转译留到对应阶段。分镜设计落实到现有SH镜头和P段，覆盖来源剧本中的动作、对白与声音。选镜与安排时长前，读取[力度与节奏默认建议](references/combat-intensity-guardrails.md)及[动作负荷与可读性](references/combat-rhythm-and-load-guardrails.md)的适用部分，用于起稿；自检再回到已写的动作、受力、构图和时长核对，不以“拍法自由”跳过检查。

1. **明确依据与构思**：核对已确认的剧情目的、人物强弱、开场位置、朝向轴线、持物、伤损、环境和画风。读[打斗构思](references/combat-construction.md)，确定动机、赌注、环境作用及起承危破收的实际变化；按[强度定档](references/tier-and-finisher-system.md)选本场适用档位，不为套节奏改写已确认剧情。
2. **编排动作与镜头**：读[核心铁律](references/combat-iron-laws.md)的铁律0八步链，按“全局视听选择→本镜任务→机位→身体发力链→特效材质及生命周期→接触、受击与环境反馈→运镜因果→转场节律及反向核对”逐步落实。分镜阶段同时落实铁律2的独立画面、7的运镜动机及11的反馈链；具体招式、终结技、群战或法术再从下表取相应方法。
3. **写成可见动作**：分镜阶段读[自然句母版](references/eight-sentence-masters.md)，将实际用到的动作、释放、命中、位移、尺度与收势写入Nora对应字段；不用招式名或抽象强度词代替过程。需要句法案例时再读syntax-corpus；明确转写Seedance时才进入其模型适配，其他模型由视频提示词技能处理。
4. **合并检查并订正**：用自然句母版的“出稿前每镜自问清单”、核心铁律45的重复与变化判断及构思文件的避坑清单，检查因果、状态、反馈和整场是否重复平推。分镜阶段按本场档位读取[节奏负载](references/combat-rhythm-and-load-guardrails.md)与[力度与节奏参考](references/combat-intensity-guardrails.md)的适用部分；涉及特效时补[介质与分层](references/vfx-rendering-mandate.md)。问题随当前业务的交付自检一并订正。

**局部修订**：保留已成立的构思和未受影响设计，按下表定位本次动作、受力、摄影或特效问题，只补读对应方法及必要的前后状态；修改牵动整场攻防或空间结构时，覆盖受影响的完整链条。只改错字、格式不重新做动作设计。仅转写已确认分镜时由视频提示词技能沿既有动作与素材映射完成，缺少动作依据才回本专项定位补齐，不重做整场。

## 按任务选择规则

| 当前问题 | 方法文件 |
| --- | --- |
| 动机、强弱、赌注与环境 | [combat-construction](references/combat-construction.md) |
| 核心动作和摄影原则，按当前问题定位铁律 | [combat-iron-laws](references/combat-iron-laws.md) |
| 具体招式 | [moves-library](references/moves-library.md) |
| 动作句组织 | [eight-sentence-masters](references/eight-sentence-masters.md) |
| 句法与场景案例 | [syntax-corpus](references/syntax-corpus.md) |
| 强度定档、终结技与尺度 | [tier-and-finisher-system](references/tier-and-finisher-system.md) |
| 剑阵法相及大招 | [ultimate-array-library](references/ultimate-array-library.md) |
| 法术与大场面 | [spell-system](references/spell-system.md) |
| 场景与风格选择 | [presets-library](references/presets-library.md) |
| 摄影机、群战与复杂转场 | [combat-cheatsheet](references/combat-cheatsheet.md) |
| 命中反馈与负面表达 | [impact-frame-and-banlist](references/impact-frame-and-banlist.md) |
| 节奏负载；同时读适用条件与验证边界 | [combat-rhythm-and-load-guardrails](references/combat-rhythm-and-load-guardrails.md) |
| 激烈度和节奏零件；同时读默认建议及适用条件 | [combat-intensity-guardrails](references/combat-intensity-guardrails.md) |
| 特效介质与绘画表现 | [vfx-rendering-mandate](references/vfx-rendering-mandate.md) |
| 明确使用Seedance时的专项转译参考 | [seedance-dual-engine](references/seedance-dual-engine.md) |
| 需要补充动作选择与衔接 | [打斗动作与衔接参考库](references/打斗动作与衔接参考库.md) |

跨专项需要节奏负载或激烈度判断时，直接选读[节奏与负载](references/combat-rhythm-and-load-guardrails.md)或[力度与节奏参考](references/combat-intensity-guardrails.md)的当前档位；需要特效笔法时读[介质与分层](references/vfx-rendering-mandate.md)。不因跨专项引用再加载通用技能的全部方法。

## 交付

把方法落实到本次获授权正文，由负责业务技能合并自检；只提出确实影响当前任务的缺项。素材查看、自动重试、模型切换、生成及采用沿主控边界，专项设计本身不授予这些权限。
