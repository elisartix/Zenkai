import asyncio
import logging
import random
import re
import string
from telethon import events

logger = logging.getLogger(__name__)

class BotFatherHelper:
    """Automates interacting with @BotFather to create and manage an inline bot."""
    def __init__(self, client):
        self.client = client
        self.botfather = "@BotFather"
        
    async def create_new_bot(self, custom_username=None):
        """Communicates with BotFather to create a new inline bot and obtain its token."""
        logger.info("Starting automated bot creation via @BotFather...")
        
        # Start the conversation
        await self.client.send_message(self.botfather, "/newbot")
        await asyncio.sleep(2)
        
        # Reply with the Name
        name = "Zenkai Userbot"
        await self.client.send_message(self.botfather, name)
        await asyncio.sleep(2)
        
        # Reply with a unique Username
        usernames = []
        if custom_username:
            usernames.append(custom_username.strip().lstrip("@"))
        for _ in range(5):
            uid = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
            usernames.append(f"zenkai_{uid}_bot")

        for username in usernames:
            await self.client.send_message(self.botfather, username)
            
            # Wait for response token
            await asyncio.sleep(3)
            
            messages = await self.client.get_messages(self.botfather, limit=2)
            for msg in messages:
                if msg.text and "token" in msg.text.lower():
                    # Extract the token format (e.g., 123456789:ABCdefgHIJKlmnopQRSTuvwXYZ123)
                    token_match = re.search(r"(\d+:[a-zA-Z0-9_-]+)", msg.text)
                    if token_match:
                        token = token_match.group(1)
                        logger.info("Successfully created inline bot!")
                        
                        # Enable Inline Mode
                        await self.enable_inline_mode(username)
                        return token
                        
                elif "sorry" in msg.text.lower() or "taken" in msg.text.lower():
                    logger.warning(f"Username {username} taken, trying again...")
                    break
        
        logger.error("Failed to create inline bot after 5 tries.")
        return None

    async def start_bot_chat(self, username):
        """Ensures the created inline bot has an opened dialog and receives /start."""
        try:
            await self.client.send_message(f"@{username}", "/start")
            logger.info("Sent /start to @%s", username)
        except Exception as e:
            logger.error("Failed to send /start to @%s: %s", username, e)

    async def create_folder(self, usernames):
        """Creates or updates the 'Zenkai' folder with all Zenkai-related chats."""
        logger.info("Ensuring 'Zenkai' Telegram folder exists...")
        try:
            from telethon.tl.functions.messages import (
                GetDialogFiltersRequest,
                UpdateDialogFilterRequest,
            )
            from telethon.tl.types import DialogFilter, TextWithEntities

            peers = []
            bot_peer = None
            for username in usernames:
                if not username:
                    continue

                try:
                    peer = await self.client.get_input_entity(f"@{username}")
                    peers.append(peer)
                    if bot_peer is None:
                        bot_peer = peer
                except Exception as e:
                    logger.warning("Skipping folder peer @%s: %s", username, e)

            if not peers:
                logger.warning("No peers collected for Zenkai folder")
                return

            unique_peers = []
            seen = set()
            for peer in peers:
                key = (
                    getattr(peer, "user_id", None),
                    getattr(peer, "chat_id", None),
                    getattr(peer, "channel_id", None),
                )
                if key in seen:
                    continue
                seen.add(key)
                unique_peers.append(peer)

            result = await self.client(GetDialogFiltersRequest())
            filters = getattr(result, "filters", []) if hasattr(result, "filters") else result
            dialog_filter = None

            for filter_obj in filters:
                if not hasattr(filter_obj, 'title'):
                    continue
                raw_title = getattr(filter_obj.title, "text", filter_obj.title)
                if str(raw_title).strip() == "Zenkai":
                    dialog_filter = filter_obj
                    break

            if dialog_filter is None:
                try:
                    folder_id = (
                        max(
                            (folder for folder in filters if hasattr(folder, "id")),
                            key=lambda item: item.id,
                        ).id
                        + 1
                    )
                except ValueError:
                    folder_id = 2
            else:
                folder_id = dialog_filter.id

            pinned = [bot_peer] if bot_peer is not None else unique_peers[:1]
            include = list(unique_peers)
            exclude = []
            emoticon = "🪐"
            color = None

            if dialog_filter is not None:
                emoticon = getattr(dialog_filter, "emoticon", None) or emoticon
                color = getattr(dialog_filter, "color", None)

            logger.info(
                "Updating Zenkai folder: folder_id=%s, pinned=%s, include=%s",
                folder_id,
                len(pinned),
                len(include),
            )

            await self.client(UpdateDialogFilterRequest(
                id=folder_id,
                filter=DialogFilter(
                    id=folder_id,
                    title=TextWithEntities(text="Zenkai", entities=[]),
                    pinned_peers=pinned,
                    include_peers=include,
                    exclude_peers=exclude,
                    contacts=False,
                    non_contacts=False,
                    groups=False,
                    broadcasts=False,
                    bots=False,
                    exclude_muted=False,
                    exclude_read=False,
                    exclude_archived=False,
                    emoticon=emoticon,
                    color=color,
                )
            ))
            logger.info("Zenkai folder is ready with %s chat(s).", len(include))

        except Exception as e:
            logger.error(f"Failed to create 'Zenkai' folder: {e}")

    async def enable_inline_mode(self, username):
        """Enables inline mode for the provided bot username."""
        await self.client.send_message(self.botfather, "/setinline")
        await asyncio.sleep(2)
        await self.client.send_message(self.botfather, f"@{username}")
        await asyncio.sleep(2)
        await self.client.send_message(self.botfather, "Zenkai ")
        await asyncio.sleep(2)
        logger.info(f"Inline mode enabled for @{username}.")
