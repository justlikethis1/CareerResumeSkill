from __future__ import annotations

import json
import os
import shutil
import socket
import tempfile
import threading
import uuid
import webbrowser
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import uvicorn
from starlette.applications import Starlette
from starlette.datastructures import UploadFile
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from .application import ApplicationService
from .config import Settings
from .latex import find_compiler
from .llm import DeepSeekClient
from .tools import environment_report

MAX_REQUEST_BYTES = 15 * 1024 * 1024
MAX_SOURCE_BYTES = 12 * 1024 * 1024
MAX_JD_CHARACTERS = 100_000
MAX_STORED_JOBS = 24
_UI_PATH = Path(__file__).with_name("web_ui.html")


def _build_service(api_key: str, output_dir: Path) -> ApplicationService:
    settings = replace(
        Settings.from_env(),
        api_key=api_key,
        output_dir=str(output_dir),
    )
    return ApplicationService(settings, provider=DeepSeekClient(settings))


def _local_origin(request: Request) -> bool:
    host = request.headers.get("host", "")
    parsed_host = urlsplit(f"//{host}").hostname
    if parsed_host not in {"127.0.0.1", "localhost"}:
        return False
    origin = request.headers.get("origin")
    if not origin:
        return True
    parsed_origin = urlsplit(origin)
    return parsed_origin.scheme == "http" and parsed_origin.netloc.casefold() == host.casefold()


def _artifact_paths(result: dict[str, Any], track: str) -> dict[str, str]:
    if track == "docx":
        candidates = {
            "resume_docx": result.get("output_docx"),
            "resume_pdf": result.get("output_pdf"),
            "cover_letter_pdf": (result.get("cover_letter_pdf") or {}).get("pdf_path"),
            "cover_letter_txt": result.get("cover_letter_text_path"),
            "cover_letter_md": result.get("cover_letter_md_path"),
        }
    else:
        documents = result.get("documents") or {}
        candidates = {
            "resume_pdf": (documents.get("resume") or {}).get("pdf_path"),
            "resume_tex": (documents.get("resume") or {}).get("tex_path"),
            "cover_letter_pdf": (documents.get("cover_letter") or {}).get("pdf_path"),
            "cover_letter_tex": (documents.get("cover_letter") or {}).get("tex_path"),
            "cover_letter_txt": result.get("cover_letter_text_path"),
            "cover_letter_md": result.get("cover_letter_md_path"),
        }
    return {name: str(Path(path).resolve()) for name, path in candidates.items() if path}


def _summary(result: dict[str, Any], track: str, artifact_paths: dict[str, str]) -> dict[str, Any]:
    ats = result.get("ats_report") or {}
    if track == "docx":
        quality = result.get("quality_report") or {}
        page_count = (quality.get("pages") or {}).get("output")
        cover_pages = (result.get("cover_letter_pdf") or {}).get("pages")
    else:
        documents = result.get("documents") or {}
        page_count = (documents.get("resume") or {}).get("pages")
        cover_pages = (documents.get("cover_letter") or {}).get("pages")
    missing = [
        *(ats.get("hard_requirements") or {}).get("missing", []),
        *(ats.get("preferred_keywords") or {}).get("missing", []),
    ]
    gaps = (result.get("gap_analysis") or {}).get("gaps", [])
    return {
        "verified": result.get("verified"),
        "resume_pages": page_count,
        "cover_letter_pages": cover_pages,
        "ats_score": ats.get("score"),
        "resume_only_ats_score": (ats.get("resume_only") or {}).get("score"),
        "missing_keywords": list(dict.fromkeys(missing))[:12],
        "evidence_gaps": gaps[:12] if isinstance(gaps, list) else [],
        "warning": result.get("warning"),
        "performance": result.get("performance", {}),
        "artifacts": [
            {"id": key, "name": Path(path).name, "label": key.replace("_", " ").title()}
            for key, path in artifact_paths.items()
        ],
    }


async def home(_: Request) -> Response:
    try:
        content = _UI_PATH.read_text(encoding="utf-8")
    except OSError:
        return HTMLResponse("Local application interface is unavailable.", status_code=500)
    return HTMLResponse(content, headers={"Cache-Control": "no-store"})


async def environment_status(_: Request) -> Response:
    settings = Settings.from_env()
    report = environment_report(settings)
    compilers = report["compilers"]
    try:
        find_compiler()
        latex_ready = True
    except RuntimeError:
        latex_ready = False
    return JSONResponse({
        "api_key_configured": settings.has_api_key,
        "model": settings.model,
        "latex_ready": latex_ready,
        "docx_pdf_ready": bool(compilers.get("libreoffice") or compilers.get("microsoft_word")),
        "output_writable": report["output"]["writable"],
        "local_only": True,
    }, headers={"Cache-Control": "no-store"})


async def create_application(request: Request) -> Response:
    if not _local_origin(request):
        return JSONResponse({"error": "本地页面请求校验失败，请从应用首页重新打开。"}, status_code=403)
    try:
        declared_size = int(request.headers.get("content-length", "0"))
    except ValueError:
        declared_size = MAX_REQUEST_BYTES + 1
    if declared_size <= 0 or declared_size > MAX_REQUEST_BYTES:
        return JSONResponse({"error": "上传请求为空或超过 15 MB 限制。"}, status_code=413)

    api_key = ""
    run_dir: Path | None = None
    try:
        async with request.form(max_files=1, max_fields=12, max_part_size=MAX_SOURCE_BYTES) as form:
            jd_text = str(form.get("jd_text", "")).strip()
            company_name = str(form.get("company_name", "Target Organization")).strip()
            verified_context = str(form.get("verified_company_context", "")).strip()
            track = str(form.get("track", "docx"))
            resume_language = str(form.get("resume_language", "en"))
            api_key = str(form.get("api_key", "")).strip()
            base_settings = Settings.from_env()
            api_key = api_key or base_settings.api_key or ""
            upload = form.get("source_file")

            if not jd_text:
                return JSONResponse({"error": "请粘贴职位描述或公开职位链接。"}, status_code=400)
            if len(jd_text) > MAX_JD_CHARACTERS:
                return JSONResponse({"error": "职位描述超过 100,000 字符限制。"}, status_code=413)
            if not company_name:
                company_name = "Target Organization"
            if track not in {"docx", "latex"}:
                return JSONResponse({"error": "请选择有效的简历来源格式。"}, status_code=400)
            if not isinstance(upload, UploadFile):
                return JSONResponse({"error": "请上传 DOCX 简历或 Master CV JSON。"}, status_code=400)
            if not api_key:
                return JSONResponse({"error": "请填写 DeepSeek API Key，或在本机 .env 中配置。"}, status_code=400)
            if track == "docx" and resume_language not in {"en", "zh_CN"}:
                return JSONResponse({"error": "请选择有效的简历语言。"}, status_code=400)
            source_bytes = await upload.read(MAX_SOURCE_BYTES + 1)
            if len(source_bytes) > MAX_SOURCE_BYTES:
                return JSONResponse({"error": "简历文件超过 12 MB 限制。"}, status_code=413)
            suffix = Path(upload.filename or "").suffix.casefold()
            expected_suffix = ".docx" if track == "docx" else ".json"
            if suffix != expected_suffix:
                expected_name = "DOCX" if track == "docx" else "JSON"
                return JSONResponse({"error": f"当前模式需要上传 {expected_name} 简历文件。"}, status_code=400)
            master_cv: dict[str, Any] | None = None
            if track == "latex":
                try:
                    master_cv = json.loads(source_bytes)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    return JSONResponse({"error": f"Master CV JSON 无法解析：{error}"}, status_code=400)
                if not isinstance(master_cv, dict):
                    return JSONResponse({"error": "Master CV JSON 顶层必须是对象。"}, status_code=400)

        output_root = request.app.state.output_root
        run_dir = output_root / uuid.uuid4().hex
        run_dir.mkdir(parents=True, exist_ok=False)
        service = request.app.state.service_factory(api_key, run_dir)
        try:
            if track == "docx":
                with tempfile.TemporaryDirectory(prefix="career-resume-web-") as temporary_dir:
                    source_path = Path(temporary_dir) / "source.docx"
                    source_path.write_bytes(source_bytes)
                    result = await service.generate_docx_application_package(
                        docx_source=str(source_path),
                        jd_text=jd_text,
                        output_docx=str(run_dir / "tailored-resume.docx"),
                        company_name=company_name,
                        verified_company_context=verified_context,
                        resume_language=resume_language,
                    )
            else:
                result = await service.generate_application_package(
                    jd_text=jd_text,
                    master_cv_json=master_cv,
                    company_name=company_name,
                    verified_company_context=verified_context,
                )
        finally:
            provider = getattr(service, "provider", None)
            close_provider = getattr(provider, "aclose", None)
            try:
                if close_provider:
                    await close_provider()
            finally:
                shutil.rmtree(run_dir / "source-baseline", ignore_errors=True)
    except Exception as error:  # noqa: BLE001
        # The UI boundary returns a sanitized message instead of a server traceback.
        if run_dir is not None:
            shutil.rmtree(run_dir, ignore_errors=True)
        message = str(error)
        if api_key:
            message = message.replace(api_key, "[redacted]")
        return JSONResponse({"error": message[:1200] or "申请包生成失败，请检查输入和本机 PDF 环境。"}, status_code=422)

    artifact_paths = _artifact_paths(result, track)
    output_root = request.app.state.output_root.resolve()
    safe_artifacts = {
        name: path for name, path in artifact_paths.items()
        if Path(path).is_relative_to(output_root) and Path(path).is_file()
    }
    if not safe_artifacts:
        return JSONResponse({"error": "流程结束但未找到可下载产物，请检查本机 PDF 环境。"}, status_code=500)
    job_id = uuid.uuid4().hex
    request.app.state.jobs[job_id] = safe_artifacts
    while len(request.app.state.jobs) > MAX_STORED_JOBS:
        request.app.state.jobs.popitem(last=False)
    return JSONResponse({"job_id": job_id, **_summary(result, track, safe_artifacts)})


async def download_artifact(request: Request) -> Response:
    job_id = request.path_params["job_id"]
    artifact_id = request.path_params["artifact_id"]
    artifact_paths = request.app.state.jobs.get(job_id)
    if not artifact_paths or artifact_id not in artifact_paths:
        return JSONResponse({"error": "下载链接已过期，请重新生成申请包。"}, status_code=404)
    path = Path(artifact_paths[artifact_id])
    if not path.is_file() or not path.is_relative_to(request.app.state.output_root.resolve()):
        return JSONResponse({"error": "下载文件不可用。"}, status_code=404)
    return FileResponse(path, filename=path.name, headers={"Cache-Control": "no-store"})


def create_app(
    *,
    output_dir: str | Path | None = None,
    service_factory: Callable[[str, Path], ApplicationService] | None = None,
) -> Starlette:
    settings = Settings.from_env()
    output_root = Path(output_dir or Path(settings.output_dir) / "web").expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    app = Starlette(routes=[
        Route("/", home, methods=["GET"]),
        Route("/api/environment", environment_status, methods=["GET"]),
        Route("/api/applications", create_application, methods=["POST"]),
        Route("/api/download/{job_id}/{artifact_id}", download_artifact, methods=["GET"]),
    ])
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    app.state.output_root = output_root
    app.state.service_factory = service_factory or _build_service
    app.state.jobs = OrderedDict()
    return app


app = create_app()


def _open_local_listener(start_port: int = 8765, tries: int = 32) -> socket.socket:
    if not 0 <= start_port <= 65535:
        raise ValueError("CAREER_SKILL_WEB_PORT must be between 0 and 65535")
    if tries < 1:
        raise ValueError("tries must be positive")
    candidate_ports = [0] if start_port == 0 else range(start_port, min(start_port + tries, 65536))
    for port in candidate_ports:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
            listener.listen(socket.SOMAXCONN)
            return listener
        except OSError:
            listener.close()
    raise RuntimeError("没有找到可用的本机网页端口。")


def main() -> None:
    try:
        preferred_port = int(os.getenv("CAREER_SKILL_WEB_PORT", "8765"))
    except ValueError as error:
        raise SystemExit("CAREER_SKILL_WEB_PORT must be an integer between 0 and 65535") from error
    listener = _open_local_listener(preferred_port)
    port = listener.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    print(f"Career Resume Skill 本机网页已启动：{url}")
    print("关闭此窗口即可停止。API Key 与上传文件不会写入网页配置。")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, access_log=False, server_header=False)
    try:
        uvicorn.Server(config).run(sockets=[listener])
    finally:
        listener.close()


if __name__ == "__main__":
    main()