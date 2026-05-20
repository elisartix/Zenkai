class InlineCall:
    """Small Telethon-backed callback wrapper compatible with Heroku-style modules."""

    def __init__(self, event=None, inline_manager=None):
        self._event = event
        self.inline_manager = inline_manager
        raw_data = getattr(event, "data", b"") if event is not None else b""
        self.data = raw_data.decode("utf-8", errors="ignore") if isinstance(raw_data, bytes) else str(raw_data or "")
        self.chat_id = getattr(event, "chat_id", None)
        self.message_id = getattr(event, "message_id", None) or getattr(event, "msg_id", None)

    async def answer(self, text=None, show_alert=False, alert=None, **kwargs):
        if self._event is None:
            return None
        return await self._event.answer(text or "", alert=show_alert if alert is None else alert, **kwargs)

    async def edit(self, text, reply_markup=None, buttons=None, **kwargs):
        if self._event is None:
            return None
        markup = buttons if buttons is not None else reply_markup
        if self.inline_manager is not None:
            markup = self.inline_manager.build_buttons(markup)
        kwargs.setdefault("parse_mode", "html")
        kwargs.setdefault("link_preview", False)
        return await self._event.edit(text, buttons=markup, **kwargs)

    async def delete(self):
        if self._event is None:
            return None
        return await self._event.delete()

    async def unload(self, *args, **kwargs):
        return await self.delete()


class InlineMessage(InlineCall):
    pass


class InlineQuery:
    """Small inline-query wrapper for Heroku-style inline handlers."""

    def __init__(self, event=None):
        self._event = event
        self.query = getattr(event, "text", "") or ""
        self.args = self.query.split(maxsplit=1)[1] if len(self.query.split()) > 1 else ""

    async def answer(self, *args, **kwargs):
        if self._event is None:
            return None
        return await self._event.answer(*args, **kwargs)

    async def _error(self, title, description):
        if self._event is None:
            return None
        result = self._event.builder.article(
            title,
            description=description,
            text=f"🚫 <b>{title}</b>\n{description}",
            parse_mode="html",
        )
        return await self._event.answer([result], cache_time=0)

    async def e400(self):
        return await self._error("400", "Bad request")

    async def e403(self):
        return await self._error("403", "Forbidden")

    async def e404(self):
        return await self._error("404", "No results found")

    async def e500(self):
        return await self._error("500", "Inline handler failed")
