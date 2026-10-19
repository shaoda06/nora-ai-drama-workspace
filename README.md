# Nora AI短剧工作区

`nora-ai-drama-workspace` 是用于AI连续短剧策划、剧本开发、资料与素材管理、ComfyUI制作及迭代的工作区模板。包含通用工作规则、Nora短剧技能、配套工作流与工具，以及Krea2本地风格库。真实短剧项目由使用者在本地创建，不随模板提供。

## 开始使用

1. 获取整个工作区，使用支持本地文件与技能的agent打开根目录。推荐Codex Desktop；其他平台需自行提供相应的会话和监控能力。
2. agent先读取根目录 [AGENTS.md](AGENTS.md)，再按任务使用 [Nora短剧技能](.agents/skills/nora-ai-short-drama/SKILL.md) 或 [Krea2技能](.agents/skills/krea2-style-library/SKILL.md)。
3. 发起新短剧时，告知题材、素材和目标，由技能按阶段创建项目。三个ComfyUI适配技能已随主技能提供，是本工作区直接使用的真源，不重复复制安装。其余依赖按主技能的[来源与获取规则](.agents/skills/nora-ai-short-drama/references/流程规范/技能依赖与协作规范.md#适用平台与技能依赖)按需补齐。
4. 新增外部技能默认安装到本工作区 `.agents/skills/{技能名}/`，已有可用安装复用。该工作区是本README所在目录，不是某部短剧的项目目录。当前独立安装的外部技能按 `.gitignore` 排除；新增技能默认可被Git发现，提交前核对来源、许可及是否需要随模板提供。
5. 初始化项目工作区时，按下方[FFmpeg初始化与运行](#ffmpeg初始化与运行)落实媒体处理依赖；服务地址询问及配置按[主技能的工作区ComfyUI配置](.agents/skills/nora-generation/references/ComfyUI-服务配置与任务提交规范.md#工作区-comfyui-配置)执行。

不需要ComfyUI即可进行策划、剧本和资料整理。执行生成时，使用者须自行准备能够运行配套工作流的ComfyUI服务；本工作区不附带模型权重、不自动安装服务端节点，也不保证任意后端都兼容。随包节点资源的存放、获授权安装及验证按[节点与安装包](.agents/skills/nora-ai-short-drama/维护规范.md#comfyui节点与安装包)执行；任务核对遵循执行规范。

## 会话组织

会话职责、编号、标题、并行与逐集接续统一维护于[会话与进度管理规范](.agents/skills/nora-ai-short-drama/references/流程规范/会话与进度管理规范.md)，此处不另列会话清单。

## 目录

| 位置 | 用途 |
| --- | --- |
| `AGENTS.md` | 工作区约定、默认依赖安装位置及本地Git提交规则 |
| `.agents/skills/nora-ai-short-drama/` | 短剧主控、共用规则、模板、脚本及[配套工作流](.agents/skills/nora-ai-short-drama/references/comfyui-workflow)；视频工作流用途见[H3执行规范](.agents/skills/nora-generation/references/ComfyUI-H3视频执行规范.md#0-制作策略与工作流配置) |
| 主控同级的7个业务技能 | [开发、写作、资产、分镜、视频提示词、生成执行、审查](.agents/skills/nora-ai-short-drama/SKILL.md#按任务读取)；现行规则归所属技能，四个适配short-drama技能随仓库保存 |
| `sd-combat-engine/`、`sd-xuanhuan-engine/`、`sd-real-engine/` | 位于 `.agents/skills/`，由业务技能按戏型选择通用、玄幻、写实打戏方法 |
| 主技能内 `dependencies/` | 三个ComfyUI适配技能的真源及已登记的节点源码目录或ZIP安装包，保留来源、版本与许可证 |
| `.agents/skills/krea2-style-library/` | 风格库使用与维护指引 |
| `工作区浏览服务/` | React＋FastAPI浏览服务、双击启动、共用解析器与开发历史 |
| `工作区浏览服务/Krea2风格库/` | 本地浏览页、当前风格资源、更新程序和启动入口 |
| `projects/` | 使用者真实短剧项目，模板仅保留目录说明 |
| `综合资料/` | 跨项目资料、未分类资料和本机过程资料，模板仅保留目录说明 |

技能历史版本、真实服务库存、项目、个人配置和工具缓存仍可留在本机，但由 `.gitignore` 排除。不要把它们的本地存在误认为已被Git备份。

## 依赖与来源

### 短剧流程技能

流程依赖的使用条件与边界读取[主技能依赖入口](.agents/skills/nora-ai-short-drama/references/流程规范/技能依赖与协作规范.md#适用平台与技能依赖)；准确获取来源、版本与许可读取[依赖获取资料](.agents/skills/nora-ai-short-drama/维护规范.md#6-依赖获取与适配资料)。随包的三个ComfyUI适配版保留各自 `LICENSE`；第三方技能许可不由本仓库MIT许可证重新授权。

### 本工作区技能与风格资源

[Nora短剧技能](.agents/skills/nora-ai-short-drama/SKILL.md)与[Krea2风格库技能](.agents/skills/krea2-style-library/SKILL.md)由本工作区维护并随仓库提供。Nora由主控、7个业务技能和3个按需打戏专项组成；原18项登记包含4个适配业务技能和14个方法／工具依赖。Krea2技能是独立可选工具。

| 资源 | 来源与作者 |
| --- | --- |
| Clio风格库与预览 | [lumenastrum/clio-style-preview](https://github.com/lumenastrum/clio-style-preview)；风格文本主要来自 [u/Dear-Spend-2865原始分享](https://www.reddit.com/r/StableDiffusion/comments/1uzdj7o/krea_2_styles_wildcards_txt/) |
| Ray Moodboard资源包 | [Ray3780 / Ray Style Switching Extension](https://civitai.com/models/2856809/ray-style-switching-extension)；[发布元数据API](https://civitai.com/api/v1/models/2856809) |
| Moodboard原始来源 | [Krea官方Moodboard介绍](https://www.krea.ai/blog/moodboards-krea-2)、[服务条款](https://www.krea.ai/terms) |

现行资源随仓库保留，实际应用版本及来源下载地址见 [versions.json](工作区浏览服务/Krea2风格库/Krea2_风格资源/versions.json)。第三方授权事项由工作区维护者负责处理；这项分发安排不表示agent已经核实取得全部授权，也不改变原始许可。

### 运行环境与后端来源

- [Python](https://www.python.org/downloads/)：原固定脚本使用3.9及以上标准库；新浏览服务使用3.10及以上和独立虚拟环境，依赖见服务目录。
- [FFmpeg](https://ffmpeg.org/download.html)：本地音视频裁剪、解码及合成依赖；安装与调用统一按[FFmpeg初始化与运行](#ffmpeg初始化与运行)。
- [Node.js](https://nodejs.org/)：浏览服务构建使用22及以上。
- [ComfyUI](https://github.com/Comfy-Org/ComfyUI)：由使用者独立部署的图片／视频生成后端。本仓库携带工作流及[已登记的节点源码或安装包](.agents/skills/nora-ai-short-drama/维护规范.md#comfyui节点与安装包)，不携带模型权重，不自动部署服务端节点或依赖。服务地址与认证按[工作区共用配置](.agents/skills/nora-generation/references/ComfyUI-服务配置与任务提交规范.md#工作区-comfyui-配置)执行；节点、模型与兼容性问题按执行规范处理，这里的技能依赖清单不是后端安装清单。

## 环境

| 用途 | 要求 |
| --- | --- |
| 阅读规则与创作 | 可读写工作区文件的agent；对应阶段按需读取技能 |
| ComfyUI客户端、库存脚本、Krea2更新工具 | Python 3.9及以上，运行脚本仅使用标准库 |
| 本地音视频处理 | FFmpeg；按[初始化与运行规则](#ffmpeg初始化与运行)落实 |
| 本地版本维护 | Git；完成任务后按AGENTS规则提交，推送另需用户要求 |
| GitHub发布 | GitHub账号及仓库权限，可通过插件或已授权的GitHub CLI操作 |
| 浏览风格库和项目页 | 现代浏览器及工作区浏览服务；资源更新另需联网 |
| 浏览服务的Node测试 | 使用下方浏览服务开发环境中的Node.js 22＋运行 `node --test` |
| 工作区浏览服务 | Python 3.10＋及requirements.txt依赖；前端构建使用Node.js 22＋、pnpm 11，普通浏览运行不使用Node；ComfyUI会话通知使用本机Node |
| 技能格式校验 | 使用平台提供的 `skill-creator` 及其校验工具；按工具本身要求准备依赖 |

Python命令示例使用 `python3`；Windows按实际安装可改为 `py -3`。新浏览服务的Windows入口为批处理文件，其他平台按服务README启动。

### FFmpeg初始化与运行

FFmpeg是工作区的本地音视频处理依赖。只在初始化项目工作区时，由agent告知其用途并安装适合当前系统的可执行版本，安装来源使用[FFmpeg官方下载入口](https://ffmpeg.org/download.html)所列的系统安装包或构建。已有明确安装／成功调用记录时复用，不重复安装；多部短剧共用本机安装，不在每个项目内复制程序。

初始化完成后，将实际调用命令或可执行文件的绝对路径记入工作区 `综合资料/工作区本机运行环境.md`；这里只保存本机事实，不复制本节规则，程序和本机路径不随公共模板分发。

日常运行默认依赖已经具备，直接使用已记录的调用方式，不先检查程序是否存在、搜索命令或查询版本。实际调用因环境问题报错时，才向用户说明真实错误及受影响的操作；不在运行中自动安装、下载或升级依赖。此项免查指运行环境，不取消素材时长、格式、解码及输出文件的核对。

## 工作区浏览服务

Windows双击 [启动（Windows）.bat](工作区浏览服务/启动（Windows）.bat)，Mac双击 [启动（Mac）.command](工作区浏览服务/启动（Mac）.command)，由系统托管启动后自动打开 `http://127.0.0.1:8782/`。首页自动发现 `projects/` 项目，统一提供项目浏览、Krea2风格库及开发记录。页面打开期间自动检测文件变化，局部更新列表；正在阅读的文档由用户选择切换新版本，不自动整页刷新。局域网使用本机局域网IP加8782端口，风格库管理开放本机及局域网IP地址，保留同源请求和操作凭证校验。双击对应系统的停止脚本结束本工作区服务；关闭Codex或网页不停止服务，不设开机或登录自启。Agent发布重启也走同一托管入口，详见[日常启动](工作区浏览服务/README.md#日常启动)。

首次安装、构建、开发及测试说明见[服务README](工作区浏览服务/README.md)。服务需要Python 3.10＋及项目依赖，前端构建需要Node.js 22＋、pnpm 11；已构建后普通浏览不需要Node.js；ComfyUI后台的Codex会话通知需要本机Node，具体接入见服务README。项目页面由浏览服务读取源资料展示，不再生成或维护项目静态HTML。

## Krea2风格库

从[工作区浏览服务](工作区浏览服务/README.md)的“风格库”进入，提供搜索、分类、预览、提示词复制及资源更新管理。服务的启动、停止与访问方式统一见服务README。

当前资源随工作区提供；检查、准备、审阅差异、应用和恢复均由使用者手动触发，不会自动升级。风格操作与文件结构见[使用说明](工作区浏览服务/Krea2风格库/使用说明.md)，agent检索与维护见[krea2-style-library](.agents/skills/krea2-style-library/SKILL.md)。

## 维护与检查

修改短剧技能前读取其[维护规范](.agents/skills/nora-ai-short-drama/维护规范.md)，使用 `skill-creator`。三个ComfyUI技能只在随包真源中维护，不从远端自动覆盖；吸收上游更新时检查适配差异并保留来源版本和许可证。Krea2的使用与维护规则集中在对应技能，不另设局部AGENTS。

按影响范围选择已有测试，不因普通文档修改运行全部测试。下列命令均在工作区根目录执行：

```sh
# ComfyUI通信客户端：本地测试，不访问生产服务。
python3 -B -m unittest discover -s .agents/skills/nora-ai-short-drama/references/comfyui-scripts -p 'test_*.py'
# 工作流脚本。
python3 -B -m unittest discover -s .agents/skills/nora-ai-short-drama/scripts -p 'test_*.py'
# 项目浏览服务：在该目录执行资料解析、API与同步测试。
(cd 工作区浏览服务 && python3 -X utf8 -B -m unittest discover -s tests -v)
# 仅检查本地画布/API配对，不验证远端兼容性。
python3 -B .agents/skills/nora-ai-short-drama/scripts/workflow_baselines.py
# Krea2：临时目录与本机临时端口测试，不联网更新资源。
python3 -B -m unittest discover -s 工作区浏览服务/Krea2风格库/Krea2_更新工具 -p 'test_*.py'
```

退出码0表示相应检查通过；脚本测试不等于用户批准素材，也不替代涉及交互修改时的浏览器检查。只维护说明且不影响项目数据结构时，不重新生成项目浏览页。

## Git边界

采用 `.gitignore` 排除清单：新增文件和目录默认可被Git发现，无需逐项放行；只有新增不应入库的内容类别时才补充忽略规则。真实项目、综合资料内容、根目录 `.codex/` 本机配置、已明确列出的外部安装技能、历史归档、`state/` 库存缓存及Krea2 `work/` 备份不入库。`projects/` 和 `综合资料/` 仅保留各自README，新增项目和过程资料仍自动排除。可被Git发现不等于自动提交，提交范围仍按本次任务核对。 `.agents/plugins/` 不整目录忽略；其中的配置提交前仍需核对本机路径和实际分发用途。

每次完成获授权维护并通过检查后，agent只为本次任务创建本地提交；纯讨论和只读检查不提交，推送须另有明确要求。提交前查看差异和暂存清单，不混入并发修改。Git只保存被跟踪且已提交的文件；真实项目需另行安排私有版本管理或备份。

作为GitHub模板使用时，新建工作区获得当前目录和文件，但不会自动接收模板后续更新。同步更新前检查本地修改，不要覆盖使用者自己的内容。单独分享Nora技能时同时携带适用的许可证及三个随包依赖的许可证。

## 授权

本工作区原创技能、脚本及文档采用根目录 [MIT许可证](LICENSE)，允许修改、再分发和商用，保留版权及许可声明。

第三方内容不因放入本仓库自动改为MIT：三个ComfyUI适配技能保留各自许可证；Krea2风格文本、预览图及来源限制以对应上游来源的许可声明为准。
