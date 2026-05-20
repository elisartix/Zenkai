import random
import platform
from telethon import TelegramClient

__version__ = (2, 0, 0)
APP_VERSION = ".".join(map(str, __version__)) + " x64"

def get_app_name():
    return "Zenkai Userbot"

def generate_random_system_version():
    return f"{random.randint(10, 15)}.{random.randint(0, 9)}.{random.randint(0, 9)}"

class ZenkaiTelegramClient(TelegramClient):
    """Custom TelegramClient for Zenkai Userbot with fake device data to prevent bans."""
    
    def __init__(self, session, api_id, api_hash, **kwargs):
        kwargs.setdefault("device_model", get_app_name())
        kwargs.setdefault("system_version", generate_random_system_version())
        kwargs.setdefault("app_version", APP_VERSION)
        kwargs.setdefault("lang_code", "en")
        kwargs.setdefault("system_lang_code", "en-US")
        
        super().__init__(session, api_id, api_hash, **kwargs)
        self.tg_me = None
        self.tg_id = None
        
    async def connect(self, *args, **kwargs):
        """Override to add any custom connection logic if necessary"""
        result = await super().connect(*args, **kwargs)
        # Populate tg_me and tg_id if authorized
        try:
            if await self.is_user_authorized():
                me = await self.get_me()
                if me:
                    self.tg_me = me
                    self.tg_id = me.id
        except Exception:
            pass
        return result
