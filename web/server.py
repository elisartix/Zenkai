import asyncio
import hmac
import inspect
import io
import json
import logging
import os
import re
import secrets
import time
from pathlib import Path

import aiohttp_jinja2
import jinja2
import qrcode
from aiohttp import web
from telethon.errors import SessionPasswordNeededError
from telethon.utils import parse_phone

from web.credentials import WebCredentials

try:
    from telethon.errors import FloodWaitError
except ImportError:
    FloodWaitError = None

try:
    from telethon.errors import PasswordHashInvalidError
except ImportError:
    PasswordHashInvalidError = None

try:
    from telethon.errors import PhoneCodeExpiredError
except ImportError:
    PhoneCodeExpiredError = None

try:
    from telethon.errors import PhoneCodeInvalidError
except ImportError:
    PhoneCodeInvalidError = None

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = "zenkai_config.json"
SESSION_NAME = "zenkai_session"
SESSION_TTL = 3600
MAX_AUTH_ATTEMPTS = 5
AUTH_LOCKOUT_SECONDS = 300


class WebServer:
    def __init__(self, client):
        self.app = web.Application()
        self.client = client
        self.runner = None
        self.port = 8080
        self.qr_login = None
        self.qr_requires_password = False
        self.qr_created_at = 0
        self.api_id = None
        self.api_hash = None
        self.phone_code_hashes = {}
        self.setup_finish_required = False
        self.clients_set = asyncio.Event()
        self._dash_sessions = {}
        self._dash_csrf_tokens = {}
        self._dash_auth_attempts = {}
        self._dash_start_time = time.time()
        self._web_creds = None

        self._load_api_config()

        jin2_loader = jinja2.FileSystemLoader(str(BASE_DIR / "web" / "templates"))
        aiohttp_jinja2.setup(self.app, loader=jin2_loader)
        self._jinja_loader = jin2_loader
        self.setup_routes()

    def _load_api_config(self):
        env_api_id = os.environ.get("API_ID")
        env_api_hash = os.environ.get("API_HASH")
        if env_api_id and env_api_hash:
            try:
                self.api_id = int(env_api_id)
                self.api_hash = env_api_hash
                return
            except ValueError:
                logger.warning("API_ID from environment is not a valid integer")

        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
                    data = json.load(handle)
                self.api_id = data.get("api_id")
                self.api_hash = data.get("api_hash")
            except Exception as e:
                logger.error("Error reading config: %s", e)

    def _read_config(self):
        if not os.path.exists(CONFIG_PATH):
            return {}
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            return {}

    def _write_config(self, data):
        with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)

    def _save_api_config(self):
        data = self._read_config()
        data.update({"api_id": self.api_id, "api_hash": self.api_hash})
        self._write_config(data)

    def _has_api(self):
        return bool(self.api_id and self.api_hash and int(self.api_id) != 12345)

    @staticmethod
    def _current_api_id(client):
        return getattr(client, "api_id", getattr(client, "_api_id", None))

    async def _ensure_real_client(self):
        if not self._has_api():
            return

        current_api_id = self._current_api_id(self.client)
        if current_api_id == 12345 or current_api_id is None:
            await self.client.disconnect()
            from core.client import ZenkaiTelegramClient

            loader = getattr(self.client, "loader", None)
            self.client = ZenkaiTelegramClient(SESSION_NAME, self.api_id, self.api_hash)
            if loader is not None:
                loader.client = self.client
                self.client.loader = loader
            self.app["client"] = self.client

    async def _connect_client(self):
        await self._ensure_real_client()
        if not self.client.is_connected():
            await self.client.connect()

    async def wait_for_clients_setup(self):
        return await self.clients_set.wait()

    def setup_routes(self):
        static_dir = BASE_DIR / "web" / "static"
        self.app.router.add_static("/static/", path=str(static_dir), name="static")
        self.app.router.add_get("/favicon.ico", self.favicon)

        self.app.router.add_get("/", self.handle_dash_root)
        self.app.router.add_get("/login", self.handle_dash_root)
        self.app.router.add_get("/dashboard", self.handle_dashboard)
        self.app.router.add_get("/api/csrf", self.api_csrf)
        self.app.router.add_post("/api/login", self.api_login)
        self.app.router.add_post("/api/auth_key", self.api_auth_key)
        self.app.router.add_get("/api/auth_key_login/{token}", self.api_auth_key_login)
        self.app.router.add_post("/api/logout", self.api_logout)
        self.app.router.add_get("/api/dashboard", self.api_dashboard)
        self.app.router.add_get("/api/modules", self.api_modules)
        self.app.router.add_post("/api/modules/toggle", self.api_modules_toggle)
        self.app.router.add_get("/api/modules/config/{name}", self.api_modules_config_get)
        self.app.router.add_post("/api/modules/config/{name}", self.api_modules_config_save)
        self.app.router.add_post("/api/terminal/exec", self.api_terminal_exec)
        self.app.router.add_get("/api/setup/status", self.api_setup_status)
        self.app.router.add_post("/api/setup/reset", self.api_setup_reset)

        self.app.router.add_put("/set_api", self.set_tg_api)
        self.app.router.add_post("/send_tg_code", self.send_tg_code)
        self.app.router.add_post("/tg_code", self.tg_code)
        self.app.router.add_post("/qr_2fa", self.qr_2fa)
        self.app.router.add_post("/init_qr_login", self.init_qr_login)
        self.app.router.add_post("/get_qr_url", self.get_qr_url)
        self.app.router.add_post("/custom_bot", self.custom_bot)
        self.app.router.add_post("/finish_login", self.finish_login)
        self.app.router.add_post("/check_session", self.check_session)
        self.app.router.add_post("/web_auth", self.web_auth)
        self.app.router.add_post("/can_add", self.can_add)

        self.app.router.add_get("/telegram", self.handle_telegram_index)
        self.app.router.add_get("/api_setup", self.handle_api_setup)
        self.app.router.add_post("/api_submit", self.handle_api_submit)
        self.app.router.add_get("/qr", self.handle_qr)
        self.app.router.add_get("/check_qr", self.handle_check_qr)
        self.app.router.add_get("/phone", self.handle_phone)
        self.app.router.add_post("/phone_submit", self.handle_phone_submit)
        self.app.router.add_post("/code_submit", self.handle_code_submit)
        self.app.router.add_get("/password", self.handle_password)
        self.app.router.add_post("/password_submit", self.handle_password_submit)

    @staticmethod
    async def favicon(_):
        return web.Response(status=204)

    def _static_file(self, name):
        return BASE_DIR / "web" / "static" / name

    def _cleanup_expired(self):
        now = time.time()
        self._dash_sessions = {
            token: created
            for token, created in self._dash_sessions.items()
            if now - created < SESSION_TTL
        }
        self._dash_csrf_tokens = {
            token: created
            for token, created in self._dash_csrf_tokens.items()
            if now - created < 600
        }

    def _is_dash_authenticated(self, request):
        token = request.cookies.get("dash_session", "")
        if not token:
            return False
        created = self._dash_sessions.get(token, 0)
        if time.time() - created > SESSION_TTL:
            self._dash_sessions.pop(token, None)
            return False
        return True

    def _check_rate_limit(self, ip):
        now = time.time()
        attempts = self._dash_auth_attempts.get(ip, [])
        attempts = [item for item in attempts if now - item < AUTH_LOCKOUT_SECONDS]
        self._dash_auth_attempts[ip] = attempts
        return len(attempts) >= MAX_AUTH_ATTEMPTS

    def _record_attempt(self, ip):
        self._dash_auth_attempts.setdefault(ip, []).append(time.time())

    def _create_session(self):
        token = secrets.token_urlsafe(32)
        self._dash_sessions[token] = time.time()
        return token

    def _validate_csrf(self, body):
        token = body.get("csrf_token", "")
        if not token or token not in self._dash_csrf_tokens:
            return False
        if time.time() - self._dash_csrf_tokens[token] > 600:
            self._dash_csrf_tokens.pop(token, None)
            return False
        self._dash_csrf_tokens.pop(token, None)
        return True

    def _check_session(self, request):
        return self._is_dash_authenticated(request)

    async def handle_dash_root(self, request):
        if self._is_dash_authenticated(request):
            raise web.HTTPFound("/dashboard")
        return web.FileResponse(self._static_file("login.html"))

    async def handle_dashboard(self, request):
        if not self._is_dash_authenticated(request):
            raise web.HTTPFound("/")
        return web.FileResponse(self._static_file("dashboard.html"))

    async def api_csrf(self, _):
        self._cleanup_expired()
        token = secrets.token_urlsafe(24)
        self._dash_csrf_tokens[token] = time.time()
        return web.json_response({"csrf_token": token})

    async def api_login(self, request):
        ip = request.remote or "unknown"
        if self._check_rate_limit(ip):
            return web.json_response({"error": "Too many attempts. Try again later."}, status=429)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid request"}, status=400)

        if not self._validate_csrf(body):
            return web.json_response({"error": "Invalid CSRF token"}, status=403)

        if not self._web_creds:
            return web.json_response({"error": "Server not ready"}, status=503)

        username = body.get("username", "")
        password = body.get("password", "")
        valid = hmac.compare_digest(username, self._web_creds.username) and hmac.compare_digest(
            password, self._web_creds.password
        )
        if not valid:
            self._record_attempt(ip)
            return web.json_response({"error": "Invalid credentials"}, status=401)

        response = web.json_response({"success": True})
        response.set_cookie(
            "dash_session",
            self._create_session(),
            max_age=SESSION_TTL,
            httponly=True,
            samesite="Strict",
        )
        return response

    async def api_auth_key(self, request):
        ip = request.remote or "unknown"
        if self._check_rate_limit(ip):
            return web.json_response({"error": "Too many attempts. Try again later."}, status=429)

        try:
            body = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid request"}, status=400)

        if not self._validate_csrf(body):
            return web.json_response({"error": "Invalid CSRF token"}, status=403)

        auth_key = body.get("auth_key", "")
        if not self._web_creds or not hmac.compare_digest(auth_key, self._web_creds.auth_key):
            self._record_attempt(ip)
            return web.json_response({"error": "Invalid auth key"}, status=401)

        response = web.json_response({"success": True})
        response.set_cookie(
            "dash_session",
            self._create_session(),
            max_age=SESSION_TTL,
            httponly=True,
            samesite="Strict",
        )
        return response

    async def api_auth_key_login(self, request):
        token = request.match_info.get("token", "")
        if not self._web_creds or not hmac.compare_digest(token, self._web_creds.auth_key):
            return web.json_response({"error": "Invalid token"}, status=401)

        response = web.HTTPFound("/dashboard")
        response.set_cookie(
            "dash_session",
            self._create_session(),
            max_age=SESSION_TTL,
            httponly=True,
            samesite="Strict",
        )
        return response

    async def api_logout(self, request):
        if not await self._json_with_csrf(request):
            return web.json_response({"error": "Invalid CSRF token"}, status=403)

        token = request.cookies.get("dash_session", "")
        self._dash_sessions.pop(token, None)
        response = web.json_response({"success": True})
        response.del_cookie("dash_session")
        return response

    async def _json_with_csrf(self, request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        return body if self._validate_csrf(body) else None

    @staticmethod
    def _account_context(me):
        username = f"@{me.username}" if getattr(me, "username", None) else "username не задан"
        phone = f"+{me.phone}" if getattr(me, "phone", None) else "скрыт"
        full_name = " ".join(
            part for part in [getattr(me, "first_name", None), getattr(me, "last_name", None)] if part
        ) or "Telegram account"
        initials = "".join(part[0] for part in full_name.split()[:2]).upper() or "E"
        return {
            "full_name": full_name,
            "username": username,
            "phone": phone,
            "user_id": me.id,
            "initials": initials,
            "premium": bool(getattr(me, "premium", False)),
        }

    async def _account_list(self):
        if not self._has_api():
            return []

        try:
            if not self.client.is_connected():
                await self.client.connect()
            if not await self.client.is_user_authorized():
                return []
            me = await self.client.get_me()
            loader = getattr(self.client, "loader", None)
            name = " ".join(
                part for part in [getattr(me, "first_name", None), getattr(me, "last_name", None)] if part
            ) or "Unknown"
            return [
                {
                    "id": me.id,
                    "name": name,
                    "username": getattr(me, "username", "") or "",
                    "phone": f"+{me.phone}" if getattr(me, "phone", None) else "Hidden",
                    "online": self.client.is_connected(),
                    "modules": len(getattr(loader, "modules", []) or []),
                }
            ]
        except Exception:
            return []

    async def api_dashboard(self, request):
        if not self._is_dash_authenticated(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        loader = getattr(self.client, "loader", None)
        modules = len(getattr(loader, "modules", []) or [])
        accounts = await self._account_list()
        return web.json_response(
            {
                "accounts": len(accounts),
                "modules": modules,
                "uptime": int(time.time() - self._dash_start_time),
                "sessions": len(self._dash_sessions),
                "accounts_list": accounts,
            }
        )

    @staticmethod
    def _module_key(module):
        return module.__class__.__name__

    @staticmethod
    def _module_name(module):
        strings = getattr(module, "strings", {})
        return getattr(module, "name", None) or (
            strings.get("name") if isinstance(strings, dict) else None
        ) or module.__class__.__name__

    @staticmethod
    def _module_is_core(module):
        core_names = {"Help", "Loader", "LoaderCommands", "Config", "Eval", "APIGuard"}
        return WebServer._module_name(module) in core_names

    @staticmethod
    def _module_commands(module):
        commands = []
        seen = set()
        for name, func in getattr(module, "commands", {}).items():
            if name in seen:
                continue
            seen.add(name)
            commands.append(
                {
                    "name": name,
                    "description": getattr(func, "description", None)
                    or getattr(func, "command_description", None)
                    or inspect.getdoc(func)
                    or "",
                }
            )
        return sorted(commands, key=lambda item: item["name"])

    def _disabled_modules(self):
        loader = getattr(self.client, "loader", None)
        if not loader:
            return set()
        state = loader._module_state.setdefault("_zenkai_dashboard", {"disabled_modules": []})
        return set(state.get("disabled_modules", []) or [])

    def _set_disabled_modules(self, disabled):
        loader = getattr(self.client, "loader", None)
        if not loader:
            return
        loader._module_state["_zenkai_dashboard"] = {"disabled_modules": sorted(disabled)}

    def _find_module(self, module_ref):
        loader = getattr(self.client, "loader", None)
        if not loader:
            return None

        module_ref = (module_ref or "").strip()
        if ":" in module_ref:
            _, module_ref = module_ref.split(":", 1)

        needle = module_ref.lower()
        for module in getattr(loader, "modules", []) or []:
            names = {
                self._module_key(module).lower(),
                self._module_name(module).lower(),
                getattr(module, "name", "").lower(),
            }
            if needle in names:
                return module
        return None

    async def api_modules(self, request):
        if not self._is_dash_authenticated(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        loader = getattr(self.client, "loader", None)
        modules = []
        disabled = self._disabled_modules()
        account_id = getattr(self.client, "tg_id", None) or 0
        for module in getattr(loader, "modules", []) or []:
            key = self._module_key(module)
            modules.append(
                {
                    "id": f"{account_id}:{key}",
                    "name": self._module_name(module),
                    "class_name": key,
                    "account_id": account_id,
                    "description": inspect.getdoc(module) or getattr(module, "description", "") or "",
                    "enabled": key not in disabled,
                    "core": self._module_is_core(module),
                    "commands": self._module_commands(module),
                }
            )
        return web.json_response({"modules": modules})

    async def api_modules_toggle(self, request):
        if not self._is_dash_authenticated(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        body = await self._json_with_csrf(request)
        if body is None:
            return web.json_response({"error": "Invalid CSRF token"}, status=403)

        module = self._find_module(body.get("module", ""))
        if not module:
            return web.json_response({"error": "Module not found"}, status=404)
        if self._module_is_core(module):
            return web.json_response({"error": "Core modules cannot be disabled"}, status=403)

        loader = getattr(self.client, "loader", None)
        enabled = bool(body.get("enabled", True))
        key = self._module_key(module)
        disabled = self._disabled_modules()

        if enabled:
            disabled.discard(key)
            for name, func in getattr(module, "commands", {}).items():
                loader.commands[name] = func
        else:
            disabled.add(key)
            for name, func in list(loader.commands.items()):
                if getattr(func, "__self__", None) is module:
                    loader.commands.pop(name, None)

        module.disabled = not enabled
        self._set_disabled_modules(disabled)
        return web.json_response({"success": True, "enabled": enabled})

    @staticmethod
    def _json_safe(value):
        try:
            json.dumps(value)
            return value
        except TypeError:
            return str(value)

    @staticmethod
    def _coerce_config_value(current, value):
        if isinstance(current, bool):
            if isinstance(value, bool):
                return value
            return str(value).lower() in {"1", "true", "yes", "on", "да"}
        if isinstance(current, int) and not isinstance(current, bool):
            return int(value)
        if isinstance(current, float):
            return float(value)
        if isinstance(current, (list, dict)) and isinstance(value, str):
            return json.loads(value)
        return value

    async def api_modules_config_get(self, request):
        if not self._is_dash_authenticated(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        module = self._find_module(request.match_info.get("name", ""))
        if not module:
            return web.json_response({"error": "Module not found"}, status=404)

        config = {}
        module_config = getattr(module, "config", None)
        if module_config:
            for key in module_config:
                config[key] = self._json_safe(module_config[key])

        account_id = getattr(self.client, "tg_id", None) or 0
        return web.json_response(
            {
                "id": f"{account_id}:{self._module_key(module)}",
                "name": self._module_name(module),
                "class_name": self._module_key(module),
                "account_id": account_id,
                "config": config,
                "commands": self._module_commands(module),
            }
        )

    async def api_modules_config_save(self, request):
        if not self._is_dash_authenticated(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        body = await self._json_with_csrf(request)
        if body is None:
            return web.json_response({"error": "Invalid CSRF token"}, status=403)

        module = self._find_module(request.match_info.get("name", ""))
        if not module:
            return web.json_response({"error": "Module not found"}, status=404)

        module_config = getattr(module, "config", None)
        key = body.get("key", "")
        if not module_config or key not in module_config:
            return web.json_response({"error": "Unknown config key"}, status=404)

        try:
            value = self._coerce_config_value(module_config[key], body.get("value"))
            module_config[key] = value
            return web.json_response({"success": True, "value": self._json_safe(module_config[key])})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def api_terminal_exec(self, request):
        if not self._is_dash_authenticated(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        body = await self._json_with_csrf(request)
        if body is None:
            return web.json_response({"error": "Invalid CSRF token"}, status=403)

        command = str(body.get("command", "")).strip()
        if not command:
            return web.json_response({"error": "Empty command"}, status=400)

        dangerous = [
            r"rm\s+-rf",
            r"mkfs",
            r"dd\s+if=",
            r":\(\)\s*\{\s*:\|:&",
            r">\s*/dev/sd",
            r"\bshutdown\b",
            r"\breboot\b",
            r"\bpoweroff\b",
            r"\bhalt\b",
            r"curl.*\|.*sh",
            r"wget.*\|.*sh",
            r"\bformat\s",
            r"\bdel\s+/",
            r"\brd\s+/s",
        ]
        for pattern in dangerous:
            if re.search(pattern, command, re.IGNORECASE):
                return web.json_response({"error": "Command blocked for security"}, status=403)

        try:
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(BASE_DIR),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
            output = stdout.decode("utf-8", errors="replace")
            if stderr:
                output += ("\n" if output else "") + stderr.decode("utf-8", errors="replace")
            return web.json_response({"output": output or "(no output)"})
        except asyncio.TimeoutError:
            return web.json_response({"error": "Command timed out (10s)"}, status=408)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def api_setup_status(self, request):
        if not self._is_dash_authenticated(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        authorized = False
        try:
            if self.client.is_connected():
                authorized = await self.client.is_user_authorized()
        except Exception:
            authorized = False

        return web.json_response(
            {
                "needs_setup": not authorized,
                "has_api": self._has_api(),
                "accounts": 1 if authorized else 0,
            }
        )

    async def api_setup_reset(self, request):
        if not self._is_dash_authenticated(request):
            return web.json_response({"error": "Unauthorized"}, status=401)

        self.qr_login = None
        self.qr_requires_password = False
        self.qr_created_at = 0
        return web.json_response({"success": True})

    async def set_tg_api(self, request):
        if not self._check_session(request):
            return web.Response(status=401, text="Authorization required")

        text = (await request.text()).strip()
        if len(text) < 33:
            return web.Response(status=400, text="API ID and HASH pair has invalid length")

        api_hash = text[:32]
        api_id = text[32:]
        if not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash) or not api_id.isdigit():
            return web.Response(status=400, text="You specified invalid API ID and/or API HASH")

        self.api_id = int(api_id)
        self.api_hash = api_hash
        self._save_api_config()
        await self._ensure_real_client()
        return web.Response(text="ok")

    @staticmethod
    def _render_fw_error(error):
        seconds = getattr(error, "seconds", 0)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        parts = []
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        parts.append(f"{seconds}s")
        return "FloodWait: wait " + " ".join(parts) + " and try again."

    async def send_tg_code(self, request):
        if not self._check_session(request):
            return web.Response(status=401, text="Authorization required")
        if not self._has_api():
            return web.Response(status=400, text="Telegram API credentials are not configured")

        phone = parse_phone(await request.text())
        if not phone:
            return web.Response(status=400, text="Invalid phone number")

        self.setup_finish_required = True
        self.clients_set.clear()
        self.qr_login = None
        self.qr_requires_password = False

        await self._connect_client()
        try:
            sent = await self.client.send_code_request(phone)
            self.phone_code_hashes[phone] = sent.phone_code_hash
            return web.Response(text="ok")
        except Exception as e:
            if FloodWaitError is not None and isinstance(e, FloodWaitError):
                return web.Response(status=429, text=self._render_fw_error(e))
            logger.exception("Failed to send Telegram code")
            return web.Response(status=500, text=str(e))

    async def tg_code(self, request):
        if not self._check_session(request):
            return web.Response(status=401, text="Authorization required")

        text = await request.text()
        parts = text.split("\n", 2)
        if len(parts) not in {2, 3}:
            return web.Response(status=400, text="Invalid request")

        code = parts[0].strip()
        phone = parse_phone(parts[1])
        password = parts[2].strip() if len(parts) == 3 else ""
        if not phone:
            return web.Response(status=400, text="Invalid phone number")

        try:
            if password:
                await self.client.sign_in(password=password)
            else:
                await self.client.sign_in(
                    phone=phone,
                    code=code,
                    phone_code_hash=self.phone_code_hashes.get(phone),
                )
            return web.Response(text="SUCCESS")
        except SessionPasswordNeededError:
            return web.Response(status=401, text="2FA Password required")
        except Exception as e:
            if PhoneCodeExpiredError is not None and isinstance(e, PhoneCodeExpiredError):
                return web.Response(status=404, text="Code expired")
            if PhoneCodeInvalidError is not None and isinstance(e, PhoneCodeInvalidError):
                return web.Response(status=403, text="Invalid code")
            if PasswordHashInvalidError is not None and isinstance(e, PasswordHashInvalidError):
                return web.Response(status=403, text="Invalid 2FA password")
            if FloodWaitError is not None and isinstance(e, FloodWaitError):
                return web.Response(status=421, text=self._render_fw_error(e))
            logger.exception("Telegram code login failed")
            return web.Response(status=500, text=str(e))

    async def init_qr_login(self, request):
        if not self._check_session(request):
            return web.Response(status=401, text="Authorization required")
        if not self._has_api():
            return web.Response(status=400, text="Telegram API credentials are not configured")

        self.setup_finish_required = True
        self.clients_set.clear()
        await self._connect_client()
        self.qr_login = await self.client.qr_login()
        self.qr_requires_password = False
        self.qr_created_at = time.time()
        return web.Response(text=self.qr_login.url)

    async def get_qr_url(self, request):
        if not self._check_session(request):
            return web.Response(status=401, text="Authorization required")

        await self._connect_client()
        try:
            if await self.client.is_user_authorized():
                return web.Response(status=200, text="SUCCESS")
        except Exception:
            pass

        if self.qr_requires_password:
            return web.Response(status=403, text="2FA")

        if self.qr_login is None:
            return await self.init_qr_login(request)

        try:
            await self.qr_login.wait(timeout=1)
            return web.Response(status=200, text="SUCCESS")
        except asyncio.TimeoutError:
            if time.time() - self.qr_created_at > 45:
                try:
                    await self.qr_login.recreate()
                    self.qr_created_at = time.time()
                except SessionPasswordNeededError:
                    self.qr_requires_password = True
                    return web.Response(status=403, text="2FA")
            return web.Response(status=201, text=self.qr_login.url)
        except SessionPasswordNeededError:
            self.qr_requires_password = True
            return web.Response(status=403, text="2FA")
        except Exception as e:
            logger.exception("QR login polling failed")
            return web.Response(status=500, text=str(e))

    async def qr_2fa(self, request):
        if not self._check_session(request):
            return web.Response(status=401, text="Authorization required")

        password = (await request.text()).strip()
        try:
            await self.client.sign_in(password=password)
            self.qr_requires_password = False
            return web.Response(text="SUCCESS")
        except Exception as e:
            if PasswordHashInvalidError is not None and isinstance(e, PasswordHashInvalidError):
                return web.Response(status=403, text="Invalid 2FA password")
            if FloodWaitError is not None and isinstance(e, FloodWaitError):
                return web.Response(status=421, text=self._render_fw_error(e))
            return web.Response(status=500, text=str(e))

    async def custom_bot(self, request):
        if not self._check_session(request):
            return web.Response(status=401, text="Authorization required")

        username = (await request.text()).strip().lstrip("@")
        if username:
            if not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username) or not username.lower().endswith("bot"):
                return web.Response(text="OCCUPIED")
            data = self._read_config()
            data["custom_bot"] = username
            self._write_config(data)
        return web.Response(text="OK")

    async def finish_login(self, request):
        if not self._check_session(request):
            return web.Response(status=401, text="Authorization required")

        self.setup_finish_required = False
        self.clients_set.set()
        return web.Response()

    async def check_session(self, request):
        return web.Response(text="1" if self._check_session(request) else "0")

    async def web_auth(self, request):
        if not self._check_session(request):
            return web.Response(status=401, text="Authorization required")
        return web.Response(text=request.cookies.get("dash_session", "authorized"))

    async def can_add(self, request):
        return web.Response(text="Yes")

    @aiohttp_jinja2.template("index.html")
    async def handle_telegram_index(self, request):
        if not self._has_api():
            raise web.HTTPFound("/api_setup")

        try:
            await self._connect_client()
            if await self.client.is_user_authorized():
                me = await self.client.get_me()
                return {
                    "status": "Аккаунт подключён",
                    "authorized": True,
                    "account": self._account_context(me),
                }
        except Exception as e:
            logger.debug("Telegram auth check failed: %s", e)
        return {"authorized": False, "api_ready": True}

    @aiohttp_jinja2.template("api_setup.html")
    async def handle_api_setup(self, request):
        return {"error": request.query.get("error")}

    async def handle_api_submit(self, request):
        try:
            data = await request.post()
            self.api_id = int(str(data.get("api_id", "")).strip())
            self.api_hash = str(data.get("api_hash", "")).strip()
            if not self.api_hash or self.api_id <= 0:
                raise ValueError("empty api credentials")
            self._save_api_config()
            await self._ensure_real_client()
        except Exception as e:
            logger.warning("Invalid API credentials submitted: %s", e)
            raise web.HTTPFound("/api_setup?error=invalid")

        raise web.HTTPFound("/telegram")

    @aiohttp_jinja2.template("qr.html")
    async def handle_qr(self, request):
        if not self._has_api():
            raise web.HTTPFound("/api_setup")
        try:
            await self._connect_client()
            self.qr_login = await self.client.qr_login()
            self.qr_requires_password = False
            self.qr_created_at = time.time()
            qr = qrcode.QRCode(version=1, box_size=10, border=4)
            qr.add_data(self.qr_login.url)
            qr.make(fit=True)
            image = qr.make_image(fill_color="black", back_color="white")
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            import base64

            return {
                "qr_b64": base64.b64encode(buffer.getvalue()).decode("utf-8"),
                "url": self.qr_login.url,
                "error": None,
            }
        except Exception as e:
            return {"error": str(e)}

    async def handle_check_qr(self, request):
        if not self.qr_login:
            return web.json_response({"authorized": False})

        try:
            await self.qr_login.wait(timeout=1)
            return web.json_response({"authorized": True, "requires_password": False})
        except asyncio.TimeoutError:
            return web.json_response({"authorized": False})
        except SessionPasswordNeededError:
            self.qr_requires_password = True
            return web.json_response({"authorized": False, "requires_password": True})
        except Exception as e:
            logger.error("QR Login Error: %s", e)
            return web.json_response({"authorized": False, "error": str(e)})

    @aiohttp_jinja2.template("phone.html")
    async def handle_phone(self, request):
        if not self._has_api():
            raise web.HTTPFound("/api_setup")
        return {}

    @aiohttp_jinja2.template("code.html")
    async def handle_phone_submit(self, request):
        data = await request.post()
        phone = data.get("phone")
        await self._connect_client()

        try:
            sent = await self.client.send_code_request(phone)
            self.phone_code_hashes[parse_phone(phone)] = sent.phone_code_hash
            return {"phone": phone, "phone_code_hash": sent.phone_code_hash, "error": None}
        except Exception as e:
            logger.error("Send code error: %s", e)
            return {"error": str(e)}

    @aiohttp_jinja2.template("code.html")
    async def handle_code_submit(self, request):
        data = await request.post()
        phone = data.get("phone")
        code = data.get("code")
        phone_code_hash = data.get("phone_code_hash")

        try:
            await self.client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            raise web.HTTPFound("/telegram")
        except web.HTTPFound:
            raise
        except SessionPasswordNeededError:
            return aiohttp_jinja2.render_template(
                "password.html",
                request,
                {"phone": phone, "phone_code_hash": phone_code_hash, "mode": "phone", "error": None},
            )
        except Exception as e:
            logger.error("Code submit error: %s", e)
            return {"phone": phone, "phone_code_hash": phone_code_hash, "error": str(e)}

    @aiohttp_jinja2.template("password.html")
    async def handle_password(self, request):
        if not self.qr_requires_password:
            raise web.HTTPFound("/telegram")
        return {"mode": "qr", "error": None}

    async def handle_password_submit(self, request):
        data = await request.post()
        password = data.get("password")
        mode = data.get("mode", "qr")
        try:
            await self.client.sign_in(password=password)
            raise web.HTTPFound("/telegram")
        except web.HTTPFound:
            raise
        except Exception as e:
            logger.error("Password error: %s", e)
            return aiohttp_jinja2.render_template(
                "password.html",
                request,
                {"mode": mode, "error": str(e)},
            )

    async def start(self, port=8080):
        self.port = int(os.environ.get("PORT", port))
        self._web_creds = WebCredentials(str(BASE_DIR))
        self._dash_start_time = time.time()
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "0.0.0.0", self.port)
        await site.start()
        self._web_creds.log_credentials(self.port)
        logger.info("Web server started at http://localhost:%s", self.port)
