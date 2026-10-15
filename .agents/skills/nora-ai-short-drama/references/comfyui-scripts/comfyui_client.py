#!/usr/bin/env python3
"""Business-independent ComfyUI HTTP client. Python 3.9+, standard library only."""
import argparse
import base64
import hashlib
import http.client
import io
import json
import math
import mimetypes
import os
from pathlib import Path
import re
import sys
import tempfile
from datetime import datetime
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

CHUNK = 1024 * 1024


class ClientError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def now():
    return datetime.now().astimezone().isoformat()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n").encode("utf-8")


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result

    def invalid(value):
        raise ValueError("Non-finite JSON value: " + value)

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def write_new(path, value):
    """Exclusive, durable evidence file; never replaces an existing file."""
    path = Path(path)
    data = encoded(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def remote_path(value, filename=False):
    normalized = value.replace("\\", "/") if isinstance(value, str) else ""
    if (not isinstance(value, str) or
            any(ord(c) < 32 for c in value) or normalized.startswith("/") or
            any(p in (".", "..") or ":" in p for p in normalized.split("/")) or
            (filename and (not value or "/" in normalized))):
        raise ClientError("invalid_path", "Expected a safe relative remote path", value=value)
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, url, timeout):
        parts = urllib.parse.urlsplit(url or "")
        if (parts.scheme not in ("http", "https") or not parts.hostname or
                parts.username or parts.password or parts.query or parts.fragment):
            raise ClientError("invalid_url", "Supply --url or COMFYUI_URL; no credentials/query/fragment in URL")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ClientError("invalid_timeout", "Timeout must be a finite positive number")
        self.url, self.timeout = url.rstrip("/"), timeout
        self.opener = urllib.request.build_opener(NoRedirect())

    def open(self, route, data=None, headers=None):
        request = urllib.request.Request(self.url + route, data=data, headers=headers or {},
                                         method="GET" if data is None else "POST")
        try:
            return self.opener.open(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            raw = exc.read(1024 * 1024)
            try:
                body = strict_json(raw)
            except (ValueError, UnicodeError):
                body = raw.decode("utf-8", errors="replace")
            raise ClientError("http_error", "Server rejected or failed the HTTP request",
                              http_status=exc.code, response=body, retry_after=exc.headers.get("Retry-After")) from exc
        except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
            raise ClientError("transport_error", str(exc)) from exc

    def json(self, route, data=None, headers=None):
        with self.open(route, data, headers) as response:
            try:
                return strict_json(response.read())
            except (ValueError, UnicodeError) as exc:
                raise ClientError("invalid_response", "Server did not return valid JSON") from exc


def upload(client, args, *, source=None, storage_type="input"):
    if storage_type not in ("input", "output"):
        raise ClientError("invalid_storage_type", "Upload storage must be input or output")
    if source is None:  # Standalone file input; backend passes its prepared source.
        source = Path(args.file).resolve(strict=True)
        remote_path(source.name, filename=True)
        if '"' in source.name:
            raise ClientError("invalid_filename", "Upload filename cannot contain a quote")
        folder = remote_path(args.subfolder)
    else:
        folder = args.subfolder
    boundary = "ComfyClient" + uuid.uuid4().hex
    digest = hashlib.sha256()
    size = 0
    # Spill multipart to disk rather than holding large videos in memory.
    with tempfile.TemporaryFile() as body:
        for key, value in (("type", storage_type), ("subfolder", folder), ("overwrite", "false")):
            body.write((f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
                        f'{value}\r\n').encode("utf-8"))
        mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        body.write((f'--{boundary}\r\nContent-Disposition: form-data; name="image"; '
                    f'filename="{source.name}"\r\nContent-Type: {mime}\r\n\r\n').encode("utf-8"))
        with source.open("rb") as stream:
            while block := stream.read(CHUNK):
                body.write(block)
                digest.update(block)
                size += len(block)
        body.write(f"\r\n--{boundary}--\r\n".encode())
        length = body.tell()
        body.seek(0)
        result = client.json("/upload/image", iter(lambda: body.read(CHUNK), b""), {
            "Content-Type": "multipart/form-data; boundary=" + boundary,
            "Content-Length": str(length),
        })
    if not isinstance(result, dict) or not all(k in result for k in ("name", "subfolder", "type")):
        raise ClientError("invalid_response", "Upload response lacks file identity", response=result,
                          upload_state="unknown_do_not_blindly_retry")
    name = remote_path(result["name"], filename=True)
    folder = remote_path(result["subfolder"])
    if result["type"] != storage_type:
        raise ClientError("invalid_response", "Unexpected upload storage type", response=result)
    return {"file": str(source), "bytes": size, "sha256": digest.hexdigest(),
            "remote": result, storage_type + "_path": "/".join(filter(None, (folder.replace("\\", "/"), name)))}


def validate_workflow(workflow):
    # Shape only; remote compatibility is decided by ComfyUI during execution.
    if not isinstance(workflow, dict) or not workflow:
        raise ClientError("invalid_workflow", "Expected nonempty API-format node object")
    for node_id, node in workflow.items():
        if (not isinstance(node, dict) or not isinstance(node.get("class_type"), str) or
                not node["class_type"] or not isinstance(node.get("inputs"), dict)):
            raise ClientError("invalid_workflow", "Expected API JSON, not UI workflow or request envelope",
                              node_id=node_id)


def submit(client, args, workflow=None, client_id=None):
    from_file = workflow is None
    if from_file:
        workflow = strict_json(Path(args.workflow).read_bytes())
        validate_workflow(workflow)
    # A supplied object comes from the backend's validated task input.
    payload = {"prompt": workflow, "client_id": client_id or str(uuid.uuid4())}
    request_bytes = encoded(payload)
    record = Path(args.record_dir).absolute()
    record.mkdir(parents=True, exist_ok=True)
    names = (args.attempt_name, args.request_name, args.response_name)
    if from_file:
        for name in names:
            remote_path(name, filename=True)
        if len(set(names)) != 3:
            raise ClientError("path_collision", "Submission evidence filenames must be distinct")
    marker, request_file, response_file = [record / n for n in names]
    if any(os.path.lexists(p) for p in (marker, request_file, response_file)):
        raise ClientError("submission_guard", "Existing submission evidence; reconcile, never resubmit here",
                          record_dir=str(record), submission_state="not_sent")
    # O_EXCL also arbitrates concurrent submit calls sharing this record directory.
    try:
        write_new(marker, {"time": now(), "url": client.url, "client_id": payload["client_id"],
                           "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
                           "state": "reserved_do_not_resubmit"})
        write_new(request_file, payload)
    except FileExistsError as exc:
        raise ClientError("submission_guard", "Submission evidence reserved by another call; no request sent",
                          record_dir=str(record), submission_state="not_sent") from exc
    try:
        result = client.json("/prompt", request_bytes, {"Content-Type": "application/json"})
    except Exception as exc:
        details = exc.details if isinstance(exc, ClientError) else {}
        state = "rejected" if details.get("http_status") in (400, 401, 403, 404, 422) else "unknown"
        failure = {"time": now(), "submission_state": state, "error": str(exc), **details}
        write_new(response_file, failure)
        raise ClientError("submission_" + state, "Do not automatically retry POST; inspect saved evidence",
                          record_dir=str(record), client_id=payload["client_id"], **failure) from exc
    # Save raw response before any further validation or reporting.
    try:
        write_new(response_file, result)
    except OSError as exc:
        raise ClientError("submission_response_save_failed", "Response received but could not be saved; do not resubmit",
                          record_dir=str(record), client_id=payload["client_id"], response=result) from exc
    if not isinstance(result, dict) or not isinstance(result.get("prompt_id"), str) or not result["prompt_id"]:
        raise ClientError("submission_unknown", "No valid prompt_id; inspect saved response, do not resubmit",
                          record_dir=str(record), response=result, client_id=payload["client_id"])
    return {"submission_state": "accepted", "prompt_id": result["prompt_id"],
            "client_id": payload["client_id"], "record_dir": str(record), "response": result}


def classify(history, queue, prompt_id):
    entry = history.get(prompt_id)
    if isinstance(entry, dict) and entry:
        status = entry.get("status", {})
        messages = status.get("messages", [])
        failed = any(isinstance(m, list) and m and m[0] in ("execution_error", "execution_interrupted")
                     for m in messages)
        if failed or status.get("status_str") == "error":
            return "failed", entry
        if status.get("completed") is True and status.get("status_str") == "success":
            return "success", entry
    for field, state in (("queue_running", "running"), ("queue_pending", "queued")):
        if any(isinstance(item, list) and len(item) > 1 and item[1] == prompt_id
               for item in queue.get(field, [])):
            return state, entry
    return "unknown", entry


def status(client, args):
    prompt_id = args.prompt_id
    history = client.json("/history/" + urllib.parse.quote(prompt_id, safe=""))
    if not isinstance(history, dict):
        raise ClientError("invalid_response", "Expected history object")
    state, entry = classify(history, {}, prompt_id)
    queue_evidence = {}
    if state == "unknown":
        queue = client.json("/queue")
        if not isinstance(queue, dict):
            raise ClientError("invalid_response", "Expected queue object")
        # Retain only this task; never persist other users' prompts/inputs.
        queue_evidence = {k: [x for x in queue.get(k, []) if isinstance(x, list) and
                              len(x) > 1 and x[1] == prompt_id]
                          for k in ("queue_running", "queue_pending")}
        state, entry = classify(history, queue_evidence, prompt_id)
    files = []
    outputs = entry.get("outputs", {}) if isinstance(entry, dict) else {}
    for node_id, node_outputs in outputs.items():
        if not isinstance(node_outputs, dict):
            continue
        for key, items in node_outputs.items():
            if not isinstance(items, list):
                continue
            for index, item in enumerate(items):
                if isinstance(item, dict) and isinstance(item.get("filename"), str):
                    files.append({"node_id": node_id, "output_key": key, "index": index, "file": item})
    return {"prompt_id": prompt_id, "state": state, "files": files,
            "history": entry, "queue": queue_evidence}


def download(client, args):
    name = remote_path(args.filename, filename=True)
    folder = remote_path(args.subfolder)
    target = Path(args.output).absolute()
    if os.path.lexists(target):
        raise ClientError("file_exists", "Refusing to overwrite local output", path=str(target))
    if args.sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", args.sha256):
        raise ClientError("invalid_hash", "Expected 64 hexadecimal SHA-256 characters")
    target.parent.mkdir(parents=True, exist_ok=True)
    query = urllib.parse.urlencode({"filename": name, "subfolder": folder, "type": args.type})
    temp_path = None
    try:
        with client.open("/view?" + query) as response:
            expected = response.headers.get("Content-Length")
            digest, count = hashlib.sha256(), 0
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".comfy-download-", delete=False) as out:
                temp_path = Path(out.name)
                while True:
                    try:
                        block = response.read(CHUNK)
                    except (OSError, http.client.HTTPException) as exc:
                        raise ClientError("transport_error", str(exc), operation="download_read") from exc
                    if not block:
                        break
                    out.write(block)
                    digest.update(block)
                    count += len(block)
                out.flush()
                os.fsync(out.fileno())
        if expected is not None and count != int(expected):
            raise ClientError("incomplete_download", "HTTP content length mismatch",
                              expected=int(expected), actual=count)
        if args.sha256 and digest.hexdigest() != args.sha256.lower():
            raise ClientError("hash_mismatch", "Downloaded bytes do not match expected SHA-256")
        # Atomic publication, unlike replace(): fails even if another process creates target meanwhile.
        os.link(temp_path, target)
        return {"path": str(target), "bytes": count, "sha256": digest.hexdigest(),
                "remote": {"filename": name, "subfolder": folder, "type": args.type}}
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def export_pack(client, args):
    source = Path(args.workflow).resolve(strict=True)
    target = Path(args.output).absolute()
    if os.path.lexists(target):
        raise ClientError("file_exists", "Refusing to overwrite local output", path=str(target))
    if not target.name.endswith(".mmxpack.zip"):
        raise ClientError("invalid_path", "Director pack output must end with .mmxpack.zip")
    workflow = strict_json(source.read_bytes())
    validate_workflow(workflow)
    node = workflow.get(args.node_id)
    if node is None or node["class_type"] != "MiniMaxH3Director":
        raise ClientError("invalid_node", "--node-id must identify a MiniMaxH3Director API node")
    inputs = node["inputs"]
    timeline = strict_json(inputs["timeline_data"])
    if not isinstance(timeline, dict):
        raise ClientError("invalid_timeline", "Expected serialized timeline object")
    # Match the native web exporter; external model/Refine/SIGMAS links are not pack widgets.
    widget_names = ("steps", "sampler", "scheduler", "cfg", "shift_video", "shift_audio", "seed", "task_type")
    widgets = {key: inputs[key] for key in widget_names if key in inputs}
    if any(isinstance(value, (list, dict)) for value in widgets.values()):
        raise ClientError("invalid_widgets", "Export requires literal widget values, not linked inputs")
    route = "/minimax/director/export_pack"
    headers = {"Content-Type": "application/json"}
    body = {"timeline": timeline, "widgets": widgets}
    preflight = client.json(route, encoded({**body, "dryRun": True}), headers)
    if preflight["missing"]:
        raise ClientError("missing_assets", "Director pack references missing remote media", missing=preflight["missing"])
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with client.open(route, encoded(body), headers) as response:
            if response.headers.get("Content-Type", "").split(";", 1)[0] == "application/json":
                result = strict_json(response.read())
                if result["missing"]:
                    raise ClientError("missing_assets", "Media disappeared during export", missing=result["missing"])
                stream = io.BytesIO(base64.b64decode(result.pop("zipB64"), validate=True))
                expected, download_name = result["bytes"], result["downloadName"]
            else:
                missing = strict_json(response.headers["X-Pack-Missing"])
                if missing:
                    raise ClientError("missing_assets", "Media disappeared during export", missing=missing)
                stream = response
                expected = int(response.headers["Content-Length"])
                download_name = response.headers["X-Pack-Download-Name"]
            digest, count = hashlib.sha256(), 0
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".comfy-pack-", delete=False) as out:
                temp_path = Path(out.name)
                while block := stream.read(CHUNK):
                    out.write(block)
                    digest.update(block)
                    count += len(block)
                out.flush()
                os.fsync(out.fileno())
        if count != expected:
            raise ClientError("incomplete_download", "Export content length mismatch", expected=expected, actual=count)
        with zipfile.ZipFile(temp_path) as pack:
            bad_entry = pack.testzip()
            if bad_entry:
                raise ClientError("invalid_pack", "ZIP CRC check failed", entry=bad_entry)
            metadata = strict_json(pack.read("pack.json"))
            if metadata["format"] != "minimax-h3-director-pack" or metadata["formatVersion"] != 1:
                raise ClientError("invalid_pack", "Unsupported Director pack format")
            pack.getinfo("timeline.json")
            pack.getinfo("shared_params/shared_params.json")
            entry_count = len(pack.infolist())
        os.link(temp_path, target)
        return {"path": str(target), "bytes": count, "sha256": digest.hexdigest(),
                "source_workflow": str(source), "node_id": args.node_id,
                "download_name": download_name, "preflight": preflight, "zip_entries": entry_count}
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ClientError("arguments", message)


def parser():
    root = Parser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True, parser_class=Parser)
    for name in ("upload", "submit", "status", "download", "export-pack"):
        sub = commands.add_parser(name)
        sub.add_argument("--url", default=os.environ.get("COMFYUI_URL"))
        sub.add_argument("--timeout", type=float, default=30, help="Per blocking network operation, not job deadline")
        sub.add_argument("--result", help="Optional new JSON result file; never overwritten")
        if name == "upload":
            sub.add_argument("--file", required=True)
            sub.add_argument("--subfolder", default="")
        elif name == "submit":
            sub.add_argument("--workflow", required=True)
            sub.add_argument("--record-dir", required=True)
            sub.add_argument("--request-name", default="request.json")
            sub.add_argument("--response-name", default="response.json")
            sub.add_argument("--attempt-name", default="submit-attempt.json")
        elif name == "status":
            sub.add_argument("--prompt-id", required=True)
        elif name == "download":
            sub.add_argument("--filename", required=True)
            sub.add_argument("--subfolder", default="")
            sub.add_argument("--type", required=True, choices=("input", "output", "temp"))
            sub.add_argument("--output", required=True)
            sub.add_argument("--sha256", help="Optional expected transfer hash, not media quality validation")
        else:
            sub.add_argument("--workflow", required=True, help="Saved API node JSON, not canvas JSON")
            sub.add_argument("--node-id", required=True, help="MiniMaxH3Director node ID in that API")
            sub.add_argument("--output", required=True, help="New .mmxpack.zip file")
    return root


def main(argv=None):
    args, result_stream = None, None
    try:
        args = parser().parse_args(argv)
        client = Client(args.url, args.timeout)
        if args.result:
            result_path = Path(args.result).absolute()
            protected = []
            if args.command == "upload":
                protected.append(Path(args.file).absolute())
            if args.command == "download":
                protected.append(Path(args.output).absolute())
            if args.command == "export-pack":
                protected.extend((Path(args.workflow).absolute(), Path(args.output).absolute()))
            if args.command == "submit":
                protected.extend(Path(args.record_dir).absolute() / n for n in
                                 (args.attempt_name, args.request_name, args.response_name))
                protected.append(Path(args.workflow).absolute())
            if result_path in protected:
                raise ClientError("path_collision", "Result file collides with input/output/evidence")
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_stream = result_path.open("xb")  # Fail before any remote side effect.
        data = globals()[args.command.replace("-", "_")](client, args)
        result = {"ok": True, "command": args.command, "time": now(), "url": client.url, "data": data}
        code = 0
    except Exception as exc:
        result = {"ok": False, "command": getattr(args, "command", None), "time": now(),
                  "error": {"code": exc.code if isinstance(exc, ClientError) else type(exc).__name__,
                            "message": str(exc),
                            **(exc.details if isinstance(exc, ClientError) else {})}}
        code = 1
    raw = encoded(result)
    try:
        if result_stream:
            result_stream.write(raw)
            result_stream.flush()
            os.fsync(result_stream.fileno())
    except OSError as exc:
        result["result_save_error"] = str(exc)
        raw, code = encoded(result), 1
    finally:
        if result_stream:
            result_stream.close()
    sys.stdout.buffer.write(raw)
    return code


if __name__ == "__main__":
    sys.exit(main())
