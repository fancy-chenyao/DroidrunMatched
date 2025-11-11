"""
HTTP 上传服务：提供 /upload 接口与临时目录管理
"""
import asyncio
import json
import os
import uuid
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from droidrun.agent.utils.logging_utils import LoggingUtils

try:
    from aiohttp import web
except Exception as e:  # pragma: no cover
    web = None
    LoggingUtils.log_error("UploadHTTP", "aiohttp not available: {error}", error=e)


@dataclass
class UploadConfig:
    host: str
    port: int
    tmp_root: str
    ttl_seconds: int = 3600  # 默认1小时


class UploadHTTPServer:
    """
    轻量HTTP服务，仅用于接收multipart图片并落盘，返回引用
    目录结构：{tmp_root}/{device_id}/{request_id}/{timestamp}_{uuid}.jpg
    """

    def __init__(self, config: UploadConfig):
        self._cfg = config
        self._app: Optional["web.Application"] = None
        self._runner: Optional["web.AppRunner"] = None
        self._site: Optional["web.TCPSite"] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        os.makedirs(self._cfg.tmp_root, exist_ok=True)

    async def start(self):
        if web is None:
            raise RuntimeError("aiohttp not installed")

        self._app = web.Application(client_max_size=10 * 1024 * 1024)  # 10MB
        self._app.add_routes([
            web.post("/upload", self._handle_upload),
            web.get("/files/{device_id}/{request_id}/{file_id}", self._handle_get_file),
        ])
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._cfg.host, self._cfg.port)
        await self._site.start()
        LoggingUtils.log_success(
            "UploadHTTP",
            "Upload server started on {host}:{port}, tmp_root={root}",
            host=self._cfg.host,
            port=self._cfg.port,
            root=self._cfg.tmp_root,
        )
        # 启动TTL清理任务
        self._cleanup_task = asyncio.create_task(self._ttl_cleanup_loop())

    async def stop(self):
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        if self._site:
            await self._site.stop()
        if self._runner:
            await self._runner.cleanup()
        LoggingUtils.log_success("UploadHTTP", "Upload server stopped")

    async def _handle_upload(self, request: "web.Request") -> "web.Response":
        """
        接收 multipart/form-data：
        - device_id (text)
        - request_id (text, 可选)
        - file (binary)
        """
        t0 = time.time()
        reader = await request.multipart()
        device_id = None
        request_id = None
        content_type = None
        size = 0
        filename = None

        # 逐项读取字段
        file_bytes = bytearray()
        try:
            while True:
                part = await reader.next()
                if part is None:
                    break
                if part.name == "device_id":
                    device_id = (await part.text()).strip()
                elif part.name == "request_id":
                    request_id = (await part.text()).strip()
                elif part.name == "file":
                    # 读取文件内容
                    content_type = part.headers.get("Content-Type", "application/octet-stream")
                    filename = part.filename or "upload.bin"
                    while True:
                        chunk = await part.read_chunk()  # 8192 bytes by default.
                        if not chunk:
                            break
                        file_bytes.extend(chunk)
                else:
                    # 忽略未知字段
                    _ = await part.read()  # 读掉
        except Exception as e:
            LoggingUtils.log_error("UploadHTTP", "Failed to parse multipart: {error}", error=e)
            return web.json_response({"status": "error", "error": "Invalid multipart"}, status=400)

        if not device_id:
            return web.json_response({"status": "error", "error": "device_id required"}, status=400)
        request_id = request_id or "session"
        size = len(file_bytes)
        if size == 0:
            return web.json_response({"status": "error", "error": "empty file"}, status=400)

        # 决定扩展名（优先使用上传的文件名后缀，其次按 Content-Type 判断）
        def _infer_ext(fname: Optional[str], ctype: Optional[str]) -> str:
            if fname:
                lower = fname.lower()
                if lower.endswith(".json"):
                    return ".json"
                if lower.endswith(".png"):
                    return ".png"
                if lower.endswith(".jpg") or lower.endswith(".jpeg"):
                    return ".jpg"
            if ctype:
                cl = ctype.lower()
                if "application/json" in cl:
                    return ".json"
                if "png" in cl:
                    return ".png"
                if "jpg" in cl or "jpeg" in cl:
                    return ".jpg"
            return ".bin"
        ext = _infer_ext(filename, content_type)

        # 构建路径
        safe_device = "".join(c for c in device_id if c.isalnum() or c in "-_")
        safe_req = "".join(c for c in request_id if c.isalnum() or c in "-_")
        session_dir = os.path.join(self._cfg.tmp_root, safe_device, safe_req)
        os.makedirs(session_dir, exist_ok=True)
        file_id = f"{int(time.time()*1000)}_{uuid.uuid4().hex}{ext}"
        file_path = os.path.join(session_dir, file_id)

        # 原子写入
        tmp_path = file_path + ".tmp"
        with open(tmp_path, "wb") as f:
            f.write(file_bytes)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)

        elapsed = int((time.time() - t0) * 1000)
        LoggingUtils.log_info(
            "UploadHTTP",
            "Uploaded file: device={device}, request={req}, size={size}B, type={ctype}, save={path}, time={ms}ms",
            device=safe_device,
            req=safe_req,
            size=size,
            ctype=content_type,
            path=file_path,
            ms=elapsed,
        )
        # 可公开访问的URL（用于客户端仅传引用）
        public_url = f"http://{self._cfg.host}:{self._cfg.port}/files/{safe_device}/{safe_req}/{file_id}"
        return web.json_response(
            {
                "status": "success",
                "file_id": file_id,
                "device_id": safe_device,
                "request_id": safe_req,
                "path": file_path,
                "url": public_url,
                "mime": content_type or "application/octet-stream",
                "size": size,
            }
        )

    async def _handle_get_file(self, request: "web.Request") -> "web.Response":
        """按URL路径返回已上传文件内容"""
        if web is None:
            raise RuntimeError("aiohttp not installed")
        device_id = request.match_info.get("device_id", "")
        request_id = request.match_info.get("request_id", "")
        file_id = request.match_info.get("file_id", "")
        # 简单校验，避免路径穿越
        def _safe(s: str) -> str:
            return "".join(c for c in s if c.isalnum() or c in "-_.")
        safe_device = _safe(device_id)
        safe_req = _safe(request_id)
        safe_file = _safe(file_id)
        file_path = os.path.join(self._cfg.tmp_root, safe_device, safe_req, safe_file)
        if not os.path.isfile(file_path):
            return web.Response(status=404, text="Not Found")
        # 猜测mime
        mime = "application/octet-stream"
        low = file_path.lower()
        if low.endswith(".png"):
            mime = "image/png"
        elif low.endswith(".jpg") or low.endswith(".jpeg"):
            mime = "image/jpeg"
        elif low.endswith(".json"):
            mime = "application/json"
        try:
            return web.FileResponse(path=file_path, headers={"Content-Type": mime})
        except Exception as e:
            LoggingUtils.log_error("UploadHTTP", "FileResponse error: {error}", error=e)
            return web.Response(status=500, text="Internal Server Error")

    async def _ttl_cleanup_loop(self):
        while True:
            try:
                await asyncio.sleep(180)  # 3分钟轮询
                self.cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                LoggingUtils.log_error("UploadHTTP", "TTL cleanup error: {error}", error=e)

    def cleanup_expired(self):
        """清理超过 TTL 的目录/文件"""
        now = time.time()
        ttl = self._cfg.ttl_seconds
        removed = 0
        for device in os.listdir(self._cfg.tmp_root):
            dpath = os.path.join(self._cfg.tmp_root, device)
            if not os.path.isdir(dpath):
                continue
            for req in os.listdir(dpath):
                rpath = os.path.join(dpath, req)
                if not os.path.isdir(rpath):
                    continue
                # 如果目录下所有文件都过期，则删除整个请求目录
                stale = True
                for fname in os.listdir(rpath):
                    fpath = os.path.join(rpath, fname)
                    try:
                        mtime = os.path.getmtime(fpath)
                        if now - mtime <= ttl:
                            stale = False
                            break
                    except Exception:
                        continue
                if stale:
                    try:
                        for fname in os.listdir(rpath):
                            try:
                                os.remove(os.path.join(rpath, fname))
                                removed += 1
                            except Exception:
                                pass
                        os.rmdir(rpath)
                        LoggingUtils.log_info("UploadHTTP", "Removed expired request dir: {path}", path=rpath)
                    except Exception:
                        pass
        if removed:
            LoggingUtils.log_info("UploadHTTP", "Removed {count} expired files", count=removed)

    def resolve_ref_to_bytes(self, path: str) -> Tuple[bytes, str]:
        """根据本地路径读取图片字节与推断mime"""
        with open(path, "rb") as f:
            data = f.read()
        mime = "image/jpeg"
        lp = path.lower()
        if lp.endswith(".png"):
            mime = "image/png"
        return data, mime


