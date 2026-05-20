from core.module import Module, command


class HelpModule(Module):
    name = "Help"
    description = "Shows loaded modules and their commands."

    def _loader(self):
        return getattr(self.client, "loader", None)

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
        if not loader:
            return
        loader._module_state[self._hidden_key()] = {"items": sorted(set(names))}

    def _iter_commands(self, module):
        return sorted(
            {
                name
                for name, handler in self._loader().commands.items()
                if getattr(handler, "__self__", None) is module
            }
        )

    def _find_module(self, query):
        loader = self._loader()
        if not loader:
            return None

        needle = query.strip().lower()
        for module in loader.modules:
            candidates = {
                module.__class__.__name__.lower(),
                getattr(module, "name", "").lower(),
            }
            if needle in candidates:
                return module
        return None

    @command(name="helphide", description="Hide or unhide modules in the help list.")
    async def helphide_cmd(self, event):
        loader = self._loader()
        if not loader:
            return await event.edit("❌ Loader is not initialized.")

        args = event.raw_text.split(maxsplit=1)
        if len(args) < 2 or not args[1].strip():
            return await event.edit("❌ Укажи модули через пробел: `.helphide Help Ping`")

        hidden = self._get_hidden()
        toggled_hidden = []
        toggled_shown = []

        for raw_name in args[1].split():
            module = self._find_module(raw_name)
            if not module:
                continue

            module_name = module.name
            if module_name in hidden:
                hidden.remove(module_name)
                toggled_shown.append(module_name)
            else:
                hidden.add(module_name)
                toggled_hidden.append(module_name)

        self._set_hidden(hidden)

        lines = []
        if toggled_hidden:
            lines.append("🙈 Скрыты: " + ", ".join(f"`{name}`" for name in sorted(toggled_hidden)))
        if toggled_shown:
            lines.append("👁 Показаны: " + ", ".join(f"`{name}`" for name in sorted(toggled_shown)))
        if not lines:
            lines.append("❌ Совпадений по модулям не найдено.")

        await event.edit("\n".join(lines))

    @command(name="help", description="Show help for modules and commands.")
    async def help_cmd(self, event):
        loader = self._loader()
        if not loader:
            return await event.edit("❌ Loader is not initialized.")

        args = event.raw_text.split(maxsplit=1)
        query = args[1].strip() if len(args) > 1 else ""

        if query:
            module = self._find_module(query)
            if not module and query in loader.commands:
                module = getattr(loader.commands[query], "__self__", None)

            if not module:
                return await event.edit(f"❌ Модуль или команда `{query}` не найдены.")

            commands = self._iter_commands(module)
            command_lines = "\n".join(f"• `.{name}`" for name in commands) or "• Нет команд"
            description = getattr(module, "description", "") or "Без описания"
            text = (
                f"📦 <b>{module.name}</b>\n"
                f"{description}\n\n"
                f"<b>Команды:</b>\n{command_lines}"
            )
            return await event.edit(text, parse_mode="html")

        hidden = self._get_hidden()
        rows = []
        for module in sorted(loader.modules, key=lambda item: item.name.lower()):
            if module.name in hidden:
                continue

            commands = self._iter_commands(module)
            command_text = ", ".join(f".{name}" for name in commands) if commands else "без команд"
            rows.append(f"• <b>{module.name}</b>: <code>{command_text}</code>")

        text = (
            f"🜂 <b>Zenkai Modules</b>\n"
            f"Загружено модулей: <code>{len(loader.modules)}</code>\n"
            f"Команд: <code>{len(loader.commands)}</code>\n\n"
            + ("\n".join(rows) if rows else "Нет загруженных модулей.")
        )
        await event.edit(text, parse_mode="html")

    @command(name="support", description="Show support contact info.")
    async def support_cmd(self, event):
        await event.edit(
            "🜂 <b>Zenkai Support</b>\n"
            "Если модуль падает, скинь название модуля, команду и текст ошибки.",
            parse_mode="html",
        )
