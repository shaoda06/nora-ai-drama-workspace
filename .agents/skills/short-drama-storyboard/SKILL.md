---
name: short-drama-storyboard
description: 为 Nora 编写、修订或审查场次分镜、镜头调度、视频分段及首帧提示词；按需调用通用、玄幻或写实打戏方法，不生成媒体。
license: MIT
---

# Nora 分镜设计

本技能是 Nora 的业务入口。直接调用时也遵循[主控读取范围](../nora-ai-short-drama/SKILL.md#读取范围)及[规则优先级](../nora-ai-short-drama/SKILL.md#外部技能协作与规则优先级)，只定位当前任务，不回主控重走全流程。项目已有方向、用户要求、Nora模板、编号和批准依据优先；方法资料中的外部配置、目录、发布工具和审批安排不作为本流程入口。已读且未变的规则复用。

## 按任务直接读取

| 任务 | 规则与产出 |
| --- | --- |
| 新建完整场次分镜 | [分镜阶段接续](references/分镜阶段接续规范.md#4-整理场次分镜并划分视频生成分段)，依其顺序进入场次规则、分段规则及模板，从已批准剧本落实SH镜头及P段 |
| 局部镜头、空间或动作修订 | [场次分镜规则](references/场次分镜制作规范.md)中的受影响章节及必要上下游；完整重做先读[完整重做要求](../nora-ai-short-drama/references/共用规则/制作返修与完整重做规范.md#完整重做的范围与完成要求) |
| 分段、拆段或输入容量调整 | [视频分段规划规范](references/视频分段规划规范.md)，核对当前及相邻段、真实素材与模型容量 |
| 手绘导演分镜表及讨论反馈 | [导演分镜表规范](references/手绘导演分镜表规范.md)及其固定模板；内容来自对应场次分镜，图像制作交资产与生成技能 |
| 开场素材选择、首帧需求判断、提示词或已有素材复用 | 先按[首帧使用条件与质量取舍](references/首帧参考图规范.md#1-制作复用与画面要求)确定本段是否采用，再按[分段素材与首帧规范](references/分段素材与首帧规范.md)落实输入用途；实际需要写Qwen正文时调用[图片提示词入口](../nora-drama-assets/references/图片提示词规范.md#图片提示词) |
| 场景机位需求及选图 | [视图规划与复用](../nora-drama-assets/references/场景资料与参考图规范.md#42-视图规划与复用)；分镜维护本次镜头选择，缺图交[资产技能](../nora-drama-assets/SKILL.md) |
| 打戏、斗法、写实格斗 | 下方打戏方法入口；按实际段落选择，不要求三技能全读 |
| 景别、构图、机位、运镜、光影、焦点方法及技巧学习 | [镜头语言与表达](../creative-techniques/SKILL.md#镜头表达)，按观看目的辅助选择并落实到既有分镜／首帧字段；方法库由该技能维护，正式镜头设计与P段仍在本技能 |

## 方法与专项

新写、完整重做或局部修订涉及景别、机位、构图、运镜或切点时，均先执行[镜头选择与观看效果复核](references/场次分镜制作规范.md#运镜构图与切镜的选择)，在选择过程中按问题取用镜头指南，结果写入既有逐镜字段；局部任务同时核对受影响的前后镜。只改错字、格式或记录时不重做镜头设计。下方方法按具体缺项补充，不替代这一选择过程。

按[分镜方法补充](references/场次分镜制作规范.md#分镜方法补充)和[山音适配](../nora-ai-short-drama/references/共用规则/山音方法适配规范.md#山音方法的范围与适配)落实适用方法；[视觉表达](references/视觉表达方法规范.md#视觉表达方法)按内容读相关章节。方法均落实到Nora现有字段，不创建SHOT／REF／PLAN或short-drama.json等另一套身份与档案。

| 具体问题 | 直接方法入口 |
| --- | --- |
| 镜头职责、对白覆盖、切点及镜长 | [镜头手艺](references/shot-craft.md)、[生产镜头语法](references/production-shot-grammar.md) |
| 多方案导演设计、群戏调度或覆盖缺口 | [场次视觉计划](references/scene-visual-plan.md)、[调度手册](references/blocking-playbooks.md)、[覆盖检查](references/coverage-audition.md)，只选对应问题 |
| 光线、冻结关键帧及漫剧表现 | [光线](references/lighting-craft.md)、[关键帧](references/keyframe-craft.md)、[漫剧词表](references/comic-keyframe-lexicon.md)、[转写示例](references/screenplay-to-keyframe-example.md) |
| 修订关联与连续性检查 | [镜头修订方法](references/shot-revision-identity.md)、[连续性示例](references/review-and-fixtures.md)；编号与采用沿Nora规则 |
| 通用武侠或打斗因果、力量与节奏 | [通用打戏](../sd-combat-engine/SKILL.md) |
| 修仙拆招、法术、剑阵与大场面 | [玄幻打戏](../sd-xuanhuan-engine/SKILL.md) |
| 写实格斗、步法、防守与多人调度 | [写实格斗](../sd-real-engine/SKILL.md) |

分镜正文涉及玄幻法术时，执行[玄幻法术使用路径](../sd-xuanhuan-engine/SKILL.md#法术表现的使用路径)，将本镜采用的形态、运动、作用与反馈写入已有镜头字段；交付前按该路径所链表现核对复查。不只在“缺招式”时调用，也不把需要下游呈现的效果留成一个法术名称。

分镜中的表情可用抽象词交代意图；编写首帧或视频模型提示词时，按[表情拆解](../creative-techniques/SKILL.md#表情表达)细化为可见面部变化，不要求在分镜阶段提前写满提示词。

## 交接与完成

剧情、原台词及决定因果的必要动作回[剧本写作](../short-drama-write/SKILL.md)维护；取景、镜头和P段由本技能维护。参考图由[资产设计](../nora-drama-assets/SKILL.md)补齐，已确认镜头交[视频提示词](../nora-video-prompts/SKILL.md)转写。不得为迁就参考图、旧P段或缓存保留不合理镜头；具体完整重做范围沿上方规则。

按[文本自检](../short-drama-review/references/文本自检与订正规范.md#文本交付前的自检与订正)落实当前阶段的必需检查和方法，合并订正后交付。本批修改形成送审或执行方案时读[修改轮次](../nora-ai-short-drama/references/共用规则/场次版本组合规范.md#场次修改轮次)，使用既有工具一次登记该集组合；不按场次分别增轮，不将执行缓存组当成播放组合。写入后按[主控完成标准](../nora-ai-short-drama/references/共用规则/主控操作规范.md#完成标准)交付，文本完成不授权生成。
