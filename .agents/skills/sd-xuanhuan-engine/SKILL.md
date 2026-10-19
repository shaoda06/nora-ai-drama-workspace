---
name: sd-xuanhuan-engine
description: 为 Nora 的修仙、仙侠、法术对轰、剑阵法相与大场面提供动作编排、双向受力、特效材质和尺度方法。
---

# Nora 玄幻打戏专项

## Nora 接入与阶段边界

本技能提供专项动作与视听设计，由[剧本写作](../short-drama-write/SKILL.md)或[分镜设计](../short-drama-storyboard/SKILL.md)按任务调用。只写剧情时读取构思、动作因果及必要招式方法；设计镜头时再读取相关摄影、空间与节奏章节。直接调用也沿Nora当前项目、批准依据和交付规则。

方法落实到当前剧本、SH镜头和P段，不创建另一套记录。故事与对白由写作负责，镜头和分段由分镜负责，[视频提示词](../nora-video-prompts/SKILL.md)按实际模型格式转写，[生成执行](../nora-generation/SKILL.md)调用固定工具。参考库中的short-drama-director、validate_prompt.py、图N、固定整秒、默认反杀、输出封装和机检门仅属于原套装上下文，不构成Nora的格式、权限或必须剧情；适用模型的真实限制仍须执行。

优先级遵循[Nora主控](../nora-ai-short-drama/SKILL.md#外部技能协作与规则优先级)。各规则中的强度、镜数、贴身比例、静止或手绘化建议须连同档位、适用条件及豁免读取，不把某档或个案结论扩大到全部题材和模型。保留可用方法；具体冲突按当前项目处理，不凭措辞绝对就否定，也不自动将其升为通用硬限制。参考库按下表直接选读，不默认通读铁律全表或其他两种专项。

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

跨专项需要节奏负载或激烈度判断时，直接选读[节奏与负载](../sd-combat-engine/references/combat-rhythm-and-load-guardrails.md)或[强度与放行](../sd-combat-engine/references/combat-intensity-guardrails.md)的当前档位；需要特效笔法时读[介质与分层](../sd-combat-engine/references/vfx-rendering-mandate.md)。不因跨专项引用再加载通用技能的全部方法。

## 交付

把方法落实到本次获授权正文，由负责业务技能合并自检；只提出确实影响当前任务的缺项。素材查看、自动重试、模型切换、生成及采用沿主控边界，专项设计本身不授予这些权限。
