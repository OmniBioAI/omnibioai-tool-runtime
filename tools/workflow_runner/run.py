# tools/workflow_runner/run.py
"""
OmniBioAI tools.workflow_runner.run.

Purpose:
    Downloads workflow inputs, prepares execution commands, runs workflows and uploads collected results.

Author:
    Manish Kumar <manish@omnibioai.org>
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Tuple
from urllib.parse import urlparse


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or default)


def _load_json_env(name: str, default: Dict[str, Any] | None = None) -> Dict[str, Any]:
    raw = _env(name, "")
    if not raw:
        return default or {}
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else (default or {})
    except Exception:
        return default or {}


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _download_uri_to_path(uri: str, dst: Path) -> None:
    """
    Minimal downloader for:
      - s3://bucket/key
      - file:///path or /path
    """
    u = urlparse(uri)
    _ensure_dir(dst.parent)

    if u.scheme == "s3":
        import boto3  # type: ignore

        bucket = u.netloc
        key = u.path.lstrip("/")
        if not bucket or not key:
            raise RuntimeError(f"Bad S3 URI: {uri}")
        boto3.client("s3").download_file(bucket, key, str(dst))
        return

    if u.scheme in ("", "file"):
        src = Path(u.path if u.scheme == "file" else uri)
        if not src.exists():
            raise RuntimeError(f"Local path not found: {src}")
        shutil.copyfile(src, dst)
        return

    raise RuntimeError(f"Unsupported download URI scheme: {u.scheme} ({uri})")


def _extract_tgz(tgz_path: Path, dst_dir: Path) -> None:
    _ensure_dir(dst_dir)
    subprocess.check_call(["tar", "-xzf", str(tgz_path), "-C", str(dst_dir)])


def _normalize_result_uri(result_uri: str) -> Tuple[str, str]:
    """
    Returns (results_uri, outputs_uri)

    - If RESULT_URI ends with .json -> treat as results.json location
    - Else treat as a prefix/folder and append /results.json and /outputs.json
    """
    s = (result_uri or "").rstrip()
    if not s:
        raise RuntimeError("RESULT_URI is required")

    if s.endswith(".json"):
        base = s.rsplit("/", 1)[0]
        return s, f"{base}/outputs.json"

    s = s.rstrip("/")
    return f"{s}/results.json", f"{s}/outputs.json"


def _upload_uri(uri: str, data: bytes, content_type: str = "application/json") -> None:
    """
    Minimal multi-backend uploader:
      - s3://bucket/key
      - azureblob://account/container/path
      - file:///path or plain /path (local)
    """
    u = urlparse(uri)

    if u.scheme == "s3":
        import boto3  # type: ignore

        bucket = u.netloc
        key = u.path.lstrip("/")
        if not bucket or not key:
            raise RuntimeError(f"Bad S3 URI: {uri}")
        boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
        return

    if u.scheme == "azureblob":
        from azure.storage.blob import BlobServiceClient  # type: ignore

        path = u.path.lstrip("/")
        if "/" not in path:
            raise RuntimeError(f"Bad azureblob URI (need container/blob): {uri}")
        container, blob = path.split("/", 1)

        cs = (
            os.getenv("AZURE_STORAGE_CONNECTION_STRING")
            or os.getenv("OMNI_TOOL_RUNTIME_AZURE_CONNECTION_STRING")
            or ""
        )
        if not cs:
            raise RuntimeError("Missing AZURE_STORAGE_CONNECTION_STRING for azureblob upload")

        svc = BlobServiceClient.from_connection_string(cs)
        bc = svc.get_blob_client(container=container, blob=blob)
        bc.upload_blob(data, overwrite=True, content_settings=None)
        return

    if u.scheme in ("", "file"):
        dst = Path(u.path if u.scheme == "file" else uri)
        _ensure_dir(dst.parent)
        dst.write_bytes(data)
        return

    raise RuntimeError(f"Unsupported RESULT_URI scheme: {u.scheme} ({uri})")


def _run_command(cmd: list[str] | str, cwd: Path, env: Dict[str, str]) -> int:
    if isinstance(cmd, str):
        p = subprocess.run(cmd, shell=True, cwd=str(cwd), env=env)
        return int(p.returncode)
    p = subprocess.run(cmd, cwd=str(cwd), env=env)
    return int(p.returncode)


# ----------------------------
# AWS workdir derivation + nextflow cmd patching
# ----------------------------
def _s3_bucket_prefix_from_result_uri(results_uri: str) -> tuple[str, str]:
    """
    Infer (bucket, prefix_root) from:
      s3://bucket/tes-runs/<run_id>/results.json
    Returns (bucket, prefix_root) best-effort.
    """
    u = urlparse(results_uri)
    if u.scheme != "s3":
        return "", ""
    bucket = u.netloc
    key = u.path.lstrip("/")
    if not bucket or not key:
        return "", ""

    parts = key.split("/")
    prefix_root = parts[0] if parts else ""
    return bucket, prefix_root


def _is_nextflow_cmd(cmd: Any) -> bool:
    if isinstance(cmd, list) and cmd:
        return str(cmd[0]).endswith("nextflow") or str(cmd[0]) == "nextflow"
    if isinstance(cmd, str):
        return cmd.strip().startswith("nextflow ")
    return False


def _force_profile(cmd: list[str], profile: str) -> list[str]:
    """
    Force Nextflow -profile <profile>:
      - if -profile exists, replace its value
      - otherwise append it
    """
    out = list(cmd)
    if "-profile" in out:
        i = out.index("-profile")
        if i + 1 < len(out):
            out[i + 1] = profile
        else:
            out.append(profile)
        return out
    out.extend(["-profile", profile])
    return out


def _patch_nextflow_for_aws(
    cmd: list[str],
    *,
    run_id: str,
    results_uri: str,
    aws_profile: str = "awsbatch",
) -> tuple[list[str], dict[str, str]]:
    """
    FORCE for cloud+aws:
      -profile awsbatch
    Also inject:
      -work-dir s3://<bucket>/<prefix>/<run_id>/nf-work (best-effort)
    """
    extra_env: dict[str, str] = {}

    bucket = _env("S3_RESULTS_BUCKET", "")
    prefix = _env("S3_RESULTS_PREFIX", "")
    if not bucket:
        b2, p2 = _s3_bucket_prefix_from_result_uri(results_uri)
        bucket = bucket or b2
        prefix = prefix or p2

    prefix = (prefix or "tes-runs").strip("/")
    work_dir = f"s3://{bucket}/{prefix}/{run_id}/nf-work" if bucket else ""

    out = list(cmd)
    out = _force_profile(out, aws_profile)

    if work_dir and "-work-dir" not in out:
        out.extend(["-work-dir", work_dir])
        extra_env["NXF_WORK"] = work_dir

    return out, extra_env


# ----------------------------
# Generic input staging for cloud runs (local-path -> s3://)
# ----------------------------
def _looks_like_local_path(s: str) -> bool:
    if not s or not isinstance(s, str):
        return False
    if "://" in s:
        return False
    return s.startswith("/") or s.startswith("~/")


def _is_file_path(s: str) -> Path | None:
    if not _looks_like_local_path(s):
        return None
    p = Path(s).expanduser()
    if p.exists() and p.is_file():
        return p.resolve()
    return None


def _hash_for_key(p: Path) -> str:
    st = p.stat()
    h = hashlib.sha256()
    h.update(str(p).encode("utf-8"))
    h.update(str(st.st_size).encode("utf-8"))
    h.update(str(int(st.st_mtime)).encode("utf-8"))
    return h.hexdigest()[:16]


def _s3_put_file(bucket: str, key: str, local_path: Path) -> None:
    import boto3  # type: ignore

    boto3.client("s3").upload_file(str(local_path), bucket, key)


def _stage_and_rewrite_inputs_to_s3(
    inputs: Dict[str, Any],
    *,
    bucket: str,
    base_prefix: str,
    run_id: str,
    exec_root: Path,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Recursively scan inputs, upload any referenced local files to:
      s3://bucket/<base_prefix>/runs/<run_id>/inputs/<hash>-<basename>
    Rewrite those values to the S3 URI.
    Returns (rewritten_inputs, manifest)
    """
    if not bucket:
        raise RuntimeError("Cannot stage inputs: S3 bucket is empty. Set S3_RESULTS_BUCKET or use s3:// RESULT_URI.")

    base_prefix = (base_prefix or "tes-runs").strip("/")
    stage_prefix = f"{base_prefix}/runs/{run_id}/inputs"

    manifest: Dict[str, Any] = {
        "run_id": run_id,
        "bucket": bucket,
        "stage_prefix": f"s3://{bucket}/{stage_prefix}/",
        "files": [],
    }

    cache: dict[str, str] = {}

    def _rewrite(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {k: _rewrite(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_rewrite(v) for v in obj]
        if isinstance(obj, str):
            p = _is_file_path(obj)
            if not p:
                return obj

            sp = cache.get(str(p))
            if sp:
                return sp

            key = f"{stage_prefix}/{_hash_for_key(p)}-{p.name}"
            s3_uri = f"s3://{bucket}/{key}"

            _s3_put_file(bucket, key, p)

            cache[str(p)] = s3_uri
            manifest["files"].append({"local": str(p), "s3": s3_uri, "basename": p.name})
            return s3_uri

        return obj

    rewritten = _rewrite(inputs)
    (exec_root / "stage_manifest.json").write_text(json.dumps(manifest, indent=2))
    return rewritten, manifest


def _set_nextflow_input_json_arg(cmd: list[str], new_input_json_path: str) -> list[str]:
    """
    If the workflow command already has --input_json <path>, replace its value.
    Otherwise, do nothing.
    """
    out = list(cmd)
    if "--input_json" in out:
        i = out.index("--input_json")
        if i + 1 < len(out):
            out[i + 1] = new_input_json_path
        else:
            out.append(new_input_json_path)
    return out


def _append_if_param_present(cmd: list[str], *, flag: str, value: Any) -> list[str]:
    """
    Append `flag value` if value is present and non-empty, and flag is not already present.
    """
    if value is None:
        return cmd
    if isinstance(value, str) and not value.strip():
        return cmd

    out = list(cmd)
    if flag in out:
        i = out.index(flag)
        if i + 1 >= len(out):
            out.append(str(value))
        return out

    out.extend([flag, str(value)])
    return out


# ✅ NEW (minimal but crucial): set AWS queue/region env vars from TES inputs
def _apply_aws_env_from_inputs(child_env: Dict[str, str], inputs: Dict[str, Any]) -> None:
    q = inputs.get("aws_queue")
    r = inputs.get("aws_region")

    if isinstance(q, str) and q.strip():
        # satisfy nextflow.config check that looks for these
        child_env.setdefault("OMNIBIOAI_AWS_BATCH_QUEUE", q.strip())
        child_env.setdefault("AWS_BATCH_JOB_QUEUE", q.strip())

    if isinstance(r, str) and r.strip():
        # keep AWS SDK + nf-amazon happy
        child_env.setdefault("AWS_DEFAULT_REGION", r.strip())
        child_env.setdefault("AWS_REGION", r.strip())


def main() -> int:
    tool_id = _env("TOOL_ID", "workflow_runner")
    run_id = _env("RUN_ID", "")
    inputs = _load_json_env("INPUTS_JSON", {})
    resources = _load_json_env("RESOURCES_JSON", {})

    if not run_id:
        raise RuntimeError("RUN_ID is required")

    result_uri_raw = _env("RESULT_URI", "")
    results_uri, outputs_uri = _normalize_result_uri(result_uri_raw)

    work_root = Path(_env("WORK_ROOT", "/work"))
    exec_root = work_root / "workflow_runner_exec" / run_id
    _ensure_dir(exec_root)

    # --- workflow bundle mode (S3 tgz + entrypoint + input_json_uri) ---
    wf_bundle_uri = str(inputs.get("workflow_bundle_s3_uri") or "").strip()
    wf_entry = str(inputs.get("workflow_entrypoint") or "").strip()
    input_json_uri = str(inputs.get("input_json_uri") or "").strip()
    is_bundle_mode = str(inputs.get("engine") or "").lower() == "nextflow" and bool(wf_bundle_uri and wf_entry)

    cmd: Any = inputs.get("command")  # keep user override if provided

    if is_bundle_mode:
        bundle_tgz = exec_root / "_workflow_bundle.tgz"
        bundle_dir = exec_root / "_workflow_bundle"

        _download_uri_to_path(wf_bundle_uri, bundle_tgz)
        if bundle_dir.exists():
            shutil.rmtree(bundle_dir)
        _extract_tgz(bundle_tgz, bundle_dir)

        entry_path = (bundle_dir / wf_entry).resolve()
        if not entry_path.exists():
            raise RuntimeError(f"workflow_entrypoint not found after extract: {entry_path}")

        local_input_json = ""
        if input_json_uri:
            local_input_json_path = exec_root / "input.cloud.json"
            _download_uri_to_path(input_json_uri, local_input_json_path)
            local_input_json = str(local_input_json_path)

        cmd = ["nextflow", "run", str(entry_path)]
        if local_input_json:
            cmd += ["--input_json", local_input_json]

        # forward params too (fine to keep)
        cmd = _append_if_param_present(cmd, flag="--aws_queue", value=inputs.get("aws_queue"))
        cmd = _append_if_param_present(cmd, flag="--aws_region", value=inputs.get("aws_region"))

    # Optional: local bundle copy (local testing convenience)
    local_bundle = inputs.get("local_bundle_path")
    if isinstance(local_bundle, str) and local_bundle.strip():
        src = Path(local_bundle).expanduser().resolve()
        if src.exists() and src.is_dir():
            dst = exec_root / "bundle"
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    # If no explicit cmd and not in bundle mode, fallback to legacy behavior
    if cmd is None:
        engine = str(inputs.get("engine") or "").lower()
        wf = inputs.get("workflow") or inputs.get("workflow_path") or inputs.get("workflow_uri")
        if engine and wf:
            if engine == "nextflow":
                cmd = ["nextflow", "run", str(wf)]
            elif engine == "snakemake":
                cmd = ["snakemake", "-s", str(wf)]
            elif engine == "cwl":
                cmd = ["cwltool", str(wf)]
            else:
                cmd = str(inputs.get("command_str") or "")
        else:
            cmd = str(inputs.get("command_str") or "")

    # Normalize nextflow string cmd -> list, so patching works
    if isinstance(cmd, str) and _is_nextflow_cmd(cmd):
        cmd = shlex.split(cmd)

    child_env = os.environ.copy()
    child_env["OMNIBIOAI_WORKFLOW_RUN_ID"] = run_id
    child_env["OMNIBIOAI_WORKFLOW_EXEC_ROOT"] = str(exec_root)
    child_env["OMNIBIOAI_RESOURCES_JSON"] = json.dumps(resources)

    # ✅ apply AWS queue/region env vars early (before Nextflow parses config)
    _apply_aws_env_from_inputs(child_env, inputs)

    # Robust AWS detection for Batch: S3 RESULT_URI or region env is enough
    is_cloud_aws = (urlparse(results_uri).scheme == "s3") or bool(_env("AWS_DEFAULT_REGION", "")) or bool(
        child_env.get("AWS_DEFAULT_REGION", "")
    )

    # Stage+rewrite only when NOT in bundle mode (bundle mode already uses S3 URIs)
    if is_cloud_aws and not is_bundle_mode:
        bucket = _env("S3_RESULTS_BUCKET", "")
        prefix = _env("S3_RESULTS_PREFIX", "")
        if not bucket:
            b2, p2 = _s3_bucket_prefix_from_result_uri(results_uri)
            bucket = bucket or b2
            prefix = prefix or p2

        stage_base = _env("S3_STAGE_PREFIX", "") or prefix or "tes-runs"

        if _env("OMNI_STAGE_INPUTS", "1") != "0":
            rewritten_inputs, _manifest = _stage_and_rewrite_inputs_to_s3(
                inputs,
                bucket=bucket,
                base_prefix=stage_base,
                run_id=run_id,
                exec_root=exec_root,
            )
            cloud_input_path = exec_root / "input.cloud.json"
            cloud_input_path.write_text(json.dumps(rewritten_inputs, indent=2))

            if isinstance(cmd, list) and _is_nextflow_cmd(cmd):
                cmd = _set_nextflow_input_json_arg(cmd, str(cloud_input_path))

    # Patch Nextflow for AWS whenever we're in Batch+AWS
    if isinstance(cmd, list) and _is_nextflow_cmd(cmd) and is_cloud_aws:
        cmd, extra_env = _patch_nextflow_for_aws(cmd, run_id=run_id, results_uri=results_uri, aws_profile="awsbatch")
        child_env.update(extra_env)

    rc = 0
    err: str | None = None
    try:
        rc = _run_command(cmd, cwd=exec_root, env=child_env)  # type: ignore[arg-type]
    except Exception as e:
        rc = 1
        err = str(e)

    outputs_path = exec_root / "outputs.json"
    outputs_obj: Dict[str, Any]
    if outputs_path.exists():
        try:
            outputs_obj = json.loads(outputs_path.read_text())
            if not isinstance(outputs_obj, dict):
                outputs_obj = {"_raw": outputs_obj}
        except Exception as e:
            outputs_obj = {"ok": False, "error": f"outputs.json parse failed: {e}"}
    else:
        outputs_obj = {"ok": (rc == 0), "note": "outputs.json not produced by runner"}

    results_obj: Dict[str, Any] = {
        "ok": (rc == 0),
        "tool_id": tool_id,
        "run_id": run_id,
        "engine": inputs.get("engine"),
        "exec_root": str(exec_root),
        "results_uri": results_uri,
        "outputs_uri": outputs_uri,
        "outputs": outputs_obj
        if len(json.dumps(outputs_obj)) < 200_000
        else {"note": "outputs too large; see outputs_uri"},
    }
    if err:
        results_obj["error"] = err
    if rc != 0:
        results_obj["exit_code"] = rc

    # Upload outputs.json (best-effort), then results.json (must)
    try:
        _upload_uri(outputs_uri, json.dumps(outputs_obj, indent=2).encode("utf-8"))
    except Exception as e:
        results_obj["outputs_upload_error"] = str(e)

    # Upload outputs.normalized.json if present
    try:
        norm_path = exec_root / "outputs.normalized.json"
        if norm_path.exists() and norm_path.is_file():
            base = outputs_uri.rsplit("/", 1)[0]
            norm_uri = f"{base}/outputs.normalized.json"
            _upload_uri(norm_uri, norm_path.read_bytes(), content_type="application/json")
            results_obj["outputs_normalized_uri"] = norm_uri
    except Exception as e:
        results_obj["outputs_normalized_upload_error"] = str(e)

    _upload_uri(results_uri, json.dumps(results_obj, indent=2).encode("utf-8"))
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
