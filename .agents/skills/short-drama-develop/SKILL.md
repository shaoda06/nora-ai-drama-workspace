---
name: short-drama-develop
description: 为 Nora 完成项目定位与画风、主旨简介和世界观、故事大纲、分集规划、原稿改编和多集整稿接续；按当前交付范围使用对应模板。
license: MIT
---

# Nora 故事开发

本技能承担 Nora 的当前业务交付。直接调用也遵循[主控读取范围](../nora-ai-short-drama/SKILL.md#读取范围)与[规则优先级](../nora-ai-short-drama/SKILL.md#外部技能协作与规则优先级)，不回主控重复走全流程。按当前任务选择下方入口；首次完整制作读完整适用要求和模板，局部修改只读受影响内容。方法库中的外部目录、配置、格式、发布及审批流程不替代Nora规则。写入前按[文件与版本](../nora-ai-short-drama/references/共用规则/文件版本与工作稿规范.md)的相关章节保存，交付按[主控完成标准](../nora-ai-short-drama/SKILL.md#完成标准)同步。

## 按交付选择规则

| 任务 | 直接入口 |
| --- | --- |
| 原稿、小说、梗概或多集整稿接续 | [原稿边界](../nora-ai-short-drama/references/共用规则/创作定位与原稿规范.md#用户原稿的读取复用与确认)，按实际材料定位读取；整稿方法见下表 |
| 项目定位、制作形态及视觉风格 | [定位与画风](references/项目定位与画风规范.md)及其中模板；完整美术正文、视频短版和语言适配同页准备与确认 |
| 主旨、简介、故事核心与世界观 | [主旨简介与世界观](references/主旨简介与世界观规范.md)，采用既有七章模板 |
| 全剧故事大纲 | [故事大纲](references/故事大纲规范.md)，采用既有六章模板 |
| 分集地图、大纲或已有剧集拆分 | [分集大纲](references/分集大纲规范.md)，维护既有全剧索引与逐集七章正文 |

创作前按[开发方法适配](references/故事开发方法适配规范.md)选择当前阶段的方法；[创作定位](../nora-ai-short-drama/references/共用规则/创作定位与原稿规范.md)落实到当前题材，不套固定反转配额。准备文档有具体表达问题时按[表达规范](../nora-ai-short-drama/references/共用规则/准备文档表达规范.md)使用humanizer-zh。

## 方法按问题读取

| 问题 | 方法 |
| --- | --- |
| 人物目标、压力、升级与铺垫 | [故事方法](references/story-craft.md)、[人物与跨集状态](references/serial-character-and-memory.md) |
| 分集因果、开场与交接 | [分集设计](references/episode-design.md) |
| 多集整稿接入与分批读取 | [整稿接入](references/multi-episode-intake.md)，脚本仅在明确适配输入输出后使用 |
| 改编、取舍与参考作品 | [改编方法](references/adaptation-craft.md)、[参考吸收](references/creative-reference-intake.md) |
| 中段重复、揭示与回报 | [机制循环](references/mechanism-loop.md)、[揭示反转回报](references/reveal-reversal-payoff.md) |
| 题材、钩子及特殊前提 | [题材与钩子](references/genre-and-hook-playbook.md)、[题材卡](references/genre-cards.md)、[前提装置](references/premise-devices.md) |
| 视觉方向与导演意图 | [导演阐述方法](references/director-brief-craft.md)，落实到既有定位及工作稿 |

## 依赖与交接

确定画风时按定位规则介绍独立可选的[krea2-style-library](../krea2-style-library/SKILL.md)，实际使用才加载；库中风格不自动成为项目已确认正文。缺少工具不阻塞定位讨论。世界观在主旨简介维护，资产卡交[资产设计](../nora-drama-assets/SKILL.md)，单集展开交[剧本写作](../short-drama-write/SKILL.md)。不新增外部简报、引擎、JSONL、季度计划或批准状态来重复已有资料。

文本交付按[合并自检](../short-drama-review/references/文本自检与订正规范.md)处理，原稿与当前任务之外的内容不自动重写。
