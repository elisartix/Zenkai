import asyncio
import json
import logging
import os

from core.client import ZenkaiTelegramClient
from web.server import WebServer
from core.loader import Loader
from inline.botfather import BotFatherHelper
from inline.bot import ZenkaiInlineManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONFIG_PATH = 'zenkai_config.json'

def load_config():
    """Load API credentials from config file or environment."""
    api_id = os.environ.get("API_ID")
    api_hash = os.environ.get("API_HASH")
    
    if not api_id and os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('api_id', 12345), data.get('api_hash', 'test')
        except Exception:
            pass
    
    return int(api_id) if api_id else 12345, api_hash or "test"


async def main():
    logger.info("Starting Zenkai Userbot...")
    
    api_id, api_hash = load_config()
    
    client = ZenkaiTelegramClient('zenkai_session', api_id, api_hash)
    
    # Always create the loader and attach it to the client
    loader = Loader(client, prefix=".")
    client.loader = loader  # <-- THIS WAS MISSING, causing .help crash
    
    server = WebServer(client)
    await server.start(port=8080)
    
    if api_id == 12345:
        logger.warning("Using dummy API keys. Please set keys in Web Panel or env variables.")
    else:
        try:
            await client.connect()
        except Exception as e:
            logger.warning(f"Initial Telegram connect failed: {e}")

    logger.info("Zenkai core is running. Visit http://localhost:8080 to login.")
    
    # Wait until the user is authorized (through web or session)
    while True:
        try:
            if client.is_connected() and await client.is_user_authorized():
                break
        except Exception:
            pass
        await asyncio.sleep(2)
        
        # Re-check if config was updated by web panel
        new_id, new_hash = load_config()
        if new_id != 12345 and api_id == 12345:
            api_id, api_hash = new_id, new_hash
            server_api_id = getattr(server.client, "api_id", getattr(server.client, "_api_id", None))
            if server_api_id == api_id:
                client = server.client
            else:
                client = ZenkaiTelegramClient('zenkai_session', api_id, api_hash)
            loader.client = client
            client.loader = loader
            server.client = client
            try:
                await client.connect()
            except Exception as e:
                logger.warning(f"Telegram reconnect after config update failed: {e}")
        
    if getattr(server, "setup_finish_required", False):
        logger.info("Telegram login complete. Waiting for Web Dashboard setup to finish...")
        await server.wait_for_clients_setup()

    logger.info("Session found. Starting bot...")
    me = await client.get_me()
    client.tg_me = me
    client.tg_id = me.id
    logger.info(f"Logged in as {me.first_name} (ID: {me.id})")
    
    logger.info("Initializing module loader after authorization...")
    try:
        await loader.load_all(modules_dir="modules")
    except Exception as e:
        logger.error(f"Module loading error: {e}")
    
    # Check for inline bot token config
    has_bot_token = False
    bot_token = None
    custom_bot = None
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            conf = json.load(f)
            bot_token = conf.get('bot_token')
            custom_bot = conf.get('custom_bot')
            has_bot_token = bot_token is not None
    
    if not has_bot_token:
        logger.info("No inline bot token found. Attempting to create one via @BotFather...")
        botfather = BotFatherHelper(client)
        bot_token = await botfather.create_new_bot(custom_bot)
        if bot_token:
            with open(CONFIG_PATH, 'r+', encoding='utf-8') as f:
                conf = json.load(f)
                conf['bot_token'] = bot_token
                f.seek(0)
                json.dump(conf, f, ensure_ascii=False, indent=2)
                f.truncate()
    
    if bot_token:
        logger.info("Preparing inline manager...")
        inline_mgr = ZenkaiInlineManager(api_id, api_hash, bot_token, client)
        client.inline_manager = inline_mgr
        logger.info("Starting inline manager startup sequence...")
        await inline_mgr.start()
        logger.info("Inline manager startup sequence completed.")
        
        # Start the dialog with the bot and keep Zenkai chats grouped in a folder
        try:
            logger.info("Resolving inline bot identity...")
            bot_me = await inline_mgr.bot.get_me()
            if bot_me and bot_me.username:
                logger.info("Inline bot resolved as @%s", bot_me.username)
                botfather = BotFatherHelper(client)
                logger.info("Sending /start to inline bot...")
                await botfather.start_bot_chat(bot_me.username)
                logger.info("Creating/updating Zenkai folder...")
                await botfather.create_folder([bot_me.username])
                logger.info("Zenkai folder setup finished.")
        except Exception as e:
            logger.warning(f"Could not prepare Zenkai chats: {e}")
        
    logger.info("Startup complete. Zenkai is running.")
    
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
        
if __name__ == "__main__":
    asyncio.run(main())
