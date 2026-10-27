---
name: short-drama-review
description: 对 Nora 的原稿分析、故事、剧本、资产、分镜及图片视频提示词进行专项审查，或为当前作者提供合并自检方法；媒体内容审查须有实际查看授权。
license: MIT
---

# Nora 内容审查

本技能承担 Nora 的当前业务交付；直接调用遵循[业务技能共同约定](../nora-ai-short-drama/references/共用规则/主控操作规范.md#业务技能共同约定)，按下方当前任务入口接续。

## 合并自检与专项审查

创作者按[文本自检与订正](references/文本自检与订正规范.md)在当前任务合并检查并按授权改回来源；不为使用本技能增加新会话、独立审查报告或批准阶段。只受托审查时按[问题交付](references/文本审查与返修规范.md#文本审查问题与交付)给出位置、依据、影响和修订要求，不擅自修改来源。用户另行授权修改时由对应业务技能接续。

## 按对象选择

| 对象或问题 | 方法与业务依据 |
| --- | --- |
| 原稿分析与改编 | [原稿审查](references/rubric-source-analysis.md)及[原稿边界](../nora-ai-short-drama/references/共用规则/创作定位与原稿规范.md) |
| 故事与单集剧本 | [故事剧本审查](references/rubric-story-script.md)，对应开发／写作规则、人物及采用原稿 |
| 人物场景道具、图片提示词 | [资产与提示词审查](references/rubric-assets-prompts.md)及[资产专项](../nora-drama-assets/SKILL.md)对应类型 |
| 分镜、首帧与视频提示词文本 | [视觉运动审查](references/rubric-visual-motion.md)、[文本方法适配](references/文本审查与返修规范.md#文本审查的方法补充)，核对当前镜头、P段和实际输入 |
| 表情表达检查或生成后的具体表情反馈 | [表情拆解](../creative-techniques/SKILL.md#表情表达)；分镜允许抽象表情，模型正文检查具体面部变化。文本检查不构成生成验证；真实反馈按该技能更新参考表的验证情况，不因此取得修改项目来源或查看媒体的授权 |
| 镜头表达检查或针对实际镜头效果的反馈 | [镜头语言与表达](../creative-techniques/SKILL.md#镜头表达)，核对观看目的、可见过程及相容性；指南验证更新沿其反馈规则，文本检查不等于生成有效，也不扩大媒体查看或项目修订授权 |
| 转场、特效或动作等技法的实际效果反馈 | [共用反馈复核](../creative-techniques/references/学习与反馈维护规范.md#实际反馈复核)，按主题归属更新原专业参考；文本检查与媒体查看边界沿原任务 |
| 如何说明问题与复核 | [审查方法](references/review-method.md)；返修归属以[共用规则](../nora-ai-short-drama/references/共用规则/制作返修与完整重做规范.md)为准 |
| 模板感及重复写法 | [反模板方法](references/anti-template-repair.md)，具体表达可按需使用humanizer-zh |
| 用户授权的媒体审查与生产观察 | [生产质量参考](references/production-quality-gates.md)、[项目校准方法](references/project-calibration.md)，仅在主控允许的查看范围内使用 |

## 完成与边界

具体标准由所属业务规则维护，本技能引用，不复制第二套阈值。剧本和分镜按[山音适配](../nora-ai-short-drama/references/共用规则/山音方法适配规范.md)合并当前适用检查，提示词的内容核对仍由[提示词规则](../nora-video-prompts/references/视频提示词制作规范.md#模型正文的内容核对)负责。依据[交付核对](references/交付核对规范.md)完成本次范围。

文本通过、工具技术通过、媒体结果符合要求和用户批准分别记录。纯文本审查不授权看图、审片、自动重生成或另派Agent；媒体查看沿[主控边界](../nora-ai-short-drama/SKILL.md#看图能力调用边界)。问题和结论并入既有工作稿、审阅记录或当前交付，不新建外部JSON裁决和审批状态；真实未决项明确说明。
