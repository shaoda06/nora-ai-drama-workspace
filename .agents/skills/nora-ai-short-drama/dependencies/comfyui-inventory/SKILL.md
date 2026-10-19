---
name: comfyui-inventory
description: Discover and cache nodes, model filenames and system capabilities from the user's ComfyUI server for explicitly requested inventories or dependency diagnostics; does not install models or modify the server.
---

# ComfyUI Inventory

Portable adaptation of [MCKRUZ/ComfyUI-Expert](https://github.com/MCKRUZ/ComfyUI-Expert/tree/dee27dc3d69b609c0006a8a12e71aadfc475ae95/skills/comfyui-inventory). MIT license retained in [LICENSE](LICENSE). Portable adaptation updated 2026-09-26. Discover companion skills by name through the host platform; do not assume a shared parent installation directory. Uses Python 3.9+ standard library and the remote API; no server filesystem access is required.

## Connection and refresh

For Nora projects, use the [workspace authentication adapter](../../references/comfyui-scripts/README.md#nora-工作区配置与分享边界); configuration and invocation boundaries follow the [submission specification](../../../nora-generation/references/ComfyUI-服务配置与任务提交规范.md#固定通信工具与证据). The command below is for standalone use.

For standalone use, take the address explicitly supplied for the task, then `COMFYUI_URL`, then `http://127.0.0.1:8188`. Localhost means the machine running this script. The caller supplies its selected address; this skill does not require a project layout. Resource paths are relative to this SKILL.md, not the task working directory.

Run [refresh_inventory.py](scripts/refresh_inventory.py):

```sh
python3 "<installed-comfyui-inventory-directory>/scripts/refresh_inventory.py" --url "http://127.0.0.1:8188"
```

Replace the example installation path and URL with the actual resolved values. Pass `--url <address>` for an explicit server and optionally `--output <path>`. Default output is `state/inventory.json` inside this inventory skill’s own directory; it is created at runtime and is not distributed. An explicit `--output` may point to another writable local path; record that path so consumers read the same cache. No adjacent `comfyui-api` directory is required. `last_updated` uses the client machine’s local time with its UTC offset. The script only performs GET requests and writes a local cache. It queries `/system_stats`, `/object_info`, `/models`, then each advertised model category. Failed category reads are recorded as errors, never treated as evidence that no models exist. Core query failure preserves the previous cache and exits with an error. Exit 2 means a partial new cache was written; exit 0 means all queries succeeded.

The optional `--timeout <seconds>` is a positive number, default 30 seconds, applied to blocking network operations for each HTTP request, not a deadline for the entire refresh. Parameter help is available with `python3 "<installed-comfyui-inventory-directory>/scripts/refresh_inventory.py" --help`; normal calls do not require reading the implementation.

Stdout reports JSON: `cache_updated` indicates whether a new cache was saved, `ok` indicates complete success, and a saved-cache result includes `output`, node/model counts and `errors`. Core query failure returns exit 1 with `cache_updated: false` and `error`; argument errors use exit 2 without this JSON. Distinguish those from exit 2 with `cache_updated: true`, which means a partial refresh. Local write failures are reported as errors, not successful cache updates.

## Inventory interpretation

- `source_url`, `last_updated`, `complete`, `errors`: origin, freshness and limits.
- `system_stats`: actual server version and devices; VRAM is a point-in-time reading, not a capacity guarantee.
- `nodes`: registered class names mapped to input/output schemas and module provenance. Registered nodes are not the same as installed package directories.
- `models`: API category to filename list. A filename being listed does not verify checksum, integrity or compatibility. Extra model paths may point outside the default model directory.
- `node_modules`: module names reported by nodes; does not include unregistered or failed-to-import packages.

This skill is an explicit inventory/diagnostic tool, not a prerequisite for ordinary uploads or generation submissions. Workspace preparation and submission tools assume the selected remote can execute the supplied workflow; they do not query or refresh its capability library. Remote execution reports unsupported nodes/models/parameters, and the submission tool preserves and returns those errors to the Agent without automatic resubmission. Only perform an inventory refresh when the user explicitly requests a capability inventory or the current authorized diagnostic task requires it. Cached inventories do not expire automatically after one hour; source_url and last_updated remain factual, and reused/partial data must not be described as a complete live query.

## Workflow check

For every API node, check `class_type` against `nodes`; check required inputs, links, output slots/types and model filenames against that loader's schema. COMBO choices can be either a list as the first schema element or `COMBO` with an `options` list. Model-list categories and loader choices may use different aliases; the loader's live choices are decisive. Do not assume every two-element list is a link when the input accepts literal arrays.

For missing models, discover `comfyui-api` by name and read its `references/models.md`; for failures discover `comfyui-troubleshooter`. Resolve resources against the skill location returned by the host, not a presumed sibling path. If the API is unavailable, report the connection error and cache timestamp; do not scan the client machine and describe it as the remote server installation. Offline filesystem discovery requires an explicitly accessible installation path and a separate scoped task.
