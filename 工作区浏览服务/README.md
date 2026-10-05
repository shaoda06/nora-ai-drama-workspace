# Nora 工作区浏览服务

版本：0.1.0。项目浏览、Krea2风格库和开发记录共用一个入口，源文件仍是内容依据。

## 日常启动

Windows双击本目录的 `启动工作区浏览服务.bat`，后台运行并自动打开 http://127.0.0.1:8782/ 。重复双击复用已经运行的本工作区服务。关闭网页不停止后台；双击 `停止工作区浏览服务.bat` 停止，关机后需再次启动，不设开机自启。日志位于 `runtime/server.log`。端口被其他程序占用时明确报错，不终止其他进程。

同一局域网设备访问 `http://本机局域网IP:8782/`。当前机器地址为 `http://192.168.10.15:8782/`，地址随网络可能变化。只读浏览无需登录，风格库更新、应用和恢复仅允许本机回环地址及同源请求。局域网HTTP可能无法使用自动剪贴板，页面提供可选中的文本供手动复制。

## 安装与构建

当前工作区已安装依赖并构建。其他电脑首次使用，在本目录执行以下命令；Python 3.10＋、Node.js 22＋、pnpm 11为开发环境要求，日常启动仅使用 `.venv` 和已构建前端。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend build
```

前端或后端代码修改后重新构建前端并停止、启动服务；项目Markdown、素材和记录变化不需要重启或执行生成脚本。macOS／Linux在创建 `.venv`、安装依赖及构建后，可手动执行 `.venv/bin/python -m uvicorn backend.main:app --host 0.0.0.0 --port 8782`，本版双击入口为Windows提供。

## 模块与数据

```text
工作区浏览服务/
├── 启动工作区浏览服务.bat
├── 停止工作区浏览服务.bat
├── backend/
│   ├── main.py                # API与前端发布入口
│   ├── parsers/project.py     # 服务和离线页共用的项目解析器
│   └── services/              # 项目变化检测、Krea2更新适配
├── frontend/src/             # React组件、项目页、风格页、开发记录
├── Krea2风格库/               # 完整原工具与资源，保持相对位置
├── scripts/launcher.py       # 启动、复用和停止本工作区服务
├── tests/                    # API、变化检测与访问边界测试
├── docs/                     # 开发计划、版本记录、详细开发记录
└── runtime/                  # 本机日志及验证附件，不入Git
```

- 首页每5秒发现项目目录，项目页每5秒查询变化。后端比较文件路径、修改时间和大小；有变化时后台重新解析，失败保留上次完整结果并显示错误。首次打开大项目需要一次完整解析；不是逐栏目只读取磁盘。API按当前栏目、资料卡、文档分别发送，首页不含全部项目正文。
- 自动更新保持选中的栏目、搜索、展开目录及已打开的媒体。已打开正文有变化时提示“读取新版本”，用户选择后切换，不重载整页。没有打开页面时不运行项目扫描；下次进入检查变化。
- 人物、场景、道具及剧集目录沿用已有解析规则和审核原文，不迁移创作文件、不补造采用事实。媒体按路径提供，支持Range读取，视频与音频手动播放。
- Krea2目录整体迁入，3947项资源保留。新界面复用原更新程序，保留Clio／Ray独立检查、准备差异、应用、放弃与恢复上一版。更新仍是用户手动触发，不自动下载或升级。`work/` 的准备包和上一版保留，但不入Git。
- 原技能 `scripts/build_project_portal.py` 保持命令，调用共用解析器按需导出 `项目总览.html`。离线页仍是快照，使用它时需重新导出；服务不为每次编辑重写静态页。
- 开发记录使用Markdown源文档，网页只读显示；Git保存代码修改，`docs/开发记录/` 说明原因、实现、检查和剩余事项，`docs/版本记录.md` 跟踪发布功能。不把开发记录写入短剧项目进度。

页面和公共组件的实际组成、复用关系及样式约定见[组件与页面实现](docs/组件与页面实现.md)。新增页面先检查此清单，同用途优先复用已有组件。

## 开发与验证

```powershell
.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8781
pnpm --dir frontend dev
.venv/Scripts/python.exe -m unittest discover -s tests -v
python -X utf8 -B -m unittest discover -s ../.agents/skills/nora-ai-short-drama/scripts -p test_project_portal.py
node --test ../.agents/skills/nora-ai-short-drama/scripts/test_project_portal_ui.mjs
python -X utf8 -B -m unittest discover -s Krea2风格库/Krea2_更新工具 -p 'test_*.py'
pnpm --dir frontend build
```

测试资源更新使用临时目录，不执行真实上游应用或恢复。浏览器验证与检查结果见[开发记录](docs/开发记录/W001-工作区服务首版.md)。
