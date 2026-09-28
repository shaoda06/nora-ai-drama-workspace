---
name: comfyui-troubleshooter
description: Diagnose ComfyUI connection errors, rejected workflows, failed executions and image quality issues from actual API responses and task records. Use for ComfyUI troubleshooting; does not automatically restart servers, install models or change approved image specifications.
---

# ComfyUI Troubleshooter

Portable adaptation of [MCKRUZ/ComfyUI-Expert](https://github.com/MCKRUZ/ComfyUI-Expert/tree/dee27dc3d69b609c0006a8a12e71aadfc475ae95/skills/comfyui-troubleshooter). MIT license retained in [LICENSE](LICENSE). Portable adaptation updated 2026-09-26. Discover companion skills by name through the host platform; do not assume a shared parent installation directory.

## Evidence first

Read the actual task workflow, prompt/parameters, submission response, `prompt_id`, history status/messages and output if relevant. Discover `comfyui-api` by name and read its configuration and `foundation/api-quick-ref.md` for the selected endpoint. Obtain hardware from `/system_stats` and capabilities from the cache managed by the installed `comfyui-inventory`; read that skill’s actual cache path and refresh when missing, stale, incomplete or from another endpoint. Neither a project layout nor sibling installation paths are required.

Distinguish a rejected submission, queued/running execution, failed/interrupted execution, missing result and a successful image with visual defects. State known facts and uncertainty before changing anything.

| Evidence | Investigation and scoped remedy |
| --- | --- |
| Cannot reach API | Check selected address, HTTP response and service reachability. Do not assume ComfyUI is stopped or restart it based on a timeout alone. |
| POST /prompt rejected | Inspect `error` and `node_errors`; check required inputs, COMBO values, model selections and link types against the live node schemas. |
| Submission response lost | Check queue/history for the task's unique client ID and saved request before considering another POST; avoid duplicate generation. |
| History is empty | Check `/queue` for this prompt ID; absence from both means unknown, not success or proof it never ran. Preserve identifiers for recovery. |
| Execution error/interruption | Read the exact history message, failing node and exception. Do not report partial outputs as a successful task. |
| Missing node/model | Refresh inventory and verify the exact loader choice. Use the installed `comfyui-api` skill’s `references/models.md` for source verification; do not guess a download URL or install an unrelated package. |
| Out of memory | Check current VRAM, batch, dimensions, model precision and failing node. Prefer a compatible lower-memory execution strategy; do not silently reduce approved pixel dimensions. |
| Wrong size | Trace latent width/height, resizing/cropping nodes and output metadata. Prompt text alone does not set dimensions. |
| Wrong identity/composition | Check actual reference inputs, crop, reference roles and prompt. Fixed seed alone does not ensure identity. Change one relevant factor at a time. |
| Precision/type error | Verify model, encoder, VAE and custom node compatibility from the exact error; do not add generic precision flags blindly. |

Check the actual model, conditioning and sampler implementation before recommending negative prompts or CFG changes. Do not treat settings for another model, extra LoRAs or changed resolutions as universal fixes. Follow the task's confirmed image specification and workflow instructions.

`/interrupt`, queue deletion, `/free` and restart may affect other users' work. Check task ownership and existing authorization before using them; never cancel unrelated jobs as troubleshooting. Installing models/nodes or changing server settings is separate from read-only diagnosis. If additional evidence is needed, request only the relevant error/log snippet. Never post user logs to outside communities automatically.

## Report

Explain the evidence, likely cause, smallest useful correction, checks performed and remaining uncertainty. A diagnosis does not authorize an unbounded series of reruns; preserve existing outputs and task IDs.
