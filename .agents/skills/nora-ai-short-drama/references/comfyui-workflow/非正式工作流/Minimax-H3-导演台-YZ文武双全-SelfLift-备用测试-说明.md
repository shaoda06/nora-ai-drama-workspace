# 导演台 × YZ文武双全 SelfLift 测试画布

状态：实验稿；未替换正式工作流，未提交生成。

实验画布：导演台管理素材、提示词和分组；模型链沿YZ金鱼《终极篇·文武双全》。

使用放大权重：minimax_h3_latent_upscaler_3d_fp16_V2.safetensors。远端已识别该权重。

在导演台第一组添加参考素材并填写提示词。参考图策略max。导演台界面时长12秒，对应294帧／实际12.25秒；目标1664×928、24fps。

SelfLift：前6步低清，倍率0.6；后4步高清；总计10步；rho=0；不接额外Refine。四个武打／修复／速度LoRA沿作者旁路。

固定作者当前种子，便于同素材、同提示词切换节点38的INT8／NVFP4编码器作对照。

此处使用导演台自带SelfLift实现，并非作者外部SelfLiftH3Sampler的逐像素复现；插值和缓存／卸载由导演台实现管理。未提交生成，不能据此声称速度或画质已验证。

## 来源与参数

- 作者工作流：`YZ金鱼-MiniMax H3 终极篇-文武双全.json`，工程ID `eee7ca4f-9198-48dd-b48a-80b3f7191873`。
- 导演台原生模块：[MiniMaxH3DirectorSelfLift](https://github.com/AIMixer/ComfyUI_MiniMaxH3_Director/blob/4c6245e518dd8a494f3afc4f3cccd53f22d82d10/nodes/director_selflift.py)。
- 底模与两类VAE、DMAD 0.8、MysticXXX 0.35、NVFP4 AWQ、Kitchen＋sol-attn、Shift 12/3、前馈2块、H.264 CRF19沿作者设置；Simple采样设为10步（前6后4）。
- 未引入本地标准版的Turbo v4、TE-Speed、SplitSigmas或额外Refine。
- 作者的ResolutionSelector 1.5MP解析值1664×928已填入导演台；作者时长公式解析为294帧，实际12.25秒。
- 仅用导演台原生素材组；不接外部r2v_groups覆盖素材管理。测试组为空，填入自己的素材和提示词后再运行。

## 编码器比较

INT8 ConvRot和NVFP4 AWQ是同一32B编码器的不同量化版本。NVFP4模型更紧凑；在当前RTX4090上未实测编码耗时、峰值显存或视频质量，不宣称一定更快或更好。官方说明NVFP4文本编码器可以在非Blackwell设备使用。只切换节点38，其余素材、提示词、种子和参数保持一致，才便于比较。

## 验证范围

- 现有离线配对校验与技能校验通过。20个画布节点包含4个旁路LoRA和1个说明节点，API有效节点15个。
- 对照当前主节点schema，15个API节点均已注册，18条有效连线的类型和槽位已核对。
- 当前远端节点列表已识别SelfLift的V2权重；文件可选不等于模型加载或生成已通过。
- 浏览器重新打开检查通过：导演台素材组界面正常，40个数值控件均为有限数值；实际帧数保持294帧。未启动生成。
- 权重目录：`ComfyUI/models/latent_upscale_models/minimax_h3_latent_upscaler_3d_fp16_V2.safetensors`。模型实际加载及视频效果仍须后续测试。
- 没有安装插件、下载模型、重启服务器或提交生成。

## 编码器的已知依据

官方仓库当前文件大小：INT8 ConvRot为27,141,342,152字节，约25.28GiB；NVFP4 AWQ为15,687,142,551字节，约14.61GiB。文件体积不等于运行时峰值显存。NVFP4文本编码器可以在非Blackwell设备使用，但当前4090不能据此假定获得原生NVFP4算力加速。未找到两种编码器在同条件H3视频上的可靠质量排名。

- [官方模型说明](https://huggingface.co/Comfy-Org/MiniMax-H3)
- [官方编码器文件](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/text_encoders)
- [Comfy Kitchen量化布局与硬件要求](https://github.com/Comfy-Org/comfy-kitchen#quantized-tensors)

## 远端测试画布

- 保存位置：`01-自用/02-视频生成/Nora-测试-导演台-YZ文武双全-SelfLift-20261018.workflow.json`。
- 已通过 ComfyUI 用户文件接口另存，并回读核对与本地画布一致；未启动生成。

## 打开画布

使用完整加载的导演台前端，确认素材组界面可见、数值控件正常后使用。若脚本加载失败曾造成参数错位，刷新后关闭测试画布的异常草稿且不保存，再从远端列表重新打开保存文件。界面时长使用12秒，不将实际时长12.25秒反填到durationSec，否则前端会再次向上对齐帧数。
