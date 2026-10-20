# 导演台 × YZ文武双全 SelfLift 测试画布

状态：实验稿；未替换正式工作流，未提交生成。

实验画布：导演台管理素材、提示词和分组；模型链沿YZ金鱼《终极篇·文武双全》。

使用放大权重：minimax_h3_latent_upscaler_3d_fp16_V2.safetensors。远端已识别该权重。

在导演台第一组添加参考素材并填写提示词。参考图最长边1536，保持原比例；新增或导入分组也设为1536。导演台界面时长12秒，对应294帧／实际12.25秒；目标1664×928、24fps。

SelfLift采用Simple完整12步，`split_mode=transition_step`、`transition_step=6`、`highres_steps=6`、`lowres_scale=0.6`、`latent_upsample=nearest`；rho=0，不接额外Refine。

| 阶段 | 配置对应的分辨率 | 采样步数 |
| --- | --- | --- |
| 低清前段 | 992×544 | 前6步 |
| 高清后段 | 1664×928 | 后6步 |

低清尺寸按高清画布的0.6倍率及×32对齐计算，由SelfLift自动确定，不是另设独立画布；以上不是视频运行实测。BasicScheduler与导演台步数均为12，命名控件和序列控件保持一致。

## 武打与运动LoRA组

画布B组以下四个节点全部启用（mode=0），按所列权重串入模型链；前后两阶段共用该模型，未另接model_hires。原版文件中这四个节点处于旁路，本测试配置将它们启用。

| LoRA文件 | 权重 | 用途／状态 |
| --- | --- | --- |
| `H3_Combat_V2.safetensors` | 0.65 | Combat打斗；已启用 |
| `minimax_h3\Motion_Repair_V2.safetensors` | 0.35 | 运动修复；已启用 |
| `H3_Fight_Flow_V1.safetensors` | 0.35 | 打斗衔接；已启用 |
| `H3_speed_slider_1.1.safetensors` | 3.0 | 速度控制；已启用 |

固定作者当前种子，便于同素材、同提示词切换节点38的INT8／NVFP4编码器作对照。

此处使用导演台自带SelfLift实现，并非作者外部SelfLiftH3Sampler的逐像素复现；插值和缓存／卸载由导演台实现管理。未提交生成，不能据此声称速度或画质已验证。

## 来源与参数

- 作者工作流：`YZ金鱼-MiniMax H3 终极篇-文武双全.json`，工程ID `eee7ca4f-9198-48dd-b48a-80b3f7191873`。
- 导演台原生模块：[MiniMaxH3DirectorSelfLift](https://github.com/AIMixer/ComfyUI_MiniMaxH3_Director/blob/4c6245e518dd8a494f3afc4f3cccd53f22d82d10/nodes/director_selflift.py)。
- 底模与两类VAE、DMAD 0.8、MysticXXX 0.35、NVFP4 AWQ、Kitchen＋sol-attn、Shift 12/3、前馈2块、H.264 CRF19沿作者设置；Simple采样为12步（前6后6）。
- 未使用Turbo v4、TE-Speed、SplitSigmas或额外Refine。
- 作者的ResolutionSelector 1.5MP解析值1664×928已填入导演台；作者时长公式解析为294帧，实际12.25秒。
- 仅用导演台原生素材组；不接外部r2v_groups覆盖素材管理。测试组为空，填入自己的素材和提示词后再运行。

## 编码器比较

INT8 ConvRot和NVFP4 AWQ是同一32B编码器的不同量化版本。NVFP4模型更紧凑；在当前RTX4090上未实测编码耗时、峰值显存或视频质量，不宣称一定更快或更好。官方说明NVFP4文本编码器可以在非Blackwell设备使用。只切换节点38，其余素材、提示词、种子和参数保持一致，才便于比较。

## 验证范围

- 本地API按结构和执行参数检查，不比较画布与API。20个画布节点包含1个说明节点，API有效节点19个；4个武打与运动LoRA均在有效API模型链中。
- BasicScheduler和导演台均设为12步，SelfLift在第6步后由992×544低清转入1664×928高清；低清尺寸按倍率0.6与×32网格计算，不是运行实测。
- 本地静态检查不代表目标服务器已加载LoRA或完成视频生成。未更改或重新验证远端节点、模型安装与远端保存画布。
- 放大权重：`ComfyUI/models/latent_upscale_models/minimax_h3_latent_upscaler_3d_fp16_V2.safetensors`。

## 与原版的对应与差异

| 项目 | 对应关系 |
| --- | --- |
| 底模与VAE | 相同：INT8 H3底模、INT8视频VAE、FP32音频VAE |
| 编码器 | 相同：Qwen3-VL 32B NVFP4 AWQ，minimax类型 |
| 基础LoRA | 相同：DMAD v4 0.8、MysticXXX 0.35 |
| 武打与运动LoRA | 文件、权重与串联顺序相同；原版4个旁路，本测试4个全部启用 |
| 注意力与Shift | 相同：Kitchen、sol-attn及其参数，Shift 12/3 |
| 前馈分块 | 相同：2块，阈值4096 |
| 分辨率与帧率 | 相同：1664×928、24fps；低清0.6倍率对应992×544 |
| 采样 | 相同：Euler、Simple 12步、CFG 1、前6后6 |
| 提升参数 | 相同：V2潜变量放大模型、rho=0、w_min=0.5、w_max=1、高清分块关闭 |
| SelfLift实现 | 原版外部`SelfLiftH3Sampler`；本测试为导演台配套`MiniMaxH3DirectorSelfLift`。接口与内部实现不同，不声明逐像素等同 |
| 插值 | 相同：nearest最近邻；原版采样器内固定使用，本测试在SelfLift控件中显式设置 |
| 种子控制 | 起始种子数值相同；原版randomize，本测试fixed，便于同输入对照 |
| 素材、条件与导出 | 原版外接参考输入、零条件节点及音视频解码；本测试由导演台管理。输出命名与缓存机制不同；H.264、CRF19、yuv420p及24fps相同 |

## 原版采样器的接入边界

当前`MiniMaxH3Director`的输出是已采样的图像、音频及报告，没有原版`SelfLiftH3Sampler`所需的`CONDITIONING`和`LATENT`。它的`selflift`输入接收的是`MMX_DIR_SELFLIFT`配置包，不是外部采样器或采样后的潜变量，不能直接互换节点。

同插件的`MiniMaxH3DirectorConditioning`可以输出条件和潜变量，但不读取当前导演台的公共区、分组素材和时间线，也不提供该分组管理界面，不能只替换名称就保留原有功能。

要保留导演台素材／提示词／分组界面并由原版节点采样，需要额外实现“分组数据→原版条件与潜变量”的导出适配，并对齐公共和本组素材合并、选中组、时长与逐组执行。当前备用画布尚未实现这条外部采样链，不将内置SelfLift标注为原版节点。节点接口依据：[导演台](https://github.com/AIMixer/ComfyUI_MiniMaxH3_Director/blob/4c6245e518dd8a494f3afc4f3cccd53f22d82d10/nodes/director.py)、[Conditioning](https://github.com/AIMixer/ComfyUI_MiniMaxH3_Director/blob/4c6245e518dd8a494f3afc4f3cccd53f22d82d10/nodes/conditioning.py)。

## 编码器的已知依据

官方仓库当前文件大小：INT8 ConvRot为27,141,342,152字节，约25.28GiB；NVFP4 AWQ为15,687,142,551字节，约14.61GiB。文件体积不等于运行时峰值显存。NVFP4文本编码器可以在非Blackwell设备使用，但当前4090不能据此假定获得原生NVFP4算力加速。未找到两种编码器在同条件H3视频上的可靠质量排名。

- [官方模型说明](https://huggingface.co/Comfy-Org/MiniMax-H3)
- [官方编码器文件](https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/text_encoders)
- [Comfy Kitchen量化布局与硬件要求](https://github.com/Comfy-Org/comfy-kitchen#quantized-tensors)

## 远端测试画布

- 保存位置：`01-自用/02-视频生成/Nora-测试-导演台-YZ文武双全-SelfLift-20261018.workflow.json`。
- 这是独立的远端副本；本地修改不会自动更新它。使用当前配置时加载本地画布，不把该远端旧副本当作本地最新版。

## 打开画布

使用完整加载的导演台前端，确认素材组界面可见、数值控件正常后使用。若脚本加载失败曾造成参数错位，刷新后关闭测试画布的异常草稿且不保存，再从远端列表重新打开保存文件。界面时长使用12秒，不将实际时长12.25秒反填到durationSec，否则前端会再次向上对齐帧数。
