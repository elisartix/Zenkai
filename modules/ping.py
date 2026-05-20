import time
from telethon import events
from core.module import Module, command

class PingModule(Module):
    name = "Ping"
    description = "Checks the bot's response time."

    @command(name="ping", aliases=["p"], description="Returns Pong with response time.")
    async def ping_cmd(self, event):
        start = time.perf_counter_ns()
        # Edit the message to show processing
        msg = await event.edit("🏓 Pong!")
        
        # Calculate time taken
        end = time.perf_counter_ns()
        ms = round((end - start) / 10**6, 2)
        
        await msg.edit(f"🏓 **Pong!**\nTime: `{ms}ms`")
