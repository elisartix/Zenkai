import html
import logging
import secrets

from telethon import Button, TelegramClient, events
from telethon.tl import types as tl_types

logger = logging.getLogger(__name__)


class ZenkaiInlineManager:
    """Minimal inline form runtime for Zenkai."""

    def __init__(self, api_id, api_hash, bot_token, userbot_client=None):
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.bot = TelegramClient("zenkai_inline_bot", self.api_id, self.api_hash)
        self.userbot = userbot_client
        self.handlers = {}
        self.units = {}
        self.callback_map = {}
        self.input_map = {}
        self.bot_username = None
        self.bot_id = None

    def _rand(self, size=16):
        return secrets.token_hex(size // 2 + 1)[:size]

    def new_unit_id(self, size=16):
        return self._rand(size)

    async def start(self):
        if not self.bot_token:
            logger.warning("No bot_token provided. Inline features will be disabled.")
            return

        logger.info("Starting Inline Bot...")
        await self.bot.start(bot_token=self.bot_token)
        bot_me = await self.bot.get_me()
        self.bot_username = getattr(bot_me, "username", None)
        self.bot_id = getattr(bot_me, "id", None)

        self.bot.add_event_handler(self._handle_start, events.NewMessage(pattern="/start"))
        self.bot.add_event_handler(self._handle_help, events.NewMessage(pattern="/help"))
        self.bot.add_event_handler(self.handle_callback, events.CallbackQuery)
        self.bot.add_event_handler(self.handle_inline, events.InlineQuery)
        self.bot.add_event_handler(self.handle_raw, events.Raw(types=tl_types.UpdateBotInlineSend))
        logger.info("Inline Bot started successfully.")

    def register_callback(self, data_prefix, handler):
        self.handlers[data_prefix] = handler

    async def form(self, text, message, reply_markup=None, silent=False, unit_id=None):
        if not self.bot_username:
            return False

        unit_id = unit_id or self._rand(16)
        self.units[unit_id] = {
            "type": "form",
            "text": text,
            "buttons": reply_markup or [],
        }

        try:
            query = await self.userbot.inline_query(self.bot_username, unit_id)
            await query[0].click(
                message.chat_id,
                reply_to=getattr(message, "reply_to_msg_id", None),
                hide_via=bool(silent),
            )
        except Exception as e:
            logger.error("Failed to send inline form: %s", e)
            return False

        return unit_id

    def _clear_unit_tokens(self, unit_id):
        for token, meta in list(self.callback_map.items()):
            if meta.get("unit_id") == unit_id:
                del self.callback_map[token]
        for token, meta in list(self.input_map.items()):
            if meta.get("unit_id") == unit_id:
                del self.input_map[token]

    def _build_markup(self, unit_id):
        self._clear_unit_tokens(unit_id)
        unit = self.units[unit_id]
        markup = []
        for row in unit.get("buttons", []):
            built_row = []
            for button in row:
                text = button.get("text", "Button")
                if button.get("action") == "close":
                    token = self._rand()
                    self.callback_map[token] = {
                        "unit_id": unit_id,
                        "handler": self._close_unit,
                        "args": (),
                        "kwargs": {},
                    }
                    built_row.append(Button.inline(text, token.encode("utf-8")))
                    continue

                if "callback" in button:
                    token = self._rand()
                    self.callback_map[token] = {
                        "unit_id": unit_id,
                        "handler": button["callback"],
                        "args": tuple(button.get("args", ()) or ()),
                        "kwargs": dict(button.get("kwargs", {}) or {}),
                    }
                    built_row.append(Button.inline(text, token.encode("utf-8")))
                    continue

                if "input" in button and "handler" in button:
                    token = self._rand(10)
                    self.input_map[token] = {
                        "unit_id": unit_id,
                        "handler": button["handler"],
                        "prompt": button["input"],
                        "args": tuple(button.get("args", ()) or ()),
                        "kwargs": dict(button.get("kwargs", {}) or {}),
                    }
                    built_row.append(Button.switch_inline(text, f"{token} ", same_peer=True))
                    continue

                if "url" in button:
                    built_row.append(Button.url(text, button["url"]))
            if built_row:
                markup.append(built_row)
        return markup

    async def edit_inline(self, inline_message_id, text, reply_markup=None):
        buttons = reply_markup or []
        return await self.bot.edit_message(
            inline_message_id,
            text,
            buttons=buttons,
            parse_mode="html",
            link_preview=False,
        )

    async def update_form(self, unit_id, inline_message_id, text, reply_markup=None):
        if unit_id not in self.units:
            self.units[unit_id] = {"type": "form", "text": text, "buttons": reply_markup or []}
        else:
            self.units[unit_id]["text"] = text
            self.units[unit_id]["buttons"] = reply_markup or []

        buttons = self._build_markup(unit_id)
        return await self.edit_inline(inline_message_id, text, buttons)

    async def _close_unit(self, event, *args, **kwargs):
        await event.edit("✅ Закрыто.", buttons=None)

    async def _handle_start(self, event):
        await event.respond(
            "🜂 **Zenkai Userbot**\n\n"
            "Это инлайн-бот Zenkai.\n"
            "Используйте `@{0}` в любом чате для инлайн-форм и модулей.".format(
                self.bot_username or "zenkai_inline_bot"
            ),
            parse_mode="md",
        )

    async def _handle_help(self, event):
        await event.respond(
            "🜂 **Zenkai Inline Help**\n\n"
            "`.cfg` открывает интерактивный конфиг через inline-бота.\n"
            "`.help` показывает модули.",
            parse_mode="md",
        )

    async def handle_callback(self, event):
        data = event.data.decode("utf-8")

        callback = self.callback_map.get(data)
        if callback:
            try:
                await callback["handler"](event, *callback["args"], **callback["kwargs"])
            except Exception as e:
                logger.error("Inline callback failed: %s", e)
                await event.answer(f"Error: {e}", alert=True)
            return

        for prefix, handler in self.handlers.items():
            if data.startswith(prefix):
                await handler(event)
                return

        await event.answer("Unknown action.")

    async def handle_raw(self, update):
        query = getattr(update, "query", "") or ""
        if not query:
            return

        if query in self.units:
            self.units[query]["inline_message_id"] = getattr(update, "msg_id", None)
            return

        token = query.split()[0]
        meta = self.input_map.get(token)
        if not meta:
            return

        if self.userbot and getattr(self.userbot, "tg_id", None) and update.user_id != self.userbot.tg_id:
            return

        value = query.split(maxsplit=1)[1] if len(query.split()) > 1 else ""
        try:
            await meta["handler"](value, *meta["args"], **meta["kwargs"])
        except Exception as e:
            logger.error("Inline input handler failed: %s", e)

    async def handle_inline(self, event):
        builder = event.builder
        query = (event.text or "").strip()
        token = query.split()[0] if query else ""

        input_meta = self.input_map.get(token)
        if input_meta:
            result = builder.article(
                title=input_meta["prompt"],
                description="Не удаляйте ID.",
                text="🔄 <b>Передаю значение в Zenkai...</b>\n<i>Это сообщение можно удалить.</i>",
                parse_mode="html",
            )
            await event.answer([result], cache_time=0)
            return

        if query in self.units and self.units[query]["type"] == "form":
            unit = self.units[query]
            result = builder.article(
                title="Zenkai",
                text=unit["text"],
                parse_mode="html",
                buttons=self._build_markup(query),
            )
            await event.answer([result], cache_time=0)
            return

        lowered = query.lower()
        results = []
        if self.userbot and hasattr(self.userbot, "loader") and self.userbot.loader:
            loader = self.userbot.loader
            if lowered:
                for mod in loader.modules:
                    if lowered in mod.name.lower() or lowered in (mod.description or "").lower():
                        cmds = [
                            c
                            for c, h in loader.commands.items()
                            if getattr(h, "__self__", None) == mod
                        ]
                        cmd_text = ", ".join(f".{c}" for c in cmds) if cmds else "нет команд"
                        results.append(
                            builder.article(
                                f"📦 {mod.name}",
                                text=(
                                    f"🪐 <b>{html.escape(mod.name)}</b>\n"
                                    f"{html.escape(mod.description or 'Нет описания')}\n\n"
                                    f"Команды: {html.escape(cmd_text)}"
                                ),
                                parse_mode="html",
                                description=f"{mod.description or 'Module'} | {cmd_text}",
                            )
                        )
            else:
                results.append(
                    builder.article(
                        "🜂 Zenkai Userbot",
                        text=(
                            f"🜂 <b>Zenkai Userbot</b>\n\n"
                            f"Загружено модулей: <code>{len(loader.modules)}</code>\n"
                            f"Доступно команд: <code>{len(loader.commands)}</code>\n\n"
                            f"Используйте <code>.help</code> или <code>.cfg</code>."
                        ),
                        parse_mode="html",
                        description=f"{len(loader.modules)} modules, {len(loader.commands)} commands",
                    )
                )

        if not results:
            results.append(
                builder.article(
                    "🜂 Zenkai Userbot",
                    text="🜂 <b>Zenkai Userbot</b>\nИспользуйте <code>.help</code> или <code>.cfg</code>.",
                    parse_mode="html",
                    description="Modular Telegram userbot.",
                )
            )

        await event.answer(results, cache_time=0)

    async def stop(self):
        await self.bot.disconnect()
