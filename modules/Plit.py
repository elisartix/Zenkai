from .. import loader, utils
import asyncio
import logging

logger = logging.getLogger(__name__)


@loader.tds
class PlitMod(loader.Module):
    """
    Модуль для отправки inline результатов от ботов.
    Позволяет автоматически кликать на inline результаты и отправлять их в чат.
    """

    strings = {"name": "Plit"}

    def __init__(self):
        super().__init__()
        self.config = loader.ModuleConfig(
            loader.ConfigValue(
                "bot_username",
                "mlversebot",
                "Username бота для inline запросов (без @)",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "query",
                "",
                "Текст для inline запроса",
                validator=loader.validators.String(),
            ),
            loader.ConfigValue(
                "count",
                50,
                "Количество отправок",
                validator=loader.validators.Integer(),
            ),
            loader.ConfigValue(
                "speed",
                2,
                "Скорость отправки (кол-во в секунду)",
                validator=loader.validators.Integer(),
            ),
        )
        self.is_running = False
        self.chat_id = None

    async def client_ready(self, client, db):
        """Инициализация модуля"""
        self.client = client
        self.db = db

    @loader.command(alias="плыть")
    async def плытьcmd(self, message):
        """
        .плыть - включить отправку inline результатов
        .плыть <количество> - отправить N результатов
        """
        if self.is_running:
            await utils.answer(message, "<b>⚠️ Отправка уже идет!</b>")
            return

        args = utils.get_args_raw(message)
        
        count = self.config["count"]
        
        # Если указано количество в аргументах
        if args:
            try:
                count = int(args)
            except ValueError:
                await utils.answer(message, "<b>❌ Укажите число</b>")
                return

        self.is_running = True
        self.chat_id = message.chat_id

        bot_username = self.config["bot_username"]
        query = self.config["query"]
        speed = self.config["speed"]
        delay = 1.0 / speed

        # Удаляем исходное сообщение
        await message.delete()

        try:
            await self._send_inline_results(
                bot_username, query, count, delay
            )
        except Exception as e:
            logger.error(f"PlitMod error: {e}", exc_info=True)
            await self.client.send_message(
                self.chat_id,
                f"<b>❌ Ошибка:</b> <code>{str(e)}</code>",
            )
        finally:
            self.is_running = False

    async def _send_inline_results(self, bot_username, query, count, delay):
        """Отправляет inline результаты в чат"""
        success_count = 0
        error_count = 0

        for i in range(count):
            if not self.is_running:
                break

            try:
                # Делаем inline запрос
                results = await self.client.inline_query(bot_username, query)

                if not results:
                    logger.warning(f"No results from {bot_username}")
                    error_count += 1
                    await asyncio.sleep(delay)
                    continue

                # Кликаем на первый результат
                result = results[0]
                await result.click(self.chat_id)

                success_count += 1
                logger.info(f"PlitMod: Отправлено {success_count}/{count}")

                await asyncio.sleep(delay)

            except Exception as e:
                logger.error(f"PlitMod iteration error: {e}", exc_info=True)
                error_count += 1
                await asyncio.sleep(delay)
                continue

    @loader.command(alias="стопплыть")
    async def стопплытьcmd(self, message):
        """
        .стопплыть - выключить отправку
        """
        if not self.is_running:
            await utils.answer(message, "<b>❌ Отправка не идет</b>")
            return

        self.is_running = False
        await utils.answer(message, "<b>✅ Отправка остановлена</b>")