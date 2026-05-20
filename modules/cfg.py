import html

from core.module import Module, command


class ConfigModule(Module):
    name = "Config"
    description = "Interactive inline config editor."

    def _inline(self):
        return getattr(self.client, "inline_manager", None)

    def _modules_with_config(self):
        loader = getattr(self.client, "loader", None)
        if not loader:
            return []

        modules = []
        for module in loader.modules:
            config = getattr(module, "config", None)
            if config and getattr(config, "_config", None):
                modules.append(module)
        return sorted(modules, key=lambda item: item.name.lower())

    def _lookup(self, name):
        needle = name.strip().lower()
        for module in self._modules_with_config():
            if needle in {module.name.lower(), module.__class__.__name__.lower()}:
                return module
        return None

    def _validator(self, module, option):
        return getattr(module.config._config.get(option), "validator", None)

    def _is_hidden(self, module, option):
        validator = self._validator(module, option)
        return bool(validator and getattr(validator, "internal_id", "") == "Hidden")

    def _revealed_options(self, unit_id):
        inline = self._inline()
        if not inline:
            return set()
        unit = inline.units.setdefault(unit_id, {})
        revealed = unit.get("revealed_options")
        if not isinstance(revealed, set):
            revealed = set(revealed or [])
            unit["revealed_options"] = revealed
        return revealed

    def _is_revealed(self, unit_id, option):
        return option in self._revealed_options(unit_id)

    def _escape(self, value):
        return html.escape(str(value))

    def _mask(self, value):
        return "*" * max(1, len(str(value)))

    def _value_text(self, module, option, value, reveal=False):
        if self._is_hidden(module, option) and not reveal:
            value = self._mask(value)
        text = str(value)
        if len(text) > 160:
            text = text[:157] + "..."
        return self._escape(text)

    def _module_text(self, module):
        rows = []
        for option in module.config:
            rows.append(
                f"▫️ <code>{self._escape(option)}</code>: "
                f"<b>{self._value_text(module, option, module.config[option])}</b>"
            )

        return (
            f"⚙️ <b>Выбери параметр для модуля</b> <code>{self._escape(module.name)}</code>\n\n"
            f"<b>Текущие настройки:</b>\n\n" + "\n".join(rows)
        )

    def _validator_hint(self, validator):
        if not validator:
            return ""

        internal_id = getattr(validator, "internal_id", "")
        if internal_id == "Choice":
            return "🕵️ <b>Должно быть одним из:</b> " + " / ".join(
                self._escape(item) for item in getattr(validator, "values", [])
            )
        if internal_id == "Boolean":
            return "🕵️ <b>Должно быть:</b> True или False"
        if internal_id == "Integer":
            return "🕵️ <b>Должно быть целым числом</b>"
        if internal_id == "Float":
            return "🕵️ <b>Должно быть числом</b>"
        return ""

    def _option_text(self, unit_id, module, option):
        config = module.config
        validator = self._validator(module, option)
        hint = self._validator_hint(validator)
        doc = config.getdoc(option) or "Без описания."
        reveal = self._is_revealed(unit_id, option)
        return (
            f"⚙️ <b>Управление параметром</b> <code>{self._escape(option)}</code> "
            f"<b>модуля</b> <code>{self._escape(module.name)}</code>\n"
            f"ℹ️ <i>{doc}</i>\n\n"
            f"<b>Стандартное:</b> <code>{self._value_text(module, option, config.getdef(option), reveal=reveal)}</code>\n\n"
            f"<b>Текущее:</b> <code>{self._value_text(module, option, config[option], reveal=reveal)}</code>\n\n"
            f"{hint}"
        )

    def _home_markup(self, unit_id):
        buttons = []
        row = []
        for module in self._modules_with_config():
            row.append(
                {
                    "text": module.name,
                    "callback": self._show_module,
                    "args": (unit_id, module.name),
                }
            )
            if len(row) == 3:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append([{"text": "🔻 Закрыть", "action": "close"}])
        return buttons

    def _module_markup(self, unit_id, module):
        buttons = []
        row = []
        for option in module.config:
            row.append(
                {
                    "text": option,
                    "callback": self._show_option,
                    "args": (unit_id, module.name, option),
                }
            )
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)
        buttons.append(
            [
                {"text": "👉 Назад", "callback": self._show_home, "args": (unit_id,)},
                {"text": "🔻 Закрыть", "action": "close"},
            ]
        )
        return buttons

    def _choice_rows(self, unit_id, module, option):
        validator = self._validator(module, option)
        rows = []
        current = module.config[option]
        values = list(getattr(validator, "values", []) or [])
        row = []
        for choice in values:
            prefix = "✅" if choice == current else "⚪"
            row.append(
                {
                    "text": f"{prefix} {choice}",
                    "callback": self._set_direct_value,
                    "args": (unit_id, module.name, option, choice),
                }
            )
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        return rows

    def _bool_rows(self, unit_id, module, option):
        current = bool(module.config[option])
        return [
            [
                {
                    "text": ("✅ True" if current else "⚪ True"),
                    "callback": self._set_direct_value,
                    "args": (unit_id, module.name, option, True),
                },
                {
                    "text": ("✅ False" if not current else "⚪ False"),
                    "callback": self._set_direct_value,
                    "args": (unit_id, module.name, option, False),
                },
            ]
        ]

    def _option_markup(self, unit_id, module, option):
        validator = self._validator(module, option)
        rows = [[
            {
                "text": "✍️ Ввести значение",
                "input": "✍️ Введи новое значение этого параметра",
                "handler": self._set_input_value,
                "args": (unit_id, module.name, option),
            }
        ]]

        internal_id = getattr(validator, "internal_id", "")
        if internal_id == "Choice":
            rows.extend(self._choice_rows(unit_id, module, option))
        elif internal_id == "Boolean":
            rows.extend(self._bool_rows(unit_id, module, option))

        if self._is_hidden(module, option):
            rows.append(
                [
                    {
                        "text": "🙈 Скрыть значение" if self._is_revealed(unit_id, option) else "👁️ Показать значение",
                        "callback": self._toggle_hidden_value,
                        "args": (unit_id, module.name, option),
                    }
                ]
            )

        rows.append(
            [
                {
                    "text": "♻️ Значение по умолчанию",
                    "callback": self._reset_value,
                    "args": (unit_id, module.name, option),
                }
            ]
        )
        rows.append(
            [
                {
                    "text": "👉 Назад",
                    "callback": self._show_module,
                    "args": (unit_id, module.name),
                },
                {"text": "🔻 Закрыть", "action": "close"},
            ]
        )
        return rows

    async def _show_home(self, event, unit_id):
        inline = self._inline()
        await inline.update_form(
            unit_id,
            event.query.msg_id,
            "⚙️ <b>Выбери модуль для настройки</b>",
            self._home_markup(unit_id),
        )

    async def _show_module(self, event, unit_id, module_name):
        module = self._lookup(module_name)
        if not module:
            return await event.edit("❌ Модуль не найден.", buttons=None)

        await self._inline().update_form(
            unit_id,
            event.query.msg_id,
            self._module_text(module),
            self._module_markup(unit_id, module),
        )

    async def _show_option(self, event, unit_id, module_name, option):
        module = self._lookup(module_name)
        if not module or option not in module.config:
            return await event.edit("❌ Параметр не найден.", buttons=None)

        await self._inline().update_form(
            unit_id,
            event.query.msg_id,
            self._option_text(unit_id, module, option),
            self._option_markup(unit_id, module, option),
        )

    async def _toggle_hidden_value(self, event, unit_id, module_name, option):
        module = self._lookup(module_name)
        if not module or option not in module.config:
            return await event.answer("Параметр не найден", alert=True)

        revealed = self._revealed_options(unit_id)
        if option in revealed:
            revealed.discard(option)
        else:
            revealed.add(option)

        await self._inline().update_form(
            unit_id,
            event.query.msg_id,
            self._option_text(unit_id, module, option),
            self._option_markup(unit_id, module, option),
        )

    async def _set_direct_value(self, event, unit_id, module_name, option, value):
        module = self._lookup(module_name)
        if not module:
            return await event.answer("Module not found", alert=True)

        try:
            module.config[option] = value
        except Exception as e:
            return await event.answer(f"Ошибка: {e}", alert=True)

        await self._inline().update_form(
            unit_id,
            event.query.msg_id,
            self._option_text(unit_id, module, option),
            self._option_markup(unit_id, module, option),
        )

    async def _reset_value(self, event, unit_id, module_name, option):
        module = self._lookup(module_name)
        if not module:
            return await event.answer("Module not found", alert=True)

        module.config[option] = module.config.getdef(option)
        await self._inline().update_form(
            unit_id,
            event.query.msg_id,
            self._option_text(unit_id, module, option),
            self._option_markup(unit_id, module, option),
        )

    async def _set_input_value(self, value, unit_id, module_name, option):
        module = self._lookup(module_name)
        if not module:
            return

        inline_message_id = self._inline().units.get(unit_id, {}).get("inline_message_id")
        if not inline_message_id:
            return

        try:
            module.config[option] = value
        except Exception:
            value = f"❌ Некорректное значение: <code>{self._escape(value)}</code>"
            await self._inline().edit_inline(inline_message_id, value, [])
            return

        await self._inline().update_form(
            unit_id,
            inline_message_id,
            self._option_text(unit_id, module, option),
            self._option_markup(unit_id, module, option),
        )

    @command(name="cfg", aliases=["config"], description="Open inline config editor.")
    async def cfg_cmd(self, event):
        inline = self._inline()
        if not inline or not getattr(inline, "bot_username", None):
            return await event.edit("❌ Инлайн-бот ещё не готов.")

        args = event.raw_text.split()[1:]
        unit_id = inline.new_unit_id()

        if not args:
            text = "⚙️ <b>Выбери модуль для настройки</b>"
            markup = self._home_markup(unit_id)
        elif len(args) == 1:
            module = self._lookup(args[0])
            if not module:
                return await event.edit(f"❌ Модуль `{args[0]}` не найден.")
            text = self._module_text(module)
            markup = self._module_markup(unit_id, module)
        else:
            module = self._lookup(args[0])
            if not module or args[1] not in module.config:
                return await event.edit("❌ Модуль или параметр не найден.")
            text = self._option_text(unit_id, module, args[1])
            markup = self._option_markup(unit_id, module, args[1])

        result = await inline.form(text, event, reply_markup=markup, silent=True, unit_id=unit_id)
        if not result:
            return await event.edit("❌ Не удалось открыть inline-форму.")
