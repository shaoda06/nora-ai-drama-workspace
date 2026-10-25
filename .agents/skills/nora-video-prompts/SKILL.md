---
name: nora-video-prompts
description: 将 Nora 已确认分镜、P段和实际参考素材转写成视频模型正文与中文参考版，完成主体素材映射及内容核对；H3按实际模式读取官方指南，不提交生成。
---

# Nora 视频提示词

本技能承担 Nora 的当前业务交付。直接调用也遵循[主控读取范围](../nora-ai-short-drama/SKILL.md#读取范围)与[规则优先级](../nora-ai-short-drama/SKILL.md#外部技能协作与规则优先级)，不回主控重复走全流程。按当前任务选择下方入口；首次完整制作读完整适用要求和模板，局部修改只读受影响内容。方法库中的外部目录、配置、格式、发布及审批流程不替代Nora规则。写入前按[文件与版本](../nora-ai-short-drama/references/共用规则/文件版本与工作稿规范.md)的相关章节保存，交付按[主控完成标准](../nora-ai-short-drama/SKILL.md#完成标准)同步。

## 按当前任务读取

| 任务 | 入口 |
| --- | --- |
| 新建完整分段提示词 | [阶段接续](references/提示词阶段接续规范.md)，依其顺序进入正文制作规则及对应模板 |
| H3正文编写或修改 | Ref2VA先读[参考定义与保留说明](references/视频提示词制作规范.md#ref2va参考定义与保留说明)，落实到主体定义、保留说明与逐镜正文；再按[H3模式入口](references/H3提示词规范.md)，调用[h3-prompt-writing](../h3-prompt-writing/SKILL.md)的实际模式指南 |
| 表情转写或相关实际反馈 | [表情拆解](../facial-expression/SKILL.md)，按情境写出可见面部变化和必要过程，并落实首次使用告知与反馈更新 |
| 镜头语言转写或相关实际反馈 | [镜头语言与表达](../camera-language/SKILL.md)，将已确认镜头落实为起始关系、必要变化与落点，沿其首次使用提示与反馈复核；不在转写时另改镜头设计或模型格式 |
| 素材对应、说话者或语言修订 | 制作规范中[项目与模型标签](references/视频提示词制作规范.md#项目引用与模型标签)、[语言规则](references/视频提示词制作规范.md#h3模型正文的语言与命名)及受影响的完整交流 |
| 内容核对与中文对应检查 | Ref2VA同时按[参考定义与保留说明](references/视频提示词制作规范.md#ref2va参考定义与保留说明)核对素材特征及章节归属；[内容核对](references/视频提示词制作规范.md#模型正文的内容核对)，检查实际启用的公共＋本组完整正文及同版中文 |
| 接近或超过正文上限 | [长度规则](references/视频提示词制作规范.md#模型提示词长度)，先评估分段密度；确需拆段返回分镜，不能硬删必要表达 |

## 执行顺序与职责

按[编写与检查顺序](references/视频提示词制作规范.md#提示词编写与检查顺序)：确定依据、建立主体对应、完整转写、逐节翻译、核对订正，再进入必要技术准备。identity、space_action、continuity_sound、translation的依据和结论写入既有content_review；工具判断确定性要求，Agent判断内容，具体要求只在制作规范维护。

镜头设计、P段与动作缺项回[分镜](../short-drama-storyboard/SKILL.md)，剧情和原台词缺项回[写作](../short-drama-write/SKILL.md)，资产设计或来源缺项回[资产](../nora-drama-assets/SKILL.md)。不在转写时另编故事，也不默认重新加载打戏或山音全库；已确认的动作和法术设计直接转写。

画风使用定位文件中已确认的适用视频短版及语言适配，缺少时回[定位](../short-drama-develop/references/项目定位与画风规范.md#项目画风展开示例验证与复用)补齐，不临时压缩长版。视觉方法按[视觉表达](../short-drama-storyboard/references/视觉表达方法规范.md)相关章节读取；画面文字沿[共用边界](../nora-ai-short-drama/references/共用规则/画面文字与字幕规范.md)。

初稿或实质性修订完成后，直接按[文本交付前自检](../short-drama-review/references/文本自检与订正规范.md#文本交付前的自检与订正)的第6步，合并本次内容核对与视听文本审查方法；订正受影响正文及中文对应，不另回审查技能入口或增加检查轮次。仅改错字、格式或记录时按该规则处理受影响范围。

交付、状态与接续执行[提示词自检与执行授权](../nora-ai-short-drama/references/共用规则/主控操作规范.md#提示词自检与执行授权)。仅写或核对提示词时在正文交付结束；获授权生成才交[生成执行](../nora-generation/SKILL.md)。正常结果通知不重新做内容审查；修订依据和授权边界按[返修归属](../nora-ai-short-drama/references/共用规则/制作返修与完整重做规范.md)。
