from __future__ import annotations

import html
import io
import ipaddress
import json
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlparse
from urllib.request import ProxyHandler, Request, build_opener

MAX_BACKUP_BYTES = 2 * 1024 * 1024


def _is_local_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local


def _resolve_local_host(host: str) -> str:
    try:
        candidates = socket.getaddrinfo(host, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("无法解析同步地址") from exc
    for item in candidates:
        ip = item[4][0]
        if _is_local_ip(ip):
            return ip
    raise ValueError("同步地址必须位于本地局域网，已拒绝连接公网地址")


def discover_lan_ip() -> str:
    """Best-effort local IPv4 discovery without requiring internet access."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect selects a route but sends no application data.
        sock.connect(("192.0.2.1", 9))
        candidate = sock.getsockname()[0]
        if _is_local_ip(candidate) and not candidate.startswith("127."):
            return candidate
    except OSError:
        pass
    finally:
        sock.close()

    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM):
            candidate = item[4][0]
            if _is_local_ip(candidate) and not candidate.startswith("127."):
                return candidate
    except socket.gaierror:
        pass
    return "127.0.0.1"


def normalize_address(address: str) -> tuple[str, int]:
    value = (address or "").strip()
    if not value:
        raise ValueError("请输入电脑显示的局域网地址")
    if "://" not in value:
        value = "http://" + value
    parsed = urlparse(value)
    if parsed.scheme != "http":
        raise ValueError("局域网同步只允许 HTTP，本功能不会连接互联网")
    if not parsed.hostname:
        raise ValueError("同步地址格式不正确")
    host_ip = _resolve_local_host(parsed.hostname)
    try:
        port = parsed.port or 8765
    except ValueError as exc:
        raise ValueError("端口号不正确") from exc
    if not 1 <= port <= 65535:
        raise ValueError("端口号不正确")
    return host_ip, port


def build_sync_url(address: str, pair_code: str) -> str:
    host, port = normalize_address(address)
    code = "".join(ch for ch in (pair_code or "") if ch.isdigit())
    if len(code) != 6:
        raise ValueError("配对码应为 6 位数字")
    return f"http://{host}:{port}/sync/{code}"


def sync_with_peer(address: str, pair_code: str, local_backup: bytes, timeout: float = 8.0) -> bytes:
    if len(local_backup) > MAX_BACKUP_BYTES:
        raise ValueError("备份文件过大，已拒绝发送")
    url = build_sync_url(address, pair_code)
    req = Request(
        url,
        data=local_backup,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        # Explicitly bypass OS/application HTTP proxies (for example Clash/v2rayN).
        # LAN sync must always be a direct local connection.
        opener = build_opener(ProxyHandler({}))
        with opener.open(req, timeout=timeout) as resp:
            if resp.status != 200:
                raise ValueError(f"同步失败：HTTP {resp.status}")
            data = resp.read(MAX_BACKUP_BYTES + 1)
    except OSError as exc:
        raise ValueError("无法连接另一台设备。请确认两台设备在同一 Wi-Fi / 局域网，且防火墙允许本应用通信。") from exc
    if len(data) > MAX_BACKUP_BYTES:
        raise ValueError("对方返回的数据过大，已拒绝导入")
    return data


def qr_svg(text: str) -> str:
    """Generate an SVG QR code without Pillow/native image dependencies."""
    import qrcode
    import qrcode.image.svg

    image = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage)
    buf = io.BytesIO()
    image.save(buf)
    return buf.getvalue().decode("utf-8")


class LanSyncServer:
    def __init__(self, get_backup: Callable[[], bytes], merge_backup: Callable[[bytes], bytes]):
        self.get_backup = get_backup
        self.merge_backup = merge_backup
        self.pair_code = f"{secrets.randbelow(1_000_000):06d}"
        self.host_ip = discover_lan_ip()
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.port: int | None = None

    @property
    def address(self) -> str:
        if self.port is None:
            return ""
        return f"{self.host_ip}:{self.port}"

    @property
    def browser_url(self) -> str:
        if self.port is None:
            return ""
        return f"http://{self.host_ip}:{self.port}/pair/{self.pair_code}"

    def start(self) -> None:
        if self._httpd is not None:
            return

        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "FamilyBirthdayLAN/0.2"

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                return

            def _client_allowed(self) -> bool:
                return _is_local_ip(self.client_address[0])

            def _send(self, status: int, body: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if not self._client_allowed():
                    self._send(403, b"LAN only", "text/plain; charset=utf-8")
                    return
                path = self.path.split("?", 1)[0]
                if path == f"/backup/{owner.pair_code}":
                    payload = owner.get_backup()
                    self._send(200, payload, "application/json; charset=utf-8")
                    return
                if path == f"/pair/{owner.pair_code}":
                    page = owner._browser_page().encode("utf-8")
                    self._send(200, page, "text/html; charset=utf-8")
                    return
                if path == f"/status/{owner.pair_code}":
                    self._send(200, b'{"ok":true}', "application/json; charset=utf-8")
                    return
                self._send(404, b"Not found", "text/plain; charset=utf-8")

            def do_POST(self) -> None:  # noqa: N802
                if not self._client_allowed():
                    self._send(403, b"LAN only", "text/plain; charset=utf-8")
                    return
                path = self.path.split("?", 1)[0]
                if path != f"/sync/{owner.pair_code}":
                    self._send(403, b"Invalid pairing code", "text/plain; charset=utf-8")
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length <= 0 or length > MAX_BACKUP_BYTES:
                    self._send(413, b"Invalid backup size", "text/plain; charset=utf-8")
                    return
                raw = self.rfile.read(length)
                try:
                    merged = owner.merge_backup(raw)
                    json.loads(merged.decode("utf-8"))
                except Exception as exc:
                    msg = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
                    self._send(400, msg, "application/json; charset=utf-8")
                    return
                self._send(200, merged, "application/json; charset=utf-8")

        self._httpd = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        # ThreadingMixIn defaults to non-daemon request threads and waits for them
        # during server_close(). A desktop GUI must never be kept alive by a
        # stale HTTP request after the window is closed.
        self._httpd.daemon_threads = True
        self._httpd.block_on_close = False
        self.port = int(self._httpd.server_address[1])
        self._thread = threading.Thread(
            target=lambda: self._httpd.serve_forever(poll_interval=0.1) if self._httpd else None,
            name="birthday-lan-sync",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        httpd = self._httpd
        thread = self._thread
        if httpd is not None:
            # shutdown() asks serve_forever() to return; server_close() then
            # releases the listening socket. Request threads are daemonized in
            # start(), so they cannot keep the application process alive.
            httpd.shutdown()
            httpd.server_close()
        if thread is not None and thread is not threading.current_thread() and thread.is_alive():
            thread.join(timeout=2.0)
        self._httpd = None
        self._thread = None
        self.port = None

    def _browser_page(self) -> str:
        code = html.escape(self.pair_code)
        sync_url = f"/sync/{code}"
        backup_url = f"/backup/{code}"
        return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>家庭生日管理器 · 局域网同步</title>
<style>
body{{font-family:system-ui,-apple-system,sans-serif;max-width:680px;margin:0 auto;padding:24px;line-height:1.6}}
.card{{border:1px solid #ddd;border-radius:14px;padding:18px;margin:16px 0}}button,a.btn{{display:inline-block;padding:10px 14px;margin:6px 4px;border:0;border-radius:10px;background:#222;color:#fff;text-decoration:none;font-size:16px}}input{{max-width:100%;padding:12px}}#msg{{white-space:pre-wrap}}
</style></head><body>
<h1>家庭生日管理器</h1><p>本页面只在当前局域网中工作。配对码：<b>{code}</b></p>
<div class="card"><h2>从电脑取备份</h2><a class="btn" href="{backup_url}" download="家庭生日备份.json">下载电脑备份</a></div>
<div class="card"><h2>双向合并</h2><p>选择手机应用导出的 JSON 备份。电脑会合并两端数据，并返回合并后的备份供你重新导入手机。</p>
<input id="file" type="file" accept="application/json,.json"><br><button onclick="sync()">上传并合并</button><p id="msg"></p></div>
<script>
async function sync(){{
 const f=document.getElementById('file').files[0]; const m=document.getElementById('msg');
 if(!f){{m.textContent='请先选择 JSON 备份文件';return;}}
 m.textContent='正在同步…';
 try{{const raw=await f.arrayBuffer(); const r=await fetch('{sync_url}',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:raw}});
 if(!r.ok) throw new Error(await r.text()); const blob=await r.blob(); const u=URL.createObjectURL(blob); const a=document.createElement('a'); a.href=u; a.download='家庭生日_合并备份.json'; a.click(); URL.revokeObjectURL(u); m.textContent='同步成功：电脑已合并数据，并已下载合并后的备份。';}}
 catch(e){{m.textContent='同步失败：'+e;}}
}}
</script></body></html>"""
