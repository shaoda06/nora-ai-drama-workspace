# Nora AI短剧工作区

`nora-ai-drama-workspace` 是用于AI连续短剧策划、剧本开发、资料与素材管理、ComfyUI制作及迭代的工作区模板。包含通用工作规则、Nora短剧技能、配套工作流与工具，以及Krea2本地风格库。真实短剧项目由使用者在本地创建，不随模板提供。

## 开始使用

1. 获取整个工作区，使用支持本地文件与技能的agent打开根目录。推荐Codex Desktop；其他平台需自行提供相应的会话和监控能力。
2. agent先读取根目录 [AGENTS.md](AGENTS.md)，再按任务使用 [Nora短剧技能](.agents/skills/nora-ai-short-drama/SKILL.md) 或 [Krea2技能](.agents/skills/krea2-style-library/SKILL.md)。
3. 发起新短剧时，告知题材、素材和目标，由技能按阶段创建项目。三个ComfyUI适配技能已随主技能提供，是本工作区直接使用的真源，不重复复制安装。其余依赖按主技能的[来源与获取规则](.agents/skills/nora-ai-short-drama/SKILL.md#适用平台与技能依赖)按需补齐。
4. 新增外部技能默认安装到本工作区 `.agents/skills/{技能名}/`，已有可用安装复用。该工作区是本README所在目录，不是某部短剧的项目目录。新增本地依赖默认不纳入公共仓库。
5. 项目初始化时，agent询问该项目的ComfyUI地址，明确告知默认 `http://127.0.0.1:8188`，得到答复后创建项目根目录 `comfyui-config.json`。该文件只含 `remote-url`；本地地址指执行脚本所在机器，不默认指向另一台GPU服务器。

不需要ComfyUI即可进行策划、剧本和资料整理。执行生成时，使用者须自行准备能够运行配套工作流的ComfyUI服务；本工作区不附带模型权重、不安装服务端节点，也不保证任意后端都兼容。具体核对遵循执行规范。

## 目录

| 位置 | 用途 |
| --- | --- |
| `AGENTS.md` | 工作区约定、默认依赖安装位置及本地Git提交规则 |
| `.agents/skills/nora-ai-short-drama/` | 短剧流程、模板、脚本和7套配对工作流 |
| 主技能内 `dependencies/` | 三个ComfyUI适配技能的单一真源，保留上游及许可证 |
| `.agents/skills/krea2-style-library/` | 风格库使用与维护指引 |
| `Krea2风格库/` | 本地浏览页、当前风格资源、更新程序和启动入口 |
| `projects/` | 使用者真实短剧项目，模板仅保留目录说明 |
| `综合资料/` | 跨项目资料、未分类资料和本机过程资料，模板仅保留目录说明 |

技能历史版本、真实服务库存、项目、个人配置和工具缓存仍可留在本机，但由 `.gitignore` 排除。不要把它们的本地存在误认为已被Git备份。

## 依赖与来源

### 短剧流程技能

以下为Nora流程登记的 **8个依赖技能**，按任务需要读取或补齐，不要求每次全部加载。现行调用边界与安装规则以[主技能依赖章节](.agents/skills/nora-ai-short-drama/SKILL.md#适用平台与技能依赖)为准。

| 技能 | 用途 | 来源与获取位置 | 是否随本仓库提供 |
| --- | --- | --- | --- |
| `qwen-image-2-1-prompter` | Qwen Image 2.1图片提示词编写与校对；本流程中文规则优先 | [iamyoki/qwen-image-2.1-skill](https://github.com/iamyoki/qwen-image-2.1-skill)，[技能目录](https://github.com/iamyoki/qwen-image-2.1-skill/tree/main/skills/qwen-image-2-1-prompter) | 否，按需安装 |
| `h3-prompt-writing` | MiniMax H3视频提示词及输入模式 | MiniMax官方 [MiniMax-AI/MiniMax-H3](https://github.com/MiniMax-AI/MiniMax-H3)，[技能目录](https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills/h3-prompt-writing) | 否，按需安装 |
| `comfyui-api` | ComfyUI提交、查询与取回 | 上游 [MCKRUZ/ComfyUI-Expert / comfyui-api](https://github.com/MCKRUZ/ComfyUI-Expert/tree/dee27dc3d69b609c0006a8a12e71aadfc475ae95/skills/comfyui-api)；使用[随包适配版](.agents/skills/nora-ai-short-drama/dependencies/comfyui-api/SKILL.md) | 是，MIT |
| `comfyui-inventory` | ComfyUI节点、模型与接口能力核对 | 上游 [MCKRUZ/ComfyUI-Expert / comfyui-inventory](https://github.com/MCKRUZ/ComfyUI-Expert/tree/dee27dc3d69b609c0006a8a12e71aadfc475ae95/skills/comfyui-inventory)；使用[随包适配版](.agents/skills/nora-ai-short-drama/dependencies/comfyui-inventory/SKILL.md) | 是，MIT |
| `comfyui-troubleshooter` | ComfyUI执行与质量问题诊断 | 上游 [MCKRUZ/ComfyUI-Expert / comfyui-troubleshooter](https://github.com/MCKRUZ/ComfyUI-Expert/tree/dee27dc3d69b609c0006a8a12e71aadfc475ae95/skills/comfyui-troubleshooter)；使用[随包适配版](.agents/skills/nora-ai-short-drama/dependencies/comfyui-troubleshooter/SKILL.md) | 是，MIT |
| `stop-that-shit` | 约束过度工程、范围扩张及重复验证 | [lennney/stop-that-shit](https://github.com/lennney/stop-that-shit)，[技能目录](https://github.com/lennney/stop-that-shit/tree/main/skills/stop-that-shit) | 否，按需安装 |
| `stss` | 精简方案、计划等决策说明中的防御性赘述 | [lennney/stop-that-shit](https://github.com/lennney/stop-that-shit)，[技能目录](https://github.com/lennney/stop-that-shit/tree/main/skills/stss) | 否，按需安装 |
| `skill-creator` | 技能维护与格式验证 | Codex Desktop自带系统技能，按名称发现实际入口；其他平台缺少时说明维护能力缺项 | 否，使用平台内置版本 |

三个ComfyUI技能的适配来源版本为 `dee27dc3d69b609c0006a8a12e71aadfc475ae95`，各自目录保留 `LICENSE`。本工作区的 `dependencies/` 是可维护真源；上游仅供署名、追溯和比较更新，不能用上游原版或全局同名技能自动替代。外部安装技能须保留其上游许可证，不受本仓库MIT许可证重新授权。

**可选参考**：`screenwriting-master`（山音超级编剧大师）来自 [Shanyin-ai/shanyin-screenwriting-master](https://github.com/Shanyin-ai/shanyin-screenwriting-master)，获取仓库根目录 `screenwriting-master（Claude&GPT通用）.skill` 并解包为 `screenwriting-master/`。不随本仓库提供，仅在用户明确要求时调用；不属于上述8个必需流程依赖。

### 本工作区技能与风格资源

[Nora短剧技能](.agents/skills/nora-ai-short-drama/SKILL.md)与[Krea2风格库技能](.agents/skills/krea2-style-library/SKILL.md)由本工作区维护并随仓库提供。Krea2技能是独立工具入口，不额外计入Nora的8个流程依赖。

| 资源 | 来源与作者 | 本地内容与许可说明 |
| --- | --- | --- |
| Clio风格库与预览 | [lumenastrum/clio-style-preview](https://github.com/lumenastrum/clio-style-preview)；风格文本主要来自 [u/Dear-Spend-2865原始分享](https://www.reddit.com/r/StableDiffusion/comments/1uzdj7o/krea_2_styles_wildcards_txt/) | `Krea2风格库/Krea2_风格资源/krea2_styles/`；上游代码MIT，原许可见 [Clio-LICENSE.txt](Krea2风格库/Clio-LICENSE.txt)，该许可不将社区文本纳入MIT声明；预览图和文本的授权由维护者另行处理 |
| Ray Moodboard资源包 | [Ray3780 / Ray Style Switching Extension](https://civitai.com/models/2856809/ray-style-switching-extension)；[发布元数据API](https://civitai.com/api/v1/models/2856809) | `Krea2风格库/Krea2_风格资源/Krea2_moodboard/`；当前来源包及版本记录于 `versions.json`，遵循发布者许可及原始素材权利边界，不改授MIT |
| Moodboard原始来源 | [Krea官方Moodboard介绍](https://www.krea.ai/blog/moodboards-krea-2)、[服务条款](https://www.krea.ai/terms) | Ray发布说明称其整理自Krea公开Moodboard；本地有一张缺失预览从Krea原图补入，详见第三方说明；不把整理者的发布选项等同于原始素材的完整授权 |

现行资源随仓库保留，实际应用版本及来源下载地址见 [versions.json](Krea2风格库/Krea2_风格资源/versions.json)。第三方授权事项由工作区维护者负责处理；这项分发安排不表示agent已经核实取得全部授权，也不改变原始许可。详见[第三方来源与许可](Krea2风格库/THIRD_PARTY_NOTICES.md)。

### 运行环境与后端来源

- [Python](https://www.python.org/downloads/)：本地执行及浏览工具使用Python 3.9及以上标准库；具体用途见下方环境表。
- [Git](https://git-scm.com/downloads)：本地版本管理；[GitHub CLI](https://cli.github.com/)或已授权的平台工具用于可选的远端操作。
- [Node.js](https://nodejs.org/)：18及以上，仅用于项目浏览页的维护测试。
- [ComfyUI](https://github.com/Comfy-Org/ComfyUI)：由使用者独立部署的图片／视频生成后端。本仓库携带工作流，不携带模型权重和服务端自定义节点。每个项目配置服务地址，具体节点、模型与兼容性按本地工作流及执行规范核对；这里的技能依赖清单不是后端安装清单。

## 环境

| 用途 | 要求 |
| --- | --- |
| 阅读规则与创作 | 可读写工作区文件的agent；对应阶段按需读取技能 |
| ComfyUI客户端、库存脚本、项目浏览页、Krea2工具 | Python 3.9及以上，运行脚本仅使用标准库 |
| 本地版本维护 | Git；完成任务后按AGENTS规则提交，推送另需用户要求 |
| GitHub发布 | GitHub账号及仓库权限，可通过插件或已授权的GitHub CLI操作 |
| 浏览风格库和项目页 | 现代浏览器；Krea2离线浏览无需常驻服务，更新需要本地Python服务和联网 |
| 项目浏览页的维护测试 | Node.js 18及以上的 `node --test`；不是普通制作的运行依赖 |
| 技能格式校验 | 使用平台提供的 `skill-creator` 及其校验工具；按工具本身要求准备依赖 |

Python命令示例使用 `python3`；Windows按实际安装可改为 `py -3`。macOS双击入口使用zsh，其他平台使用下面的Python命令。没有需要整体安装的Node前端工程。

## Krea2风格库

macOS可打开 `Krea2风格库/启动Krea2风格库.command`。在工作区根目录也可运行：

```sh
python3 Krea2风格库/Krea2_更新工具/server.py
```

默认访问 `http://127.0.0.1:8876/`，服务仅监听本机。`--port 8877` 可换端口，`--no-browser` 可只启动服务。结束时按Ctrl+C。直接打开 [离线浏览页](Krea2风格库/Krea2_风格浏览.html) 可浏览和复制提示词，但不能更新资源。

当前资源随工作区提供，后续由使用者在页面手动检查、准备、审阅差异、应用或恢复。更新程序不会自动在后台升级资源。详见[使用说明](Krea2风格库/Krea2_风格资源/使用说明.md)及[第三方来源与许可](Krea2风格库/THIRD_PARTY_NOTICES.md)。

## 维护与检查

修改短剧技能前读取其[维护规范](.agents/skills/nora-ai-short-drama/维护规范.md)，使用 `skill-creator`。三个ComfyUI技能只在随包真源中维护，不从远端自动覆盖；吸收上游更新时检查适配差异并保留来源版本和许可证。Krea2的使用与维护规则集中在对应技能，不另设局部AGENTS。

按影响范围选择已有测试，不因普通文档修改运行全部测试。下列命令均在工作区根目录执行：

```sh
# ComfyUI通信客户端：本地测试，不访问生产服务。
python3 -B -m unittest discover -s .agents/skills/nora-ai-short-drama/references/comfyui-scripts -p 'test_*.py'
# 项目浏览页与工作流脚本。
python3 -B -m unittest discover -s .agents/skills/nora-ai-short-drama/scripts -p 'test_*.py'
node --test .agents/skills/nora-ai-short-drama/scripts/test_project_portal_ui.mjs
# 仅检查本地画布/API配对，不验证远端兼容性。
python3 -B .agents/skills/nora-ai-short-drama/scripts/workflow_baselines.py
# Krea2：临时目录与本机临时端口测试，不联网更新资源。
python3 -B -m unittest discover -s Krea2风格库/Krea2_更新工具 -p 'test_*.py'
```

退出码0表示相应检查通过；脚本测试不等于用户批准素材，也不替代涉及交互修改时的浏览器检查。只维护说明且不影响项目数据结构时，不重新生成项目浏览页。

## Git边界

默认只跟踪白名单内的公共模板内容。新增根目录工具或希望分发的文件时，应明确其归属并同步 `.gitignore`。真实项目、综合资料内容、`.codex/` 个人配置、其他已安装技能、历史归档、`state/` 库存缓存、Krea2 `work/` 备份均不入库。

每次完成获授权维护并通过检查后，agent只为本次任务创建本地提交；纯讨论和只读检查不提交，推送须另有明确要求。提交前查看差异和暂存清单，不混入并发修改。Git只保存被跟踪且已提交的文件；真实项目需另行安排私有版本管理或备份。

作为GitHub模板使用时，新建工作区获得当前目录和文件，但不会自动接收模板后续更新。同步更新前检查本地修改，不要覆盖使用者自己的内容。单独分享Nora技能时同时携带适用的许可证及三个随包依赖的许可证。

## 授权

本工作区原创技能、脚本及文档采用根目录 [MIT许可证](LICENSE)，允许修改、再分发和商用，保留版权及许可声明。

第三方内容不因放入本仓库自动改为MIT：三个ComfyUI适配技能保留各自许可证；Krea2风格文本、预览图及来源限制以[第三方说明](Krea2风格库/THIRD_PARTY_NOTICES.md)为准。工作区维护者负责处理第三方资源的授权事项，现按其决定保留资源用于分发准备；本说明不声称已取得尚未提供的授权证明。
