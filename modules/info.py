import html
import imgkit
import io
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import psutil

from core.client import APP_VERSION
from core.module import Module, command

START_TIME = time.time()
BANNER_WIDTH = 1200
BANNER_HEIGHT = 375
# requires: imgkit psutil


class InfoModule(Module):
    name = "Info"
    description = "Displays Zenkai info card and runtime details."

    def _format_uptime(self):
        total = max(0, int(time.time() - START_TIME))
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}:{minutes:02}:{seconds:02}"

    def _get_os_name(self):
        if os.name == "nt":
            return platform.platform()
        try:
            with open("/etc/os-release", "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("PRETTY_NAME="):
                        return line.split("=", 1)[1].strip().strip('"')
        except Exception:
            pass
        return f"{platform.system()} {platform.release()}".strip()

    def _get_branch(self):
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            branch = (result.stdout or "").strip()
            if branch:
                return branch
        except Exception:
            pass
        return "beta"

    def _get_host_label(self):
        cloud_markers = [
            "DYNO",
            "RAILWAY_ENVIRONMENT",
            "RENDER",
            "K_SERVICE",
            "FLY_APP_NAME",
            "DOCKER",
        ]
        if any(os.getenv(key) for key in cloud_markers):
            return "VDS"
        return "VDS" if os.name != "nt" else "Desktop"

    def _find_browser(self):
        candidates = [
            os.getenv("ZENKAI_BROWSER"),
            shutil.which("chrome"),
            shutil.which("msedge"),
            shutil.which("chromium"),
            shutil.which("google-chrome"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            "/usr/bin/microsoft-edge",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ]
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate
        return None

    def _find_wkhtmltoimage(self):
        candidates = [
            os.getenv("WKHTMLTOIMAGE_BINARY"),
            os.getenv("ZENKAI_WKHTMLTOIMAGE"),
            shutil.which("wkhtmltoimage"),
            r"C:\Program Files\wkhtmltopdf\bin\wkhtmltoimage.exe",
            r"C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltoimage.exe",
            "/usr/bin/wkhtmltoimage",
            "/usr/local/bin/wkhtmltoimage",
        ]
        for candidate in candidates:
            if candidate and os.path.exists(candidate):
                return candidate
        return None

    def _render_banner_html(self, data):
        username = html.escape(data["username"])
        host = html.escape(data["host"])
        ping = html.escape(data["ping"])
        uptime = html.escape(data["uptime"])
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <style>
    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}
    html, body {{
      width: {BANNER_WIDTH}px;
      height: {BANNER_HEIGHT}px;
      overflow: hidden;
      font-family: "Segoe UI", "Inter", "Montserrat", sans-serif;
      background: linear-gradient(145deg, #0a0c1a 0%, #1a1f3a 50%, #2a2f55 100%);
      color: #ffffff;
    }}
    body {{
      position: relative;
    }}
    #card-root {{
      width: {BANNER_WIDTH}px;
      height: {BANNER_HEIGHT}px;
      padding: 20px;
      display: flex;
      align-items: center;
    }}
    .hero {{
      position: relative;
      width: 100%;
      height: 100%;
      border-radius: 28px;
      padding: 25px 35px;
      background: linear-gradient(165deg, rgba(10, 12, 26, 0.95), rgba(22, 27, 48, 0.98));
      border: 1px solid rgba(110, 130, 255, 0.3);
      box-shadow:
        0 20px 40px -8px rgba(0, 0, 0, 0.6),
        0 0 0 1px rgba(160, 180, 255, 0.1) inset;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      justify-content: center;
    }}
    .hero::before {{
      content: '';
      position: absolute;
      top: -50%;
      right: -20%;
      width: 500px;
      height: 500px;
      background: radial-gradient(circle, rgba(100, 120, 255, 0.25) 0%, transparent 70%);
      border-radius: 50%;
      pointer-events: none;
    }}
    .hero::after {{
      content: '';
      position: absolute;
      bottom: -30%;
      left: -10%;
      width: 400px;
      height: 400px;
      background: radial-gradient(circle, rgba(200, 100, 255, 0.18) 0%, transparent 70%);
      border-radius: 50%;
      pointer-events: none;
    }}
    .hero-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: relative;
      z-index: 2;
    }}
    .platform {{
      display: flex;
      align-items: center;
      gap: 14px;
      font-size: 28px;
      font-weight: 800;
      letter-spacing: 0.04em;
      color: #dbe4ff;
    }}
    .platform-dot {{
      width: 17px;
      height: 17px;
      border-radius: 999px;
      background: linear-gradient(135deg, #80d0ff, #7088ff);
      box-shadow: 0 0 18px rgba(100, 150, 255, 0.9);
    }}
    .user-link {{
      padding: 14px 24px;
      border-radius: 22px;
      background: linear-gradient(145deg, rgba(40, 45, 80, 0.5), rgba(25, 30, 60, 0.5));
      border: 1px solid rgba(150, 170, 255, 0.3);
      backdrop-filter: blur(8px);
      font-size: 24px;
      font-weight: 800;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      color: #e7edff;
    }}
    .hero-main {{
      position: relative;
      z-index: 2;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 30px;
      flex: 1;
    }}
    .title {{
      text-align: center;
      font-size: 88px;
      font-weight: 900;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      text-shadow:
        0 0 12px rgba(255, 255, 255, 0.95),
        0 0 28px rgba(120, 160, 255, 0.7);
    }}
    .chips {{
      display: flex;
      justify-content: center;
      align-items: flex-start;
      gap: 26px;
      width: 100%;
    }}
    .chip-wrap {{
      display: flex;
      flex-direction: column;
      align-items: center;
      min-width: 230px;
    }}
    .chip {{
      width: 230px;
      min-height: 92px;
      border-radius: 28px;
      background: linear-gradient(145deg, rgba(40, 45, 80, 0.9), rgba(25, 30, 60, 0.95));
      border: 1px solid rgba(150, 170, 255, 0.4);
      box-shadow:
        0 10px 24px rgba(0, 0, 0, 0.2),
        inset 0 0 0 1px rgba(255, 255, 255, 0.05);
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 10px;
    }}
    .chip-value {{
      font-size: 27px;
      font-weight: 900;
      letter-spacing: 0.02em;
      line-height: 1;
    }}
    .chip-label {{
      font-size: 18px;
      font-weight: 800;
      letter-spacing: 0.08em;
      color: #aab9ff;
    }}
  </style>
</head>
<body>
  <div id="card-root">
    <section class="hero">
      <div class="hero-header">
        <div class="platform"><span class="platform-dot"></span><span>{host}</span></div>
        <div class="user-link">{username}</div>
      </div>
      <div class="hero-main">
        <div class="title">ZENKAI INFO</div>
        <div class="chips">
          <div class="chip-wrap">
            <div class="chip">
              <div class="chip-value">{ping}ms</div>
              <div class="chip-label">PING</div>
            </div>
          </div>
          <div class="chip-wrap">
            <div class="chip">
              <div class="chip-value">{uptime}</div>
              <div class="chip-label">UPTIME</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</body>
</html>"""

    def _render_banner_imgkit(self, data):
        wkhtmltoimage = self._find_wkhtmltoimage()
        if not wkhtmltoimage:
            raise RuntimeError("wkhtmltoimage binary not found")
        html_content = self._render_banner_html(data)
        config = imgkit.config(wkhtmltoimage=wkhtmltoimage)
        options = {
            "format": "png",
            "width": BANNER_WIDTH,
            "height": BANNER_HEIGHT,
            "crop-w": BANNER_WIDTH,
            "crop-h": BANNER_HEIGHT,
            "quality": 100,
            "encoding": "UTF-8",
            "enable-local-file-access": "",
            "quiet": "",
            "disable-smart-width": "",
        }
        image_bytes = imgkit.from_string(html_content, False, config=config, options=options)
        if not image_bytes:
            raise RuntimeError("imgkit returned empty banner")
        buffer = io.BytesIO(image_bytes)
        buffer.name = "zenkai_info.png"
        buffer.seek(0)
        return buffer

    def _render_banner_browser(self, data):
        browser = self._find_browser()
        if not browser:
            raise RuntimeError("No Chromium-based browser found for HTML render")

        html_content = self._render_banner_html(data)
        with tempfile.TemporaryDirectory(prefix="zenkai_info_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            html_path = tmp_path / "info.html"
            image_path = tmp_path / "info.png"
            html_path.write_text(html_content, encoding="utf-8")

            variants = [
                [
                    browser,
                    "--headless=new",
                    "--disable-gpu",
                    "--no-first-run",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--hide-scrollbars",
                    "--allow-file-access-from-files",
                    f"--window-size={BANNER_WIDTH},{BANNER_HEIGHT}",
                    f"--screenshot={image_path}",
                    html_path.resolve().as_uri(),
                ],
                [
                    browser,
                    "--headless",
                    "--disable-gpu",
                    "--no-first-run",
                    "--disable-background-networking",
                    "--disable-default-apps",
                    "--hide-scrollbars",
                    "--allow-file-access-from-files",
                    f"--window-size={BANNER_WIDTH},{BANNER_HEIGHT}",
                    f"--screenshot={image_path}",
                    html_path.resolve().as_uri(),
                ],
            ]

            last_error = None
            for command in variants:
                try:
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=45,
                        check=False,
                    )
                    if result.returncode == 0 and image_path.exists() and image_path.stat().st_size > 0:
                        buffer = io.BytesIO(image_path.read_bytes())
                        buffer.name = "zenkai_info.png"
                        buffer.seek(0)
                        return buffer
                    last_error = RuntimeError((result.stderr or result.stdout or "Browser screenshot failed").strip())
                except Exception as error:
                    last_error = error

            raise last_error or RuntimeError("Unable to render banner screenshot")

    def _render_banner(self, data):
        try:
            return self._render_banner_imgkit(data)
        except Exception:
            return self._render_banner_browser(data)

    def _build_text(self, data):
        owner = data["owner"]
        return (
            "┌\n"
            f"├  【👤】 𝙾𝚠𝚗𝚎𝚛: {owner}\n"
            f"├  【🤖】 𝚅𝚎𝚛𝚜𝚒𝚘𝚗: {data['version']}\n"
            "└\n"
            "┌\n"
            f"├  【📷】 𝙿𝚛𝚎𝚏𝚒𝚡: «{data['prefix']}»\n"
            f"├  【🔄】 𝚄𝚙𝚝𝚒𝚖𝚎: {data['uptime']}\n"
            f"├  【👤】 𝙱𝚛𝚊𝚗𝚌𝚑: {data['branch']}\n"
            "└\n"
            "┌\n"
            f"├  【❗️】 𝙲𝙿𝚄: {data['cpu']}\n"
            f"├  【🛡】 𝚁𝙰𝙼: {data['ram']}\n"
            f"├  【📊】 𝙿𝚒𝚗𝚐: {data['ping']}\n"
            "└\n"
            "┌\n"
            f"├  【🛡】 𝚄𝚙𝚍𝚊𝚝𝚎: {data['update']}\n"
            f"├  【🤖】 𝙷𝚘𝚜𝚝: {data['host']}\n"
            f"├  【🤖】 𝙾𝚂: {data['os']}\n"
            f"├  【🤖】 𝙿𝚢𝚝𝚑𝚘𝚗 𝚅𝚎𝚛𝚜𝚒𝚘𝚗: {data['python_version']}\n"
            "└"
        )

    @command(name="info", aliases=["sysinfo"], description="Show Zenkai info banner.")
    async def info_cmd(self, event):
        started = time.perf_counter_ns()
        me = await self.client.get_me()
        loader = getattr(self.client, "loader", None)

        ping_ms = round((time.perf_counter_ns() - started) / 10**6, 3)
        cpu_usage = round(psutil.cpu_percent(interval=0.1), 2)
        memory = psutil.virtual_memory()
        ram_used_mb = round(memory.used / (1024 * 1024), 1)
        uptime = self._format_uptime()
        branch = self._get_branch()
        host = self._get_host_label()
        os_name = self._get_os_name()
        username = getattr(me, "username", None)
        display_name = " ".join(
            part for part in [getattr(me, "first_name", ""), getattr(me, "last_name", "")] if part
        ).strip()
        owner = f"{username} ({display_name})" if username and display_name else (username or display_name or str(getattr(me, "id", "unknown")))
        prefix = getattr(getattr(self.client, "loader", None), "prefix", ".")

        data = {
            "owner": owner,
            "username": f"@{username}" if username else owner,
            "version": APP_VERSION.split()[0],
            "prefix": prefix,
            "uptime": uptime,
            "branch": branch,
            "cpu": f"{cpu_usage:.2f}",
            "ram": f"{ram_used_mb} MB",
            "ping": f"{ping_ms}",
            "update": "Актуальная версия",
            "host": host,
            "os": os_name,
            "python_version": platform.python_version(),
            "modules": len(loader.modules) if loader else 0,
            "commands": len(loader.commands) if loader else 0,
        }

        try:
            banner = self._render_banner(data)
            await self.client.send_file(
                event.chat_id,
                banner,
                caption=self._build_text(data),
                reply_to=getattr(event, "reply_to_msg_id", None),
            )
            try:
                await event.delete()
            except Exception:
                pass
        except Exception as error:
            fallback = f"<pre>{html.escape(self._build_text(data))}</pre>\n\n<code>{html.escape(str(error))}</code>"
            await event.edit(fallback, parse_mode="html")
