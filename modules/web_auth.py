import html
import asyncio
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

from core.module import Module, command


class WebAuthModule(Module):
    name = "WebAuth"
    description = "Shows Web Dashboard credentials and auth links."
    _tunnel_process = None
    _tunnel_url = None
    _tunnel_lock = asyncio.Lock()

    def _root(self):
        return Path(__file__).resolve().parents[1]

    def _web_port(self):
        return int(os.environ.get("PORT", "8080"))

    def _credentials(self):
        path = "web_credentials.json"
        if not os.path.exists(path):
            return None

        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except Exception:
            return None

        if not all(data.get(key) for key in ("username", "password", "auth_key")):
            return None
        return data

    def _auth_url(self, base_url, creds):
        base_url = base_url.rstrip("/")
        return f"{base_url}/api/auth_key_login/{creds['auth_key']}"

    def _format_web_links(self, base_url, creds, label="Zenkai Web Dashboard"):
        auth_url = self._auth_url(base_url, creds)
        return (
            f"🌐 <b>{label}</b>\n\n"
            f"Login: <a href=\"{html.escape(base_url)}\">{html.escape(base_url)}</a>\n"
            f"One-click auth: <a href=\"{html.escape(auth_url)}\">open dashboard</a>\n\n"
            f"Username: <code>{html.escape(creds['username'])}</code>\n"
            f"Password: <code>{html.escape(creds['password'])}</code>"
        )

    def _platform_asset_name(self):
        system = platform.system().lower()
        machine = platform.machine().lower()

        if machine in {"x86_64", "amd64"}:
            arch = "amd64"
        elif machine in {"aarch64", "arm64"}:
            arch = "arm64"
        elif machine.startswith("arm"):
            arch = "arm"
        elif machine in {"i386", "i686", "x86"}:
            arch = "386"
        else:
            arch = machine

        if system == "windows":
            return f"cloudflared-windows-{arch}.exe"
        if system == "linux":
            return f"cloudflared-linux-{arch}"
        if system == "darwin":
            return f"cloudflared-darwin-{arch}.tgz"

        return None

    def _cloudflared_path(self):
        suffix = ".exe" if os.name == "nt" else ""
        return self._root() / ".zenkai" / "bin" / f"cloudflared{suffix}"

    def _version_path(self):
        return self._root() / ".zenkai" / "bin" / "cloudflared.version"

    def _download_json(self, url):
        request = urllib.request.Request(url, headers={"User-Agent": "Zenkai"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))

    def _download_bytes(self, url):
        request = urllib.request.Request(url, headers={"User-Agent": "Zenkai"})
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()

    def _extract_darwin_tgz(self, payload, target):
        tmp_tgz = target.with_suffix(".tgz")
        tmp_tgz.write_bytes(payload)
        try:
            with tarfile.open(tmp_tgz, "r:gz") as archive:
                member = next(
                    item for item in archive.getmembers()
                    if Path(item.name).name == "cloudflared" and item.isfile()
                )
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise RuntimeError("cloudflared binary was not found in archive")
                target.write_bytes(extracted.read())
        finally:
            try:
                tmp_tgz.unlink()
            except OSError:
                pass

    def _install_cloudflared_sync(self):
        system_binary = shutil.which("cloudflared")
        asset_name = self._platform_asset_name()
        if not asset_name:
            if system_binary:
                return Path(system_binary)
            raise RuntimeError(f"Unsupported OS/architecture: {platform.system()} {platform.machine()}")

        target = self._cloudflared_path()
        version_file = self._version_path()
        release = self._download_json("https://api.github.com/repos/cloudflare/cloudflared/releases/latest")
        latest_version = release.get("tag_name", "")

        if target.exists() and version_file.exists() and version_file.read_text(encoding="utf-8").strip() == latest_version:
            return target

        asset = next((item for item in release.get("assets", []) if item.get("name") == asset_name), None)
        if not asset:
            if system_binary:
                return Path(system_binary)
            raise RuntimeError(f"No cloudflared release asset for {asset_name}")

        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self._download_bytes(asset["browser_download_url"])

        if asset_name.endswith(".tgz"):
            self._extract_darwin_tgz(payload, target)
        else:
            target.write_bytes(payload)

        if os.name != "nt":
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

        version_file.write_text(latest_version, encoding="utf-8")
        return target

    async def _install_cloudflared(self):
        return await asyncio.to_thread(self._install_cloudflared_sync)

    def _process_alive(self):
        return self._tunnel_process is not None and self._tunnel_process.returncode is None

    async def _read_tunnel_stream(self, stream, found_url):
        pattern = re.compile(r"https://[-a-zA-Z0-9.]+\.trycloudflare\.com")
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="ignore")
            match = pattern.search(text)
            if match:
                self.__class__._tunnel_url = match.group(0)
                if not found_url.done():
                    found_url.set_result(self._tunnel_url)

    async def _start_tunnel(self, force=False):
        async with self._tunnel_lock:
            if force:
                await self._stop_tunnel()

            if self._process_alive() and self._tunnel_url:
                return self._tunnel_url

            binary = await self._install_cloudflared()
            found_url = asyncio.get_running_loop().create_future()
            self.__class__._tunnel_url = None
            self.__class__._tunnel_process = await asyncio.create_subprocess_exec(
                str(binary),
                "tunnel",
                "--url",
                f"http://localhost:{self._web_port()}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._root()),
            )

            asyncio.create_task(self._read_tunnel_stream(self._tunnel_process.stdout, found_url))
            asyncio.create_task(self._read_tunnel_stream(self._tunnel_process.stderr, found_url))

            try:
                return await asyncio.wait_for(found_url, timeout=45)
            except asyncio.TimeoutError:
                await self._stop_tunnel()
                raise RuntimeError("cloudflared did not return a tunnel URL in time")

    async def _stop_tunnel(self):
        process = self._tunnel_process
        self.__class__._tunnel_process = None
        self.__class__._tunnel_url = None
        if process and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=8)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

    @command(name="auth", description="Show Web Dashboard auth link.")
    async def auth_cmd(self, event):
        creds = self._credentials()
        if not creds:
            return await event.edit("Web Dashboard credentials are not ready yet.")

        args = event.raw_text.split(maxsplit=1)
        key = args[1].strip() if len(args) > 1 else creds["auth_key"]
        if key != creds["auth_key"]:
            return await event.edit("Invalid Web Dashboard auth key.")

        url = f"http://localhost:8080/api/auth_key_login/{creds['auth_key']}"
        await event.edit(
            "Zenkai Web Dashboard\n\n"
            f"Login: <code>http://localhost:8080/</code>\n"
            f"One-click auth: <a href=\"{html.escape(url)}\">open dashboard</a>",
            parse_mode="html",
            link_preview=False,
        )

    @command(name="web", description="Start Web Dashboard tunnel and show public auth link.")
    async def web_cmd(self, event):
        creds = self._credentials()
        if not creds:
            return await event.edit("Web Dashboard credentials are not ready yet.")

        args = (event.raw_text.split(maxsplit=1)[1].strip().lower() if len(event.raw_text.split(maxsplit=1)) > 1 else "")

        if args in {"stop", "off", "down"}:
            await self._stop_tunnel()
            return await event.edit("🌐 <b>Web tunnel stopped.</b>", parse_mode="html")

        force = args in {"restart", "new", "reload", "-f", "--force"}
        status = await event.edit("🌐 <b>Поднимаю Cloudflare quick tunnel...</b>", parse_mode="html")
        try:
            url = await self._start_tunnel(force=force)
        except Exception as error:
            return await status.edit(
                "❌ <b>Не удалось поднять web tunnel.</b>\n"
                f"<code>{html.escape(str(error))}</code>",
                parse_mode="html",
            )

        await status.edit(
            self._format_web_links(url, creds, label="Zenkai Web Tunnel"),
            parse_mode="html",
            link_preview=False,
        )

    @command(name="webcreds", description="Show Web Dashboard login credentials.")
    async def webcreds_cmd(self, event):
        creds = self._credentials()
        if not creds:
            return await event.edit("Web Dashboard credentials are not ready yet.")

        await event.edit(
            "Zenkai Web Dashboard credentials\n\n"
            f"Username: <code>{html.escape(creds['username'])}</code>\n"
            f"Password: <code>{html.escape(creds['password'])}</code>\n"
            f"Auth Key: <code>{html.escape(creds['auth_key'])}</code>",
            parse_mode="html",
            link_preview=False,
        )
