---
name: short-drama-write
description: 为 Nora 新写、修订或规范化本集剧本，处理对白和表演、豆包台词润色交接及回稿；打戏按需调用专项，不承担分镜或生成执行。
license: MIT
---

# Nora 剧本写作

本技能承担 Nora 的当前业务交付。直接调用也遵循[主控读取范围](../nora-ai-short-drama/SKILL.md#读取范围)与[规则优先级](../nora-ai-short-drama/SKILL.md#外部技能协作与规则优先级)，不回主控重复走全流程。按当前任务选择下方入口；首次完整制作读完整适用要求和模板，局部修改只读受影响内容。方法库中的外部目录、配置、格式、发布及审批流程不替代Nora规则。写入前按[文件与版本](../nora-ai-short-drama/references/共用规则/文件版本与工作稿规范.md)的相关章节保存，交付按[主控完成标准](../nora-ai-short-drama/SKILL.md#完成标准)同步。

## 按任务读取

| 任务 | 必要规则 |
| --- | --- |
| 新写本集或实质性场景修订 | [本集制作与接续](references/本集制作与剧本接续规范.md)、[单集剧本](references/单集剧本制作规范.md)和[本集故事剧本模板](../nora-ai-short-drama/references/模板/本集故事剧本模板.md) |
| 局部对白、人物口吻或表演修订 | [对白与表演](references/对白与表演修订规范.md)中对应章节、完整交流及必要人物与处境依据 |
| 豆包润色交接或回稿处理 | [交接与回稿](references/台词润色交接与回稿规范.md)及其模板；新写默认交接，已有批准稿不自动重做 |
| 原稿规范化或续写 | [原稿边界](../nora-ai-short-drama/references/共用规则/创作定位与原稿规范.md)，按Nora模板保留实际采用原文与确认范围 |
| 打戏构思与必要动作 | [通用打戏](../sd-combat-engine/SKILL.md)、[玄幻打戏](../sd-xuanhuan-engine/SKILL.md)或[写实格斗](../sd-real-engine/SKILL.md)，按戏型选构思和动作章节 |

## 编写与方法

先明确人物当前目的、阻力、行动结果和场次退出状态，再写完整交流、动作、听者反应、停顿和声音。只对本集实际使用的选择、证据、次数或死线做对应推演，不为了检查创造输入没有的机关。故事、台词和决定因果的必要表演在剧本完成，具体机位、镜长和P段交分镜。

按[山音范围](../nora-ai-short-drama/references/共用规则/山音方法适配规范.md)自动读取当前阶段方法，无需用户点名。对白诊断使用[dialogue](../dialogue/SKILL.md)，具体表达问题使用[humanizer-zh](../humanizer-zh/SKILL.md)，均按对白规范的适用条件合并到当前正文。

| 问题 | 方法资料 |
| --- | --- |
| 行动因果、选择、证据或时间容量 | [剧作手艺](references/script-craft.md) |
| 人物声音、过去关系及接话 | [对白手艺](references/dialogue-craft.md) |
| 声源、留白与声音过渡 | [场景声音](references/scene-sound-dramaturgy.md) |
| 同一义务的不同可拍实现 | [可替代实现](references/substitutable-realization.md) |
| 长任务接续 | [场景交接方法](references/scene-handoff-capsule.md)，复用既有工作稿或上下文，不另建台账 |

剧本语法以Nora模板为准，时长按[对白与动作核对](../nora-ai-short-drama/references/共用规则/层级编号与时长规范.md#对白与动作时长核对)判断；方法中的通用字数估时不覆盖它。交付按[文本自检](../short-drama-review/references/文本自检与订正规范.md)合并处理。批准后的具体版本交[分镜设计](../short-drama-storyboard/SKILL.md)，不因润色完成推定已获批准。
