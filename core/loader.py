import os
import re
import ast
import shlex
import asyncio
import importlib.metadata
import importlib.util
import inspect
import sys
import logging
import types
from telethon import events
from core.module import Module

logger = logging.getLogger(__name__)


class Loader:
    """Dynamically loads modules and registers their commands."""

    class _StateDict(dict):
        def __init__(self, owner, initial=None):
            self._owner = owner
            super().__init__(initial or {})

        def __setitem__(self, key, value):
            super().__setitem__(key, self._owner._wrap_state(value))
            self._owner._save_state()

        def setdefault(self, key, default=None):
            if key not in self:
                self[key] = default
            return dict.__getitem__(self, key)

        def pop(self, key, default=None):
            result = super().pop(key, default)
            self._owner._save_state()
            return result
    
    def __init__(self, client, prefix="."):
        self.client = client
        self.prefix = prefix
        self.modules = []  # list of module instances
        self.commands = {}  # command_name -> bound method
        self.inline_handlers = {}
        self.callback_handlers = {}
        self.inline = None
        self._handler_registered = False
        self._state_path = "zenkai_module_state.json"
        self._module_state = self._load_state()
        self._pip_attempted = set()

    def _wrap_state(self, value):
        if isinstance(value, self._StateDict):
            return value
        if isinstance(value, dict):
            return self._StateDict(self, {k: self._wrap_state(v) for k, v in value.items()})
        return value

    def _load_state(self):
        try:
            if os.path.exists(self._state_path):
                import json
                with open(self._state_path, "r", encoding="utf-8") as handle:
                    raw = json.load(handle)
                    return self._wrap_state(raw)
        except Exception:
            logger.debug("Failed to load module state", exc_info=True)
        return self._StateDict(self)

    def _save_state(self):
        try:
            import json
            with open(self._state_path, "w", encoding="utf-8") as handle:
                json.dump(self._module_state, handle, ensure_ascii=False, indent=2)
        except Exception:
            logger.debug("Failed to save module state", exc_info=True)

    @staticmethod
    def _strings_dict(data=None):
        class StringsDict(dict):
            def __call__(self, key):
                return self.get(key, key)

            def __missing__(self, key):
                return key

        return StringsDict(data or {})

    def _storage_key(self, instance, filepath):
        module_name = getattr(instance, "name", None) or instance.__class__.__name__
        return f"{filepath}:{module_name}:{instance.__class__.__name__}"

    def _extract_requirements(self, source):
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.lower().startswith("# requires:"):
                try:
                    return shlex.split(stripped.split(":", 1)[1].strip())
                except Exception:
                    return [item for item in stripped.split(":", 1)[1].strip().split() if item]
        return []

    @staticmethod
    def _requirement_name(package):
        return re.split(r"[<>=!~\\[]", str(package or "").strip(), 1)[0].strip()

    def _is_requirement_installed(self, package):
        requirement_name = self._requirement_name(package)
        if not requirement_name:
            return True

        try:
            importlib.metadata.version(requirement_name)
            return True
        except importlib.metadata.PackageNotFoundError:
            return False
        except Exception:
            logger.debug("Failed to inspect distribution %s", requirement_name, exc_info=True)
            return False

    async def _install_packages(self, packages, reason=None):
        normalized = []
        seen = set()
        for package in packages:
            package = str(package or "").strip()
            if not package:
                continue
            key = package.lower()
            if key in self._pip_attempted or key in seen:
                continue
            seen.add(key)
            if self._is_requirement_installed(package):
                self._pip_attempted.add(key)
                continue
            normalized.append(package)

        if not normalized:
            return True

        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-warn-script-location",
            *normalized,
        ]
        reason_suffix = f" for {reason}" if reason else ""
        logger.info("Installing module dependencies%s: %s", reason_suffix, ", ".join(normalized))

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=600)
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            logger.error("Timed out while installing dependencies%s: %s", reason_suffix, ", ".join(normalized))
            return False

        if process.returncode != 0:
            tail = (stderr or stdout or b"").decode("utf-8", errors="ignore").strip()[-600:]
            logger.error(
                "Failed to install dependencies%s: %s%s",
                reason_suffix,
                ", ".join(normalized),
                f" | {tail}" if tail else "",
            )
            return False

        self._pip_attempted.update(package.lower() for package in normalized)
        logger.info("Dependencies installed%s: %s", reason_suffix, ", ".join(normalized))
        return True

    def _missing_dependency_candidates(self, missing_name, requirements):
        candidates = []
        missing_name = str(missing_name or "").strip()
        if missing_name:
            variants = [missing_name, missing_name.replace("_", "-")]
            for variant in variants:
                if variant and variant not in candidates:
                    candidates.append(variant)

        for package in requirements:
            package = str(package or "").strip()
            if not package:
                continue
            base = re.split(r"[<>=!~\[]", package, 1)[0].strip()
            normalized = base.lower().replace("-", "_")
            if missing_name and missing_name.lower().startswith(normalized):
                if package not in candidates:
                    candidates.insert(0, package)

        return candidates

    def _dispatch_command(self, command):
        if command in self.commands:
            return command, self.commands[command]
        return command, None

    def _lookup_module(self, name):
        if not name:
            return None

        needle = str(name).lower()
        for module in self.modules:
            candidates = {
                module.__class__.__name__.lower(),
                getattr(module, "name", "").lower(),
            }
            strings = getattr(module, "strings", {})
            if isinstance(strings, dict):
                candidates.add(strings.get("name", "").lower())
            if needle in candidates:
                return module

        return type("_MockLookup", (), {"fully_loaded": True, "commands": {}, "name": name})()

    def _bind_module_runtime(self, instance, filepath):
        if not isinstance(getattr(instance, "strings", None), dict):
            instance.strings = self._strings_dict({"name": getattr(instance, "name", instance.__class__.__name__)})
        else:
            instance.strings = self._strings_dict(instance.strings)

        storage = self._module_state.setdefault(self._storage_key(instance, filepath), self._StateDict(self))
        instance._db = storage

        def _get(*args):
            if len(args) == 1:
                return storage.get(args[0])
            if len(args) == 2:
                return storage.get(args[0], args[1])
            if len(args) >= 3:
                return storage.get(args[1], args[2])
            return None

        def _set(*args):
            if len(args) == 2:
                storage[args[0]] = args[1]
            elif len(args) >= 3:
                storage[args[1]] = args[2]

        instance.get = _get
        instance.set = _set
        instance.get_prefix = lambda: self.prefix
        instance.lookup = self._lookup_module

        instance.db = type(
            "MockDB",
            (),
            {
                "get": lambda s, *a: _get(*a),
                "set": lambda s, *a: _set(*a),
            },
        )()

        config = getattr(instance, "config", None)
        if hasattr(config, "bind_storage"):
            config_storage = storage.setdefault("__config__", self._StateDict(self))
            config.bind_storage(config_storage)

        if not hasattr(instance, "inline"):
            class _MockBot:
                id = 0

                async def send_document(self, *a, **kw):
                    return None

                async def send_message(self, *a, **kw):
                    return None

            class _MockInline:
                init_complete = False
                bot_username = "zenkai_inline_bot"
                bot_id = 0
                bot = _MockBot()

                def generate_markup(self, *a, **kw):
                    return []

                async def form(self, *a, **kw):
                    return False

                async def check_inline_security(self, *a, **kw):
                    return True

                def sanitise_text(self, text):
                    return text

            instance.inline = _MockInline()

        live_inline = self.inline or getattr(self.client, "inline_manager", None)
        if live_inline is not None:
            instance.inline = live_inline

        class _AllModulesProxy:
            @property
            def commands(self_inner):
                return self.commands

            @commands.setter
            def commands(self_inner, value):
                return None

            @property
            def modules(self_inner):
                return self.modules

            @modules.setter
            def modules(self_inner, value):
                return None

            @property
            def inline_handlers(self_inner):
                return self.inline_handlers

            @inline_handlers.setter
            def inline_handlers(self_inner, value):
                return None

            @property
            def callback_handlers(self_inner):
                return self.callback_handlers

            @callback_handlers.setter
            def callback_handlers(self_inner, value):
                return None

            async def check_security(self_inner, message, func):
                return True

            def dispatch(self_inner, command):
                return self._dispatch_command(command)

            def lookup(self_inner, name):
                return self._lookup_module(name)

        instance.allmodules = _AllModulesProxy()
                
    async def load_all(self, modules_dir="modules"):
        """Loads all Python files inside the modules directory."""
        if not os.path.exists(modules_dir):
            os.makedirs(modules_dir)
            
        for filename in sorted(os.listdir(modules_dir)):
            if filename.endswith(".py") and not filename.startswith("__"):
                await self.load_module(filename[:-3], os.path.join(modules_dir, filename))
        
        if not self._handler_registered:
            self._register_handlers()
            self._handler_registered = True
            
        logger.info(f"Loaded {len(self.modules)} modules with {len(self.commands)} commands.")

    def _make_heroku_shims(self):
        """Create fake 'loader' and 'utils' modules that Heroku plugins expect."""

        # Build the shim loader module
        shim = types.ModuleType("loader")
            
        class ShimModule:
            strings = Loader._strings_dict({"name": "Unknown"})
            def __init__(self):
                self.strings = Loader._strings_dict(getattr(self.__class__, 'strings', {"name": "Unknown"}))
                self._client = None
                self._db = {}
                self.db = type("MockDB", (), {"get": lambda *a: self.get(*a), "set": lambda *a: self.set(*a)})()
                self.tg_id = None
                self.commands = {}
                self.inline_handlers = {}
                self.callback_handlers = {}
                
                class MockBot:
                    id = 0
                    async def send_document(self, *a, **kw): pass
                    async def send_message(self, *a, **kw): pass
                class MockInline:
                    init_complete = False
                    bot_username = "zenkai_inline_bot"
                    bot_id = 0
                    bot = MockBot()
                    def generate_markup(self, *a, **kw): return []
                    async def form(self, *a, **kw): return False
                    async def check_inline_security(self, *a, **kw): return True
                self.inline = MockInline()
                
                class MockAllModules:
                    commands = {}
                    modules = []
                    async def check_security(self, message, func): return True
                    def dispatch(self, command):
                        if command in self.commands:
                            return (command, self.commands[command])
                        return (command, None)
                self.allmodules = MockAllModules()
                
            def lookup(self, name):
                for m in self.allmodules.modules:
                    # Check class name
                    if m.__class__.__name__.lower() == name.lower():
                        return m
                    # Check .name attribute
                    if getattr(m, "name", "").lower() == name.lower():
                        return m
                    # Check strings dict name
                    strings = getattr(m, "strings", {})
                    if isinstance(strings, dict) and strings.get("name", "").lower() == name.lower():
                        return m
                # Return a mock for unknown lookups (prevents AttributeError on .fully_loaded etc.)
                return type("_MockLookup", (), {"fully_loaded": True, "commands": {}, "name": name})()
                
            def config(self): pass
            def get(self, *args):
                if len(args) == 1:
                    return self._db.get(args[0])
                if len(args) == 2:
                    return self._db.get(args[0], args[1])
                return self._db.get(args[1], args[2]) if args else None
            def set(self, *args):
                if len(args) == 2:
                    self._db[args[0]] = args[1]
                elif len(args) == 3:
                    self._db[args[1]] = args[2]
            def get_prefix(self):
                return "."
        
        shim.Module = ShimModule
        shim.Library = type("Library", (), {})
        
        class SelfUnload(Exception):
            """Raised when a module should unload itself."""
            pass
        shim.SelfUnload = SelfUnload
        
        class SelfSuspend(Exception):
            """Raised when a module should suspend itself."""
            pass
        shim.SelfSuspend = SelfSuspend
        
        def shim_command(**kwargs):
            def decorator(func):
                func.is_command = True
                raw = func.__name__
                # Strip trailing "cmd" as Heroku convention
                name = kwargs.get("name", raw)
                if name == raw and raw.endswith("cmd"):
                    name = raw[:-3]
                if name == raw and raw.endswith("_cmd"):
                    name = raw[:-4]
                name = name.strip("_") or raw
                func.command_name = name
                func.command_aliases = kwargs.get("aliases", [])
                doc = kwargs.get("ru_doc") or kwargs.get("en_doc") or func.__doc__ or ""
                func.description = doc
                return func
            return decorator
        
        shim.command = shim_command

        def callback_handler(*args, **kwargs):
            def decorator(func):
                func.is_callback_handler = True
                func.callback_handler_name = kwargs.get("name") or func.__name__
                return func
            return decorator
        shim.callback_handler = callback_handler

        def inline_handler(*args, **kwargs):
            def decorator(func):
                func.is_inline_handler = True
                raw = func.__name__
                name = kwargs.get("name", raw)
                if name == raw and raw.endswith("_inline_handler"):
                    name = raw[:-15]
                name = name.strip("_") or raw
                func.inline_handler_name = name
                return func
            return decorator
        shim.inline_handler = inline_handler

        def watcher(*args, **kwargs):
            def decorator(func):
                func.is_watcher = True
                return func
            return decorator
        shim.watcher = watcher
        
        def tds(cls): return cls
        shim.tds = tds
        
        class ConfigValue:
            def __init__(self, name=None, default=None, doc=None, validator=None, on_change=None, *a, **kw):
                self.option = name or (a[0] if a else "unknown")
                self.default = default
                self.doc = doc
                self.validator = validator
                self.on_change = on_change
                self.value = default
        shim.ConfigValue = ConfigValue

        class ModuleConfig(dict):
            def __init__(self, *args, **kw):
                super().__init__()
                self._config = {}
                self._storage = None
                i = 0
                while i < len(args):
                    if isinstance(args[i], ConfigValue):
                        config_value = args[i]
                        self._config[config_value.option] = config_value
                        super().__setitem__(config_value.option, config_value.default)
                        i += 1
                    elif isinstance(args[i], str):
                        key = args[i]
                        val = args[i + 1] if i + 1 < len(args) else None
                        doc = args[i + 2] if i + 2 < len(args) else None
                        config_value = ConfigValue(key, val, doc)
                        self._config[key] = config_value
                        super().__setitem__(key, val)
                        i += 3 if i + 2 < len(args) and isinstance(args[i + 2], (str, type(lambda: 0))) else 2
                    else:
                        i += 1

            def bind_storage(self, storage):
                self._storage = storage
                for option, value in storage.items():
                    if option in self._config:
                        self._set_value(option, value, run_hook=False, persist=False)

            def getdoc(self, option):
                doc = self._config[option].doc
                return doc() if callable(doc) else (doc or "")

            def getdef(self, option):
                return self._config[option].default

            def _set_value(self, option, value, run_hook=True, persist=True):
                if option not in self._config:
                    raise KeyError(option)

                config_value = self._config[option]
                validator = getattr(config_value, "validator", None)
                if validator is not None and hasattr(validator, "validate"):
                    value = validator.validate(value)

                super().__setitem__(option, value)
                config_value.value = value

                if persist and self._storage is not None:
                    self._storage[option] = value

                if run_hook and config_value.on_change:
                    try:
                        result = config_value.on_change()
                        if inspect.isawaitable(result):
                            try:
                                loop = asyncio.get_running_loop()
                                loop.create_task(result)
                            except Exception:
                                pass
                    except Exception:
                        logger.debug("Config on_change hook failed", exc_info=True)

                return value

            def __setitem__(self, option, value):
                return self._set_value(option, value)
        shim.ModuleConfig = ModuleConfig

        class validators:
            class ValidationError(ValueError):
                pass

            class _BaseValidator:
                internal_id = "Base"

                def validate(self, value):
                    return value

            class Boolean(_BaseValidator):
                internal_id = "Boolean"

                def validate(self, value):
                    if isinstance(value, bool):
                        return value
                    if isinstance(value, str):
                        normalized = value.strip().lower()
                        if normalized in {"1", "true", "yes", "on", "да", "y"}:
                            return True
                        if normalized in {"0", "false", "no", "off", "нет", "n"}:
                            return False
                    raise validators.ValidationError("Expected boolean value")

            class String(_BaseValidator):
                internal_id = "String"

                def validate(self, value):
                    return "" if value is None else str(value)

            class Integer(_BaseValidator):
                internal_id = "Integer"

                def __init__(self, minimum=None, maximum=None, *a, **kw):
                    self.minimum = minimum
                    self.maximum = maximum

                def validate(self, value):
                    try:
                        parsed = int(value)
                    except Exception as e:
                        raise validators.ValidationError("Expected integer value") from e
                    if self.minimum is not None and parsed < self.minimum:
                        raise validators.ValidationError(f"Minimum value is {self.minimum}")
                    if self.maximum is not None and parsed > self.maximum:
                        raise validators.ValidationError(f"Maximum value is {self.maximum}")
                    return parsed

            class Float(_BaseValidator):
                internal_id = "Float"

                def __init__(self, minimum=None, maximum=None, *a, **kw):
                    self.minimum = minimum
                    self.maximum = maximum

                def validate(self, value):
                    try:
                        parsed = float(value)
                    except Exception as e:
                        raise validators.ValidationError("Expected float value") from e
                    if self.minimum is not None and parsed < self.minimum:
                        raise validators.ValidationError(f"Minimum value is {self.minimum}")
                    if self.maximum is not None and parsed > self.maximum:
                        raise validators.ValidationError(f"Maximum value is {self.maximum}")
                    return parsed

            class Choice(_BaseValidator):
                internal_id = "Choice"

                def __init__(self, values=None, *a, **kw):
                    self.values = list(values or [])

                def validate(self, value):
                    if value not in self.values:
                        raise validators.ValidationError(f"Expected one of: {', '.join(map(str, self.values))}")
                    return value

            class MultiChoice(_BaseValidator):
                internal_id = "MultiChoice"

                def __init__(self, values=None, *a, **kw):
                    self.values = list(values or [])

                def validate(self, value):
                    if isinstance(value, str):
                        stripped = value.strip()
                        if stripped.startswith("["):
                            try:
                                value = ast.literal_eval(stripped)
                            except Exception:
                                value = [item.strip() for item in stripped.split(",") if item.strip()]
                        else:
                            value = [item.strip() for item in stripped.split(",") if item.strip()]
                    if not isinstance(value, (list, tuple)):
                        raise validators.ValidationError("Expected multiple values")
                    value = list(value)
                    bad = [item for item in value if self.values and item not in self.values]
                    if bad:
                        raise validators.ValidationError(f"Unsupported values: {', '.join(map(str, bad))}")
                    return value

            class Series(_BaseValidator):
                internal_id = "Series"

                def __init__(self, validator=None, fixed_len=None, *a, **kw):
                    self.validator = validator
                    self.fixed_len = fixed_len

                def validate(self, value):
                    if isinstance(value, str):
                        stripped = value.strip()
                        try:
                            parsed = ast.literal_eval(stripped)
                            value = parsed if isinstance(parsed, (list, tuple)) else [parsed]
                        except Exception:
                            value = [item.strip() for item in stripped.split(",")]
                    if not isinstance(value, (list, tuple)):
                        raise validators.ValidationError("Expected list value")
                    value = list(value)
                    if self.fixed_len is not None and len(value) != self.fixed_len:
                        raise validators.ValidationError(f"Expected {self.fixed_len} values")
                    if self.validator and hasattr(self.validator, "validate"):
                        value = [self.validator.validate(item) for item in value]
                    return value

            class RandomLink(_BaseValidator):
                internal_id = "RandomLink"

            class Hidden(_BaseValidator):
                internal_id = "Hidden"

                def __init__(self, validator=None, *a, **kw):
                    self.validator = validator

                def validate(self, value):
                    if self.validator and hasattr(self.validator, "validate"):
                        return self.validator.validate(value)
                    return value

            class Link(_BaseValidator):
                internal_id = "Link"

            class RegExp(_BaseValidator):
                internal_id = "RegExp"

                def __init__(self, pattern, *a, **kw):
                    self.pattern = re.compile(pattern)

                def validate(self, value):
                    value = str(value)
                    if not self.pattern.match(value):
                        raise validators.ValidationError("Value does not match expected format")
                    return value
        shim.validators = validators
        def loop_decorator(*args, **kwargs):
            def decorator(func):
                return func
            return decorator
        shim.loop = loop_decorator
        
        # Build the shim utils module
        utils_mod = types.ModuleType("utils")
        
        async def answer(message, text, **kwargs):
            """Heroku-style utils.answer — edits if outgoing, replies otherwise."""
            reply_markup = kwargs.pop("reply_markup", None)
            if reply_markup:
                client = getattr(message, "client", None) or getattr(message, "_client", None)
                loader = getattr(client, "loader", None)
                inline = getattr(loader, "inline", None) or getattr(client, "inline_manager", None)
                if inline and getattr(inline, "init_complete", False):
                    try:
                        return await inline.form(
                            text,
                            message=message,
                            reply_markup=inline._normalize_markup(reply_markup),
                            silent=bool(kwargs.pop("silent", False)),
                        )
                    except Exception:
                        logger.debug("Failed to answer via inline form", exc_info=True)

            try:
                return await message.edit(text, parse_mode="html", **kwargs)
            except Exception:
                return await message.respond(text, parse_mode="html", **kwargs)
        
        def get_args_raw(message):
            """Extract raw args from a message."""
            text = getattr(message, "raw_text", getattr(message, "text", "")) or ""
            parts = text.split(maxsplit=1)
            return parts[1] if len(parts) > 1 else ""
            
        def get_args(message):
            return get_args_raw(message).split()

        def get_chat_id(message):
            for attr in ("chat_id", "peer_id"):
                value = getattr(message, attr, None)
                if isinstance(value, int):
                    return value
            if hasattr(message, "chat") and getattr(message.chat, "id", None) is not None:
                return message.chat.id
            if hasattr(message, "to_id"):
                to_id = getattr(message, "to_id")
                for field in ("channel_id", "chat_id", "user_id"):
                    value = getattr(to_id, field, None)
                    if value is not None:
                        return value
            return getattr(message, "sender_id", 0)
        
        def escape_html(text):
            import html
            return html.escape(str(text))
            
        def remove_html(text):
            import re
            return re.sub(r'<[^>]*>', '', str(text))
            
        def chunks(lst, n):
            return [lst[i:i + n] for i in range(0, len(lst), n)]
            
        def config_placeholders(): return ""
        def help_placeholders(*a): return []
        def formatted_uptime(): 
            import time, psutil
            try: return time.strftime("%H:%M:%S", time.gmtime(time.time() - psutil.boot_time()))
            except: return "00:00:00"
        def get_cpu_usage(): 
            import psutil
            return f"{psutil.cpu_percent()}%"
        def get_ram_usage(): 
            import psutil
            try: return str(round(psutil.virtual_memory().used / 1024 / 1024))
            except: return "0"
        def is_up_to_date(): return True
        def get_commit_url(): return ""
        def get_named_platform(): return "Zenkai"
        def get_named_platform_emoji(): return "✨"
        def get_platform_emoji(): return "✨"
        def get_platform_name(): return "Zenkai"
        def get_git_status(): return ""
        def get_git_hash(): return ""
        def check_url(url): return str(url).startswith("http")
        def get_base_dir():
            import os
            return os.getcwd()
        async def run_sync(func, *args, **kwargs):
            return await asyncio.to_thread(func, *args, **kwargs)
        async def get_placeholders(d, msg): return d
        
        utils_mod.answer = answer
        utils_mod.get_args_raw = get_args_raw
        utils_mod.get_args = get_args
        utils_mod.get_chat_id = get_chat_id
        utils_mod.escape_html = escape_html
        utils_mod.remove_html = remove_html
        utils_mod.chunks = chunks
        utils_mod.config_placeholders = config_placeholders
        utils_mod.help_placeholders = help_placeholders
        utils_mod.formatted_uptime = formatted_uptime
        utils_mod.get_cpu_usage = get_cpu_usage
        utils_mod.get_ram_usage = get_ram_usage
        utils_mod.is_up_to_date = is_up_to_date
        utils_mod.get_commit_url = get_commit_url
        utils_mod.get_named_platform = get_named_platform
        utils_mod.get_named_platform_emoji = get_named_platform_emoji
        utils_mod.get_platform_emoji = get_platform_emoji
        utils_mod.get_platform_name = get_platform_name
        utils_mod.get_git_status = get_git_status
        utils_mod.get_git_hash = get_git_hash
        utils_mod.check_url = check_url
        utils_mod.get_base_dir = get_base_dir
        utils_mod.run_sync = run_sync
        async def wait_for_content_channel(db):
            """Mock wait_for_content_channel — returns 0 (no content channel)."""
            return 0
        
        utils_mod.get_placeholders = get_placeholders
        utils_mod.wait_for_content_channel = wait_for_content_channel
        
        return shim, utils_mod
    
    async def load_module(self, module_name, filepath):
        """Dynamically imports a single module file and initializes its Module classes."""
        try:
            try:
                with open(filepath, "r", encoding="utf-8") as source_handle:
                    module_source = source_handle.read()
            except Exception:
                module_source = ""

            requirements = self._extract_requirements(module_source)
            if requirements:
                await self._install_packages(requirements, reason=f"module {module_name}")

            shim_loader, shim_utils = self._make_heroku_shims()
            
            # Create a fake 2-level deep package so `from .. import loader, utils` works
            # Module will be at: zenkai_pkg.heroku_modules.<module_name>
            # `from ..` resolves to: zenkai_pkg  (which has .loader and .utils)
            root_pkg = "zenkai_pkg"
            sub_pkg = f"{root_pkg}.heroku_modules"
            mod_fqn = f"{sub_pkg}.{module_name}"
            
            # Root package (contains loader, utils)
            if root_pkg not in sys.modules:
                root = types.ModuleType(root_pkg)
                root.__path__ = []
                root.__package__ = root_pkg
                root.loader = shim_loader
                root.utils = shim_utils
                
                # mock main
                main_mod = types.ModuleType(f"{root_pkg}.main")
                main_mod.__version__ = (1, 0, 0)
                main_mod.get_config_key = lambda k: None
                root.main = main_mod
                sys.modules[f"{root_pkg}.main"] = main_mod
                
                # mock version
                version_mod = types.ModuleType(f"{root_pkg}.version")
                version_mod.__version__ = (1, 0, 0)
                version_mod.branch = "master"
                version_mod.__full_version__ = "1.0.0"
                root.version = version_mod
                sys.modules[f"{root_pkg}.version"] = version_mod
                
                # mock log
                log_mod = types.ModuleType(f"{root_pkg}.log")
                class MockException:
                    @staticmethod
                    def from_exc_info(*a): return "Error"
                log_mod.Exception = MockException
                root.log = log_mod
                sys.modules[f"{root_pkg}.log"] = log_mod
                
                # mock inline
                inline_mod = types.ModuleType(f"{root_pkg}.inline")
                inline_mod.types = types.ModuleType(f"{root_pkg}.inline.types")
                try:
                    from inline.types import InlineCall, InlineMessage, InlineQuery
                except Exception:
                    class InlineCall: pass
                    class InlineMessage: pass
                    class InlineQuery: pass
                inline_mod.types.InlineCall = InlineCall
                inline_mod.types.InlineQuery = InlineQuery
                inline_mod.types.InlineMessage = InlineMessage
                root.inline = inline_mod
                sys.modules[f"{root_pkg}.inline"] = inline_mod
                sys.modules[f"{root_pkg}.inline.types"] = inline_mod.types

                sys.modules[root_pkg] = root
            else:
                root = sys.modules[root_pkg]
                root.loader = shim_loader
                root.utils = shim_utils
                try:
                    from inline.types import InlineCall, InlineMessage, InlineQuery
                    root.inline.types.InlineCall = InlineCall
                    root.inline.types.InlineQuery = InlineQuery
                    root.inline.types.InlineMessage = InlineMessage
                except Exception:
                    pass
            
            # Sub-package (where modules "live")
            if sub_pkg not in sys.modules:
                sub = types.ModuleType(sub_pkg)
                sub.__path__ = []
                sub.__package__ = sub_pkg
                sys.modules[sub_pkg] = sub
            
            # Register shim modules for direct import too
            sys.modules[f'{root_pkg}.loader'] = shim_loader
            sys.modules[f'{root_pkg}.utils'] = shim_utils
            
            def _build_module():
                spec = importlib.util.spec_from_file_location(
                    mod_fqn, filepath,
                    submodule_search_locations=[]
                )
                if not spec or not spec.loader:
                    logger.error(f"Could not create spec for {filepath}")
                    return None, None

                mod = importlib.util.module_from_spec(spec)
                mod.__package__ = sub_pkg  # `from ..` goes: sub_pkg -> root_pkg ✓
                sys.modules[mod_fqn] = mod
                return spec, mod

            spec, mod = _build_module()
            if not spec or not mod:
                return

            try:
                spec.loader.exec_module(mod)
            except ModuleNotFoundError as missing_error:
                missing_name = getattr(missing_error, "name", "")
                missing_packages = self._missing_dependency_candidates(missing_name, requirements)
                installed = await self._install_packages(
                    missing_packages,
                    reason=f"missing dependency for module {module_name}",
                )
                if not installed:
                    raise

                sys.modules.pop(mod_fqn, None)
                spec, mod = _build_module()
                if not spec or not mod:
                    return
                spec.loader.exec_module(mod)
            
            ShimModule = shim_loader.Module
            
            for name, obj in inspect.getmembers(mod):
                if not inspect.isclass(obj):
                    continue
                    
                is_zenkai_module = False
                is_heroku_module = False
                try:
                    is_zenkai_module = issubclass(obj, Module) and obj is not Module
                except TypeError:
                    pass
                try:
                    is_heroku_module = issubclass(obj, ShimModule) and obj is not ShimModule
                except TypeError:
                    pass
                
                if not (is_zenkai_module or is_heroku_module):
                    continue
                
                try:
                    instance = obj()
                except Exception as e:
                    logger.warning(f"Failed to instantiate {name}: {e}")
                    continue

                self._bind_module_runtime(instance, filepath)

                if not hasattr(instance, 'tg_id'):
                    instance.tg_id = None
                instance.client = self.client
                instance._client = self.client
                
                # Set tg_id for Heroku modules (Saved Messages)
                try:
                    if self.client.is_connected():
                        me = await self.client.get_me()
                        if me:
                            instance.tg_id = me.id
                except Exception:
                    pass
                
                # Call lifecycle hooks
                if hasattr(instance, 'client_ready'):
                    try:
                        sig = inspect.signature(instance.client_ready)
                        param_count = len(sig.parameters)
                        if param_count >= 2:
                            await instance.client_ready(self.client, instance.db)
                        elif param_count == 1:
                            await instance.client_ready(self.client)
                        else:
                            await instance.client_ready()
                    except Exception as e:
                        logger.warning(f"client_ready failed for {name}: {e}")
                
                if hasattr(instance, 'on_load'):
                    try:
                        await instance.on_load()
                    except Exception as e:
                        logger.warning(f"on_load failed for {name}: {e}")
                
                # Resolve module display name
                mod_name = getattr(instance, 'name', None)
                if not mod_name or mod_name == "Unnamed" or mod_name == "Unknown":
                    if hasattr(instance, 'strings') and isinstance(instance.strings, dict):
                        mod_name = instance.strings.get("name", name)
                    else:
                        mod_name = name
                        
                instance.name = mod_name
                instance.description = getattr(instance, 'description', None) or instance.__doc__ or ''
                instance.__origin__ = "<core.heroku.modules>"
                
                # Read source for meta detection
                instance.__source__ = module_source
                
                # Ensure commands-related dicts exist
                if not hasattr(instance, 'commands'):
                    instance.commands = {}
                if not hasattr(instance, 'inline_handlers'):
                    instance.inline_handlers = {}
                if not hasattr(instance, 'callback_handlers'):
                    instance.callback_handlers = {}
                
                # Remove old version of this module if reloading
                self.modules = [m for m in self.modules if m.name != instance.name]
                # Remove old commands from this module
                old_cmds = [k for k, v in self.commands.items() 
                            if getattr(v, '__self__', None) and 
                            getattr(getattr(v, '__self__', None), 'name', None) == instance.name]
                for k in old_cmds:
                    del self.commands[k]
                old_inline = [k for k, v in self.inline_handlers.items()
                              if getattr(v, '__self__', None) and
                              getattr(getattr(v, '__self__', None), 'name', None) == instance.name]
                for k in old_inline:
                    del self.inline_handlers[k]
                old_callbacks = [k for k, v in self.callback_handlers.items()
                                 if getattr(v, '__self__', None) and
                                 getattr(getattr(v, '__self__', None), 'name', None) == instance.name]
                for k in old_callbacks:
                    del self.callback_handlers[k]
                
                self.modules.append(instance)
                
                # Extract commands (support both decorators)
                instance.commands = {}
                instance.inline_handlers = {}
                instance.callback_handlers = {}
                for method_name, method in inspect.getmembers(instance, predicate=callable):
                    is_command = getattr(method, 'is_command', False)
                    # Support legacy heroku-style command detection (methods ending in 'cmd')
                    if not is_command and method_name.endswith('cmd') and getattr(instance, '__origin__', '') == "<core.heroku.modules>":
                        is_command = True
                        method.is_command = True
                        cmd_name = method_name[:-3].strip('_')
                        method.command_name = cmd_name
                        method.command_aliases = []
                        method.command_description = method.__doc__ or "No description."

                    if is_command:
                        cmd_name = getattr(method, 'command_name', method_name)
                        instance.commands[cmd_name] = method
                        self.commands[cmd_name] = method
                        for alias in getattr(method, 'command_aliases', []):
                            instance.commands[alias] = method
                            self.commands[alias] = method
                    if getattr(method, 'is_inline_handler', False) or method_name.endswith("_inline_handler"):
                        inline_name = getattr(method, "inline_handler_name", None)
                        if not inline_name:
                            inline_name = method_name[:-15] if method_name.endswith("_inline_handler") else method_name
                        inline_name = inline_name.strip("_").lower()
                        if inline_name:
                            instance.inline_handlers[inline_name] = method
                            self.inline_handlers[inline_name] = method
                    if getattr(method, 'is_callback_handler', False):
                        callback_name = getattr(method, "callback_handler_name", method_name)
                        instance.callback_handlers[callback_name] = method
                        self.callback_handlers[callback_name] = method
                
                # Mock allmodules populating
                for m in self.modules:
                    if hasattr(m, "allmodules"):
                        m.allmodules.modules = self.modules
                        m.allmodules.commands = self.commands
                            
                logger.debug(f"Loaded module: {instance.name}")
                    
        except Exception as e:
            logger.error(f"Failed to load module {module_name} from {filepath}: {e}")

    def _register_handlers(self):
        """Registers a global Telethon event handler for command routing."""
        @self.client.on(events.NewMessage(outgoing=True, pattern=fr"^{re.escape(self.prefix)}(?P<cmd>[^\s]+)(?:\s+(?P<args>.*))?"))
        async def command_handler(event):
            cmd = event.pattern_match.group("cmd")
            if cmd in self.commands:
                try:
                    await self.commands[cmd](event)
                except Exception as e:
                    logger.error(f"Error executing command {cmd}: {e}")
                    await event.edit(f"❌ Error: {e}")
