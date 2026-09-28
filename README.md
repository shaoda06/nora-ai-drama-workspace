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

第三方内容不因放入本仓库自动改为MIT：三个ComfyUI适配技能保留各自许可证；Krea2风格文本、预览图及来源限制以[第三方说明](Krea2风格库/THIRD_PARTY_NOTICES.md)为准。公开发布包含第三方资源的仓库前，应完成该说明列出的授权核实。
