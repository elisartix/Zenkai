# Copyright 2025, werpyock
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
__version__ = (1, 4, 1)
# meta developer: @terrasa120
from .. import loader, utils
import asyncio
import shlex

@loader.tds
class WSpamMod(loader.Module):
    """Гибкий спам-модуль."""

    strings = {
        "name": "WSpamMod",
        "no_args": "❌ Укажите количество, задержку и текст (текст обязательно в кавычках) или используйте ответ на сообщение.",
        "spamming": "✅ Начинаю спам...",
        "stopped": "🛑 Задачи приостановлены.",
    }

    def __init__(self):
        self.config = loader.ModuleConfig(
            "DEFAULT_COUNT", 10, "Количество сообщений по умолчанию",
            "DEFAULT_DELAY", 1.0, "Задержка между сообщениями по умолчанию (в секундах)",
            "DEFAULT_TEXT", "Привет, мир!", "Текст по умолчанию для спама",
            "DELETE_SPAM_ANNOUNCE", "false", "Удалять сообщение о начале спама: 'true' или 'false'",
            "FAST_MODE", True, "Включает максимальную скорость (параллельный спам при delay=0)"
        )
        self.spam_tasks = set()

    @loader.command()
    async def spamcmd(self, message):
        """Запуск спама.
Использование: .spam [кол-во сообщений] [задержка] \"текст\" (или ответ на сообщение)."""
        await self._start_spam(message, delete_after_send=False)

    @loader.command()
    async def dspamcmd(self, message):
        """Запуск спама с удалением отправленных сообщений.
Использование: .dspam [кол-во сообщений] [задержка] \"текст\" (или ответ на сообщение)."""
        await self._start_spam(message, delete_after_send=True)

    async def _start_spam(self, message, delete_after_send):
        args_raw = utils.get_args_raw(message)
        reply = await message.get_reply_message()

        count = self.config["DEFAULT_COUNT"]
        delay = self.config["DEFAULT_DELAY"]
        text = self.config["DEFAULT_TEXT"] if not reply else ""

        if args_raw:
            try:
                args_list = shlex.split(args_raw)
            except Exception:
                return await utils.answer(message, self.strings["no_args"])

            if args_list and args_list[0].isdigit():
                count = int(args_list[0])
                args_list = args_list[1:]

            if args_list:
                try:
                    delay = float(args_list[0])
                    args_list = args_list[1:]
                except ValueError:
                    pass

            if args_list:
                text = " ".join(args_list)
        elif not reply:
            return await utils.answer(message, self.strings["no_args"])

        delete_announce = str(self.config["DELETE_SPAM_ANNOUNCE"]).lower() == "true"
        if delete_announce:
            await message.delete()
        else:
            await utils.answer(message, self.strings["spamming"])

        async def fast_send_and_delete(coro):
            try:
                sent = await coro
                await sent.delete()
            except:
                pass

        async def spam_task():
            chat_id = utils.get_chat_id(message)
            if delay <= 0 and self.config["FAST_MODE"]:
                # Параллельный ультра-спам
                tasks = []
                for _ in range(count):
                    if reply and reply.media:
                        coro = self._client.send_file(
                            chat_id,
                            reply.media,
                            caption=text or None,
                            reply_to=reply.id
                        )
                    else:
                        coro = self._client.send_message(chat_id, text)
                    
                    if delete_after_send:
                        tasks.append(asyncio.create_task(fast_send_and_delete(coro)))
                    else:
                        tasks.append(asyncio.create_task(coro))
                
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
            else:
                # Последовательный спам (как раньше)
                for _ in range(count):
                    if reply and reply.media:
                        sent = await self._client.send_file(
                            chat_id,
                            reply.media,
                            caption=text or None,
                            reply_to=reply.id
                        )
                    else:
                        sent = await self._client.send_message(chat_id, text)
                    
                    if delete_after_send:
                        await sent.delete()
                    
                    if delay > 0:
                        await asyncio.sleep(delay)

        task = asyncio.create_task(spam_task())
        self.spam_tasks.add(task)
        task.add_done_callback(self.spam_tasks.discard)

    @loader.command()
    async def stopspamcmd(self, message):
        """Останавливает все активные задачи .spam."""
        await self._stop_spam(message)

    @loader.command()
    async def stopdspamcmd(self, message):
        """Останавливает все активные задачи .dspam."""
        await self._stop_spam(message)

    async def _stop_spam(self, message):
        for task in self.spam_tasks:
            task.cancel()
        self.spam_tasks.clear()
        await utils.answer(message, self.strings["stopped"])