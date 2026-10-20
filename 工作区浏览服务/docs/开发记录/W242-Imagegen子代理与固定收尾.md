# Imagegen子代理与固定收尾

状态：实现与定向检查完成；真实子代理生图、脚本收尾及父代理回传通过。

## 实现

主控准备完整提示词及当前输入，用固定脚本prepare生成既有图片模板中的生成条目、实际提示词文件和交接清单。执行子代理固定gpt-6-luna／medium，fork_turns为none，不复制主控历史、不重新创作、不自动重试或切换能力。实际Imagegen结果由同一子代理调用complete接续；脚本不调用生图模型、不加入ComfyUI队列，也不编造远端任务或上传凭据。

本地原生图复制原字节，记录真实尺寸和来源；使用已有图片审阅模板和共用记录应用函数建立待确认审阅，再用共用网页候选入口核验。原生尺寸不同于正式目标不作为文件失败；不提前裁图、缩放或登记采用。提示词不符、文件不可解码、候选冲突及用户记录并发修改均停止。父代理收到现成报告后交付，不重复登记和网页扫描。生图失败可用fail留证，report只读现成结果；网页核验失败允许恢复同次收尾，不重新生成。

共享浏览代码仅提取既有图片更新应用和图片入口核验函数供固定脚本复用，没有增加网页接口、组件或共享队列任务种类。脚本使用已有浏览服务Python环境，直接加载当前代码；本功能不要求重启或发布网页，不改前端版本。

## 检查与实测

- 193项相关回归通过，覆盖Imagegen准备／完成／失败／只读报告、四种既有记录模板、无Qwen种子的已批准输入、实际网页解析、重复调用及用户反馈保留，以及原有远端图片装配、收尾、提交边界、恢复和通知。
- 两个技能结构校验通过，三个修改规则文件124处本地链接及章节引用检查通过，差异格式检查通过。
- 实际启动固定组合、独立上下文的生图子代理，内置Imagegen只调用一次，返回1672×941 PNG。父代理在其执行时继续实现工作，子代理结果自动交回父代理。
- 使用独立runtime测试项目；同一子代理运行固定complete后返回completed、user_message_ready=true、browser verified。保存原图尺寸，不自动超分或批准。该测试核验独立项目的实际网页解析器，不表示生产网站新增测试项目，不改真实剧集资产。
- 首次收尾命令因子代理抄漏长路径中的一个目录段而返回FileNotFoundError，未追加生图。父代理提供完整可复制命令并明确授权修正收尾后成功。执行规则要求直接使用交接路径及完整命令，不重组长目录。
- 额外扩展到视频下载重试套件时，test_director_final_outputs_share_retry_policy_and_skip_successful_file失败；将本次涉及的图片收尾函数切回Git原提交实现后同样复现，属于既有视频测试问题。本任务没有修改视频下载重试实现或测试，也不将该扩展套件记为全部通过。

回归命令（浏览服务目录，临时项目与模拟远端，不重新生图）：

```sh
TMPDIR=/private/tmp .venv/bin/python -B -m unittest tests.test_imagegen_results tests.test_image_closeout tests.test_submission_plans tests.test_submission_boundary tests.test_submission_lifecycle tests.test_image_notifications tests.test_completion_delivery tests.test_result_reuse tests.test_result_closeout tests.test_upload_source_stamps -q
```

实际生图测试记录保存在本机runtime/imagegen-smoke-*中，不随技能或仓库分发；工具原生文件保留在该子代理专属生成目录。工作区中其他会话的H3工作流和规则修改不属于本次任务。
