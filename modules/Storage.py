# ---------------------------------------------------------------------------------
# Name: Storage
# Description: Save files from replies and send them later by index.
# Author: @ElisArt
# Commands: s
# ---------------------------------------------------------------------------------

from .. import loader, utils


@loader.tds
class Storage(loader.Module):
    """Save files from replies and send them later by index."""

    strings = {
        "name": "Storage",
        "no_reply": "<b>Reply to a file to save it.</b>",
        "no_media": "<b>Reply does not contain a file.</b>",
        "saved": "<b>Saved as #{index}: {name}</b>",
        "list_empty": "<b>No saved files yet.</b>",
        "list_title": "<b>Saved files:</b>\n{rows}\n\nUse <code>{prefix}s N</code> to send.",
        "list_item": "{index}. <code>{name}</code>",
        "bad_index": "<b>Invalid index.</b>",
        "missing_saved": "<b>Saved file not found on server.</b>",
        "sent": "<b>File sent.</b>",
    }

    async def client_ready(self, client, db):
        self._client = client
        self._db = db
        if not isinstance(self.get("files"), list):
            self.set("files", [])

    @staticmethod
    def _get_media_name(message):
        if getattr(message, "file", None) and message.file.name:
            return message.file.name
        if getattr(message, "file", None) and message.file.ext:
            return f"file{message.file.ext}"
        return "file"

    @loader.command()
    async def s(self, message):
        """[reply] | save file; [index] | send saved file"""
        args = (utils.get_args_raw(message) or "").strip()
        reply = await message.get_reply_message()

        if reply:
            if not getattr(reply, "media", None):
                return await utils.answer(message, self.strings["no_media"])

            saved = await self._client.forward_messages(self.tg_id, reply)
            name = self._get_media_name(reply)

            files = self.get("files") or []
            files.append({"msg_id": saved.id, "name": name})
            self.set("files", files)

            return await utils.answer(
                message,
                self.strings["saved"].format(
                    index=len(files),
                    name=utils.escape_html(name),
                ),
            )

        if args:
            if not args.isdigit():
                return await utils.answer(message, self.strings["bad_index"])

            index = int(args)
            files = self.get("files") or []
            if index < 1 or index > len(files):
                return await utils.answer(message, self.strings["bad_index"])

            item = files[index - 1]
            saved = await self._client.get_messages(self.tg_id, ids=item["msg_id"])
            if not saved or not getattr(saved, "media", None):
                return await utils.answer(message, self.strings["missing_saved"])

            await self._client.send_file(
                message.chat_id,
                saved.media,
                caption=saved.text or None,
            )
            return await utils.answer(message, self.strings["sent"])

        files = self.get("files") or []
        if not files:
            return await utils.answer(message, self.strings["list_empty"])

        rows = "\n".join(
            self.strings["list_item"].format(
                index=i + 1,
                name=utils.escape_html(item.get("name") or "file"),
            )
            for i, item in enumerate(files)
        )
        return await utils.answer(
            message,
            self.strings["list_title"].format(prefix=self.get_prefix(), rows=rows),
        )