import difflib
import html
import inspect
import re

from core.module import Module, command


class HelpModule(Module):
    name = "Help"
    description = "Shows loaded modules and commands."

    CORE_MODULES = {
        "APIGuard",
        "Config",
        "Eval",
        "Help",
        "Info",
        "LoaderCommands",
        "Updater",
        "WebAuth",
    }

    def _loader(self):
        return getattr(self.client, "loader", None)

    def _prefix(self):
        loader = self._loader()
        return html.escape(getattr(loader, "prefix", ".") if loader else ".")

    def _hidden_key(self):
        return "_zenkai_help_hidden"

    def _get_hidden(self):
        loader = self._loader()
        if not loader:
            return set()
        hidden = loader._module_state.setdefault(self._hidden_key(), {"items": []})
        return set(hidden.get("items", []))

    def _set_hidden(self, names):
        loader = self._loader()
        if loader:
            loader._module_state[self._hidden_key()] = {"items": sorted(set(names))}

    def _module_name(self, module):
        strings = getattr(module, "strings", {})
        if isinstance(strings, dict) and strings.get("name"):
            return str(strings["name"])
        return str(getattr(module, "name", None) or module.__class__.__name__)

    def _module_key(self, module):
        return module.__class__.__name__

    def _is_core(self, module):
        return self._module_name(module) in self.CORE_MODULES or self._module_key(module) in self.CORE_MODULES

    def _command_doc(self, func):
        return (
            getattr(func, "command_description", None)
            or getattr(func, "description", None)
            or inspect.getdoc(func)
            or "Нет описания"
        )

    def _primary_commands(self, module):
        seen = set()
        result = []
        commands = getattr(module, "commands", {}) or {}
        for registered_name, func in commands.items():
            primary = getattr(func, "command_name", registered_name)
            if registered_name != primary and primary in commands:
                continue
            key = id(func)
            if key in seen:
                continue
            seen.add(key)
            result.append((primary, func))
        return sorted(result, key=lambda item: item[0].lower())

    def _aliases_for(self, module, command_name, func):
        aliases = set(getattr(func, "command_aliases", []) or [])
        for registered_name, registered_func in (getattr(module, "commands", {}) or {}).items():
            if registered_func is func and registered_name != command_name:
                aliases.add(registered_name)
        return sorted(aliases)

    def _all_modules(self):
        loader = self._loader()
        return list(getattr(loader, "modules", []) or []) if loader else []

    def _find_module(self, query):
        query = (query or "").strip()
        if not query:
            return None, True

        loader = self._loader()
        if not loader:
            return None, True

        needle = query.lower().lstrip(getattr(loader, "prefix", "."))
        for module in self._all_modules():
            candidates = {
                self._module_key(module).lower(),
                self._module_name(module).lower(),
                getattr(module, "name", "").lower(),
            }
            if needle in candidates:
                return module, True

        if needle in loader.commands:
            return getattr(loader.commands[needle], "__self__", None), True

        names = [self._module_name(module) for module in self._all_modules()]
        closest = difflib.get_close_matches(needle, [name.lower() for name in names], n=1, cutoff=0.35)
        if closest:
            for module in self._all_modules():
                if self._module_name(module).lower() == closest[0]:
                    return module, False

        return None, True

    def _developer(self, module):
        source = getattr(module, "__source__", "") or ""
        match = re.search(r"# ?meta developer: ?(.+)", source)
        return html.escape(match.group(1).strip()) if match else None

    async def _module_help(self, event, query):
        module, exact = self._find_module(query)
        if not module:
            return await event.edit("🚫 <b>Модуль или команда не найдены.</b>", parse_mode="html")

        prefix = self._prefix()
        module_name = html.escape(self._module_name(module))
        version = getattr(module, "__version__", None)
        if version:
            module_name = f"{module_name} (v{html.escape('.'.join(map(str, version)))})"

        doc = html.escape(inspect.getdoc(module) or getattr(module, "description", "") or "Нет описания")
        lines = []
        for cmd_name, func in self._primary_commands(module):
            aliases = self._aliases_for(module, cmd_name, func)
            alias_text = ""
            if aliases:
                alias_text = " (" + ", ".join(f"<code>{prefix}{html.escape(alias)}</code>" for alias in aliases) + ")"
            lines.append(
                "▫️ <code>{}{}</code>{} {}".format(
                    prefix,
                    html.escape(cmd_name),
                    alias_text,
                    html.escape(self._command_doc(func)),
                )
            )

        inline_handlers = getattr(module, "inline_handlers", {}) or {}
        for name, func in inline_handlers.items():
            lines.append(
                "🤖 <code>@zenkai_inline_bot {}</code> {}".format(
                    html.escape(str(name)),
                    html.escape(inspect.getdoc(func) or "Нет описания"),
                )
            )

        if not lines:
            lines.append("🟠 <i>У модуля нет команд.</i>")

        extra = []
        developer = self._developer(module)
        if developer:
            extra.append(f"🫶 Разработчик: {developer}")
        if not exact:
            extra.append("☝️ <b>Точного совпадения не нашлось, показан ближайший модуль.</b>")
        if self._is_core(module):
            extra.append("☝️ <b>Это встроенный модуль Zenkai.</b>")

        text = (
            f"🪐 <b>{module_name}</b>:\n"
            f"<i>ℹ️ {doc}</i>\n"
            f"<blockquote expandable>{chr(10).join(lines)}</blockquote>"
        )
        if extra:
            text += "\n" + "\n".join(extra)

        await event.edit(text, parse_mode="html")

    @command(name="helphide", description="Hide or show modules in .help.")
    async def helphide_cmd(self, event):
        if not self._loader():
            return await event.edit("🚫 <b>Loader не инициализирован.</b>", parse_mode="html")

        args = (getattr(event, "raw_text", "") or "").split(maxsplit=1)
        modules = args[1].split() if len(args) > 1 else []
        if not modules:
            return await event.edit("🚫 <b>Укажи модуль(-и), которые нужно скрыть.</b>", parse_mode="html")

        currently_hidden = self._get_hidden()
        hidden = []
        shown = []

        for raw_name in modules:
            module, _ = self._find_module(raw_name)
            if not module:
                continue

            key = self._module_key(module)
            if key in currently_hidden:
                currently_hidden.remove(key)
                shown.append(self._module_name(module))
            else:
                currently_hidden.add(key)
                hidden.append(self._module_name(module))

        self._set_hidden(currently_hidden)

        if not hidden and not shown:
            return await event.edit("🚫 <b>Модули не найдены.</b>", parse_mode="html")

        hidden_text = "\n".join(f"👁‍🗨 <i>{html.escape(name)}</i>" for name in hidden)
        shown_text = "\n".join(f"👁 <i>{html.escape(name)}</i>" for name in shown)
        await event.edit(
            f"<b>{len(hidden)} модулей скрыто, {len(shown)} модулей показано:</b>\n{hidden_text}\n{shown_text}",
            parse_mode="html",
        )

    @command(name="help", description="Show help for modules and commands.")
    async def help_cmd(self, event):
        loader = self._loader()
        if not loader:
            return await event.edit("🚫 <b>Loader не инициализирован.</b>", parse_mode="html")

        raw_args = (getattr(event, "raw_text", "") or "").split(maxsplit=1)
        args = raw_args[1].strip() if len(raw_args) > 1 else ""
        flags = {item for item in args.split() if item.startswith("-")}
        query = " ".join(item for item in args.split() if not item.startswith("-")).strip()

        force = "-f" in flags
        only_core = "-c" in flags
        only_loaded = "-l" in flags
        if only_core or only_loaded:
            force = True

        if query:
            return await self._module_help(event, query)

        hidden = self._get_hidden()
        modules = self._all_modules()
        hidden_count = 0 if force else sum(self._module_key(module) in hidden for module in modules)
        header = f"<b>{len(modules)} модулей доступно, {hidden_count} скрыто:</b>"

        core_rows = []
        plain_rows = []
        empty_rows = []

        for module in sorted(modules, key=lambda item: self._module_name(item).lower()):
            if self._module_key(module) in hidden and not force:
                continue

            commands = [name for name, _ in self._primary_commands(module)]
            inline_handlers = list((getattr(module, "inline_handlers", {}) or {}).keys())
            module_name = html.escape(self._module_name(module))

            if not commands and not inline_handlers:
                empty_rows.append(f"\n🟠 <code>{module_name}</code>")
                continue

            command_text = " | ".join(html.escape(name) for name in commands)
            inline_text = " | ".join(f"🤖 {html.escape(str(name))}" for name in inline_handlers)
            joined = " | ".join(part for part in (command_text, inline_text) if part)
            row = f"\n{'▪️' if self._is_core(module) else '▫️'} <code>{module_name}</code>: ( {joined} )"

            if self._is_core(module):
                core_rows.append(row)
            else:
                plain_rows.append(row)

        visible_empty = empty_rows if force else []
        blocks = []
        if not only_loaded:
            blocks.append("".join(core_rows))
        if not only_core:
            blocks.append("".join(plain_rows + visible_empty))

        text = "🪐 " + header
        for block in blocks:
            if block:
                text += f"\n<blockquote expandable>{block}</blockquote>"

        await event.edit(text, parse_mode="html")

    @command(name="support", description="Show support contact info.")
    async def support_cmd(self, event):
        await event.edit(
            "❔ <b>Zenkai Support</b>\n\n"
            "Если модуль падает, скинь название модуля, команду и полный текст ошибки.",
            parse_mode="html",
        )
