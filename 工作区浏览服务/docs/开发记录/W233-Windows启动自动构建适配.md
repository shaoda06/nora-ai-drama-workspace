# W233 Windows启动自动构建适配

日期：2026-10-19。基于d78b8d3f的启动前自动构建逻辑，只补齐Windows入口与共用启动器；本次只准备代码并本地提交，不发布、不构建正式前端、不重启Mac的8782服务，版本仍为0.6.97。

## 问题与处理

- Windows分支明确查找`npm.cmd`，继续通过shell调用已有`npm --prefix <frontend> run build`，版本判断不复制到批处理或PowerShell。构建命令、工作目录与任务路径保留为独立参数或环境变量，覆盖含中文及空格的目录。
- `pythonw`没有控制台，子命令统一使用空标准输入、捕获输出和Windows无窗口标志；非UTF-8的系统错误输出使用替换解码，避免错误反馈自身因解码失败而中断。构建失败仍在停止服务之前抛错。
- Windows错误弹窗改用系统自带的`MessageBoxW`，不依赖Tk。双击批处理等待启动器退出；失败保留提示及非零退出码。`--no-browser`继续向命令行报告错误。构建版本清单的JSON读取错误也进入错误反馈。
- PowerShell调用改为UTF-16LE的`-EncodedCommand`，避免内嵌脚本的引号经过命令行再次解释；目录、端口及动作仍由环境变量传递。
- 启动等待同时核对目标版本与`ready=true`。此前模拟返回旧版本的`ready=true`时会提前结束等待，新增回归在修复前失败、修复后通过。

## 任务计划程序核对

`scripts/windows_service.ps1`已有逻辑符合要求，本次不修改其注册定义：按当前用户SID及端口命名；核对账号、Python路径、带引号的脚本参数及工作目录后才操作已有任务；系统任务只运行`serve`，不承担版本判断或构建；没有开机、登录、定时或自动重启触发。保持已有动作参数不变，避免正常的已注册任务因参数变化被误判为其他目录。注册失败向启动器抛错，不直接启动工作进程。

同版本就绪服务直接复用；旧版本服务在构建成功后经原托管路径重启。保留现有端口及服务身份核验，不接管其他程序、不安装或升级依赖。

## 检查结果

在Mac的服务虚拟环境中执行，未访问正式生成服务或改动项目资料、ComfyUI配置：

```sh
TMPDIR=/private/tmp .venv/bin/python -X utf8 -B -m unittest tests.test_launcher tests.test_release -q
```

共31项：30项通过，1项Windows专用测试跳过。覆盖构建缺失／版本过期、同版本免构建、失败保留旧进程、构建后重启、同版本复用、其他端口不接管，以及新增的Windows npm调用参数、中文及空格路径、无控制台子命令参数、PowerShell编码与环境变量、原生错误弹窗、Agent错误输出、托管失败不绕过系统启动、目标版本就绪等待。

新增`test_real_cmd_build_in_unicode_and_spaced_directory`只在Windows运行：在临时中文及空格目录中创建替身`npm.cmd`，通过真实`cmd.exe`验证参数传递、构建产物及失败退出码，不安装Node、不注册系统任务、不连接正式端口。当前Mac已明确跳过，不能视为Windows实机通过。

扩大检查执行了全部Python测试。默认Mac临时目录的`/var`与`/private/var`别名造成大量路径断言及范围检查失败；改用`TMPDIR=/private/tmp`后，共680项：676项通过、3项跳过、1项失败。剩余失败是`tests.test_completion_delivery.CompletionDeliveryTests.test_restart_restores_pending_notice_and_does_not_resend_unknown_delivery`，在第276行期望`adapter.call_count == 2`，实际为1；单独运行也失败，该测试不调用启动器。本次没有修改通知实现或该测试，也不将全套回归标为通过。

## Windows实机验收缺项

当前设备无Windows、PowerShell或Wine，以下尚未实测：

1. 双击批处理，经真实`pythonw`完成npm构建、注册任务并打开网页；同版本再次双击复用原进程。
2. 在中文及空格目录运行上述Windows专用测试，并使用真实Node/npm构建一次。
3. 缺少npm或真实构建失败时显示具体错误，原服务进程继续运行；同版本已构建时无需npm。
4. 已注册任务的目录和账号核验、旧服务构建后接续、任务计划程序拒绝访问时的错误反馈，以及退出启动窗口／Codex后的托管存活。

这些缺项需要Windows设备验收，隔离模拟与代码核对不能替代系统行为实测。
