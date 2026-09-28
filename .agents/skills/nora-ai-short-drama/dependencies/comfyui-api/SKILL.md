---
name: comfyui-api
description: Connect to a running ComfyUI instance, queue workflows, monitor execution, and retrieve results. Supports both online (REST API) and offline (JSON export) modes. Use when executing ComfyUI workflows or checking server status.
metadata: {"openclaw":{"emoji":"🔌","os":["darwin","linux","win32"],"requires":{"anyBins":["curl","wget"]},"primaryEnv":"COMFYUI_URL"}}
---

# ComfyUI API Skill

Connect to ComfyUI's REST API to execute workflows, monitor progress, and retrieve outputs.

Portable adaptation of [ComfyUI-Expert](https://github.com/MCKRUZ/ComfyUI-Expert/tree/dee27dc3d69b609c0006a8a12e71aadfc475ae95/skills/comfyui-api). MIT license retained in [LICENSE](LICENSE). Portable adaptation updated 2026-09-26. Discover companion skills by name through the host platform; do not assume a shared parent installation directory. Relative resource paths resolve against this skill directory, not the task working directory.

## Configuration

- **Default URL**: `http://127.0.0.1:8188` (the machine running the API client)
- **Custom URL**: An address explicitly supplied for the current task takes precedence, followed by `COMFYUI_URL` if set, then the default above. Resolve the address before calling the API. A calling project should pass its selected configuration explicitly; this skill does not read a specific project layout. Set `COMFYUI_URL` to that resolved address for the examples below; they show localhost only as a placeholder default.
- **Timeout**: 30s per HTTP request. Generation monitoring uses the task’s agreed cadence and limits; it is separate from an individual request timeout.

## Two Modes

### Online Mode (ComfyUI Running)

Full API access. Preferred mode for interactive work.

1. **Test connection**: `GET /system_stats`
2. **Discover capabilities**: Use `comfyui-inventory`
3. **Queue workflow**: `POST /prompt`
4. **Poll for results**: `GET /history/{prompt_id}` every 5 seconds
5. **Retrieve outputs**: `GET /view?filename=...`

### Offline Mode (No Server)

Export workflow JSON for manual loading in ComfyUI.

1. Generate workflow JSON following ComfyUI's format
2. Save to the task-authorized output directory. Follow the project skill's paths when applicable.
3. Distinguish UI format for canvas import from API execution format. Report that no remote execution occurred.

## API Operations

### Check Server Status

```bash
COMFYUI_URL="http://127.0.0.1:8188" # replace with the resolved task endpoint
curl --max-time 30 "$COMFYUI_URL/system_stats"
```

**Response fields:**
- `system.os`: Operating system
- `system.comfyui_version`: Version string
- `devices[0].name`: GPU name
- `devices[0].vram_total`: Total VRAM bytes
- `devices[0].vram_free`: Free VRAM bytes

### Queue a Workflow

```bash
curl --max-time 30 -X POST "$COMFYUI_URL/prompt" \
  -H "Content-Type: application/json" \
  --data-binary @request.json
```

`request.json` is the saved task request containing `prompt` (the validated API graph) and a unique `client_id`. Do not retry this POST automatically after a timeout.

**API graph structure example only** (incomplete; replace model and prompt placeholders and validate the actual graph before submission):
```json
{
  "1": {
    "class_type": "CheckpointLoaderSimple",
    "inputs": {
      "ckpt_name": "__MODEL_FILE__.safetensors"
    }
  },
  "2": {
    "class_type": "CLIPTextEncode",
    "inputs": {
      "text": "__TASK_PROMPT__",
      "clip": ["1", 1]
    }
  }
}
```

Each node is keyed by a string ID. Inputs reference other nodes as `["{node_id}", {output_index}]`.

**Response:**
```json
{"prompt_id": "abc-123-def", "number": 1}
```

### Poll for Completion

```bash
curl --max-time 30 "$COMFYUI_URL/history/abc-123-def"
```

**Empty history**: May be queued, running or unavailable; check this prompt ID in `/queue`. Do not treat empty history as completion.
**History present**: Inspect completed/success status and errors before downloading. Example successful output:
```json
{
  "abc-123-def": {
    "outputs": {
      "9": {
        "images": [{"filename": "ComfyUI_00001.png", "subfolder": "", "type": "output"}]
      }
    },
    "status": {"completed": true, "status_str": "success"}
  }
}
```

### Retrieve Output Image

```bash
curl --max-time 30 "$COMFYUI_URL/view?filename=ComfyUI_00001.png&subfolder=&type=output" -o output.png
```

### Upload Reference Image

```bash
curl --max-time 30 -X POST "$COMFYUI_URL/upload/image" \
  -F "image=@reference.png" \
  -F "subfolder=input" \
  -F "type=input"
```

### Cancel Current Generation

```bash
curl --max-time 30 -X POST "$COMFYUI_URL/interrupt"
```

### Free VRAM

```bash
curl --max-time 30 -X POST "$COMFYUI_URL/free" \
  -H "Content-Type: application/json" \
  -d '{"unload_models": true}'
```

## Polling Strategy

ComfyUI supports WebSocket; REST polling is the default here because it needs no extra Python client dependency. The following 5-second cadence is for standalone use; an explicitly specified task or calling workflow monitoring policy takes precedence, including scheduled checks. Do not start a second polling loop when that policy already provides monitoring. See the [API quick reference](foundation/api-quick-ref.md).

1. Save the request and a unique client ID, then submit once via `POST /prompt` → save `prompt_id`. If the response is lost, inspect queue/history before any resubmission.
2. Poll `GET /history/{prompt_id}` every **5 seconds**
3. On empty response: check queue for the prompt ID; absence from both is unknown, not proof of success or failure.
4. On populated response: check `status.completed`, success status and error/interruption messages.
5. On success, retrieve expected output-node files and verify actual image metadata.
6. If failed, use `comfyui-troubleshooter`.

**Long execution**: Follow the task’s monitoring policy. For standalone use, report observed state after 10 minutes; elapsed queue or total time alone is not evidence of a stall. Keep the prompt ID for recovery and do not interrupt or resubmit automatically.

## Workflow Validation

Before queuing any workflow:

1. Read the cache location documented by the installed `comfyui-inventory` skill; refresh through that skill when missing, stale, incomplete or from another endpoint. This skill does not own an inventory cache or assume the other skill is installed next to it.
2. For each node in workflow: verify `class_type` exists in installed nodes
3. For each model reference: verify file exists in installed models
4. Flag missing items with:
   - Node: identify the package from evidence; do not guess install commands.
   - Model: consult [references/models.md](references/models.md) and verify the exact source.
   - Version mismatch: investigate compatibility before proposing an update.

## Error Handling

| Error | Cause | Action |
|-------|-------|--------|
| Connection refused | Endpoint/service unavailable | Verify address and connectivity; report offline status |
| 400 Bad Request | Invalid workflow JSON | Validate node connections |
| 500 Internal Error | Server-side error | Inspect response and relevant logs; do not assume a crash |
| Timeout (no response) | Network/service state uncertain | GET may be retried; uncertain POST /prompt requires queue/history reconciliation first |

## Reference

[API quick reference](foundation/api-quick-ref.md).

Interrupting, clearing queues, freeing server memory or restarting can affect other tasks; verify ownership and authorization before acting. Installing these local skills does not authorize server changes. Temporary workflow submission does not require saving or overwriting remote user workflow files.
