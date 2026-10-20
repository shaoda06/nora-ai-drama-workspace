---
name: comfyui-troubleshooter
description: Diagnose ComfyUI connection errors, rejected workflows, failed executions and image quality issues from actual API responses and task records. Use for ComfyUI troubleshooting; does not automatically restart servers, install models or change approved image specifications.
---

# ComfyUI Troubleshooter

Portable adaptation of [MCKRUZ/ComfyUI-Expert](https://github.com/MCKRUZ/ComfyUI-Expert/tree/dee27dc3d69b609c0006a8a12e71aadfc475ae95/skills/comfyui-troubleshooter). MIT license retained in [LICENSE](LICENSE). Portable adaptation updated 2026-09-26. Discover companion skills by name through the host platform; do not assume a shared parent installation directory.

## Evidence first

Start with the existing task status/report and the exact error to identify the failing stage. Read only the workflow nodes, prompt/parameters, submission response, `prompt_id`, history messages or output needed to resolve that failure; reuse evidence already available for the same inputs. State known facts and uncertainty before changing anything.

For Nora tasks, read the relevant [recovery case](../../../nora-generation/references/ComfyUI-任务监控规范.md#31-异常检查与连接恢复) when handling an execution or collection failure, using the existing task identity and retry state. Local file or permission failures proceed to the local-save row below; remote communication rules are selected only when that investigation needs a remote request. Media content inspection follows the calling workflow's viewing authorization.

## Choose the required dependency

- **Remote protocol or authenticated request needed**: read the selected `comfyui-api` configuration and `foundation/api-quick-ref.md`. Nora follows [workspace diagnostics](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#固定通信工具与证据) and uses the bundled [API entry](../comfyui-api/SKILL.md#configuration) and [protocol reference](../comfyui-api/foundation/api-quick-ref.md); other installations discover the actual skill by name. Inspect the reported node via `/object_info/{class_type}` for a specific schema mismatch, without loading the full catalog.
- **Memory or hardware diagnosis**: obtain `/system_stats` only when the failure requires current hardware/VRAM evidence; combine it with the actual task dimensions, batch and precision.
- **Capability inventory or dependency diagnosis needed within the authorized task**: Nora uses the bundled [inventory entry](../comfyui-inventory/SKILL.md); other installations discover it by name. Read its actual cache path, source endpoint, completeness and timestamp. Reuse relevant valid data; refresh only when this diagnosis needs evidence missing from the cache, affected by a known change, incomplete for the question or from another endpoint. A cache timestamp alone does not require a refresh, and routine diagnosis does not require inventory. Follow the inventory skill's documented refresh and partial-result handling.
- **Model source verification needed**: read the selected API skill's `references/models.md` (Nora: [model reference](../comfyui-api/references/models.md)). Source verification does not authorize installation.

## Investigate the failure

Distinguish a rejected submission, queued/running execution, failed/interrupted execution, missing result and a successful image with visual defects. Use the matching row; combine rows only when the evidence shows multiple failures.

| Evidence | Investigation and scoped remedy |
| --- | --- |
| Cannot reach API | Check selected address, HTTP response and service reachability. Do not assume ComfyUI is stopped or restart it based on a timeout alone. |
| POST /prompt rejected | Inspect `error` and `node_errors`; check required inputs, COMBO values, model selections and link types against the reported node's live schema. |
| Submission response lost | Check queue/history for the task's unique client ID and saved request before considering another POST; avoid duplicate generation. |
| History is empty | Check `/queue` for this prompt ID; absence from both means unknown, not success or proof it never ran. Preserve identifiers for recovery. |
| Execution error/interruption | Read the exact history message, failing node and exception. Do not report partial outputs as a successful task. |
| Missing node/model | Check the reported node or loader choice first. If the authorized dependency diagnosis needs inventory, use the branch above and refresh only the evidence needed. Use the model reference for source verification; do not guess a download URL or install an unrelated package. |
| Out of memory | Check current VRAM, batch, dimensions, model precision and failing node. Prefer a compatible lower-memory execution strategy; do not silently reduce approved pixel dimensions. |
| Download or local save failure | Read the failed output's mapping, HTTP or filesystem error, saved-file evidence and retry state. For network failures use the selected endpoint's protocol and the calling workflow's collection policy; for disk, permission or path errors inspect the local target. Preserve successful files and task IDs; collection recovery is not a new generation. |
| Wrong size | Trace latent width/height, resizing/cropping nodes and output metadata. Prompt text alone does not set dimensions. |
| Wrong identity/composition | Check actual reference inputs, crop, reference roles and prompt. Fixed seed alone does not ensure identity. Change one relevant factor at a time. |
| Precision/type error | Verify model, encoder, VAE and custom node compatibility from the exact error; do not add generic precision flags blindly. |

Check the actual model, conditioning and sampler implementation before recommending negative prompts or CFG changes. Do not treat settings for another model, extra LoRAs or changed resolutions as universal fixes. Follow the task's confirmed image specification and workflow instructions.

`/interrupt`, queue deletion, `/free` and restart may affect other users' work. Check task ownership and existing authorization before using them; never cancel unrelated jobs as troubleshooting. Installing models/nodes or changing server settings is separate from read-only diagnosis. If additional evidence is needed, request only the relevant error/log snippet. Never post user logs to outside communities automatically.

## Report

Explain the evidence, likely cause, smallest useful correction, checks performed and remaining uncertainty. A diagnosis does not authorize an unbounded series of reruns; preserve existing outputs and task IDs.
