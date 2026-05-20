import os
import aiohttp
import aiofiles
from core.module import Module, command

class LoaderModule(Module):
    name = "Loader"
    description = "Commands to dynamically load and manage modules."

    @command(name="lm", description="Loads a module from a replied file.")
    async def lm_cmd(self, event):
        if not event.is_reply:
            return await event.edit("❌ Reply to a Python file to load it.")
            
        reply = await event.get_reply_message()
        if not reply.document or not reply.file.name.endswith(".py"):
            return await event.edit("❌ Replied message must be a `.py` file.")
            
        filename = reply.file.name
        filepath = os.path.join("modules", filename)
        
        # Download the file
        await event.edit(f"📥 Downloading `{filename}`...")
        await event.client.download_media(reply, filepath)
        
        # Load into the MAIN loader (client.loader), not a temp one
        loader = self.client.loader
        await loader.load_module(filename[:-3], filepath)
        await event.edit(f"✅ Module `{filename}` successfully loaded!")

    @command(name="dlm", description="Downloads and loads a module from a URL.")
    async def dlm_cmd(self, event):
        match = event.pattern_match.group("args")
        if not match:
            return await event.edit("❌ Provide a URL to download the module from.")
            
        url = match.strip()
        filename = url.split("/")[-1]
        if not filename.endswith(".py"):
            filename += ".py"
            
        filepath = os.path.join("modules", filename)
        await event.edit(f"📥 Downloading from `{url}`...")
        
        try:
           async with aiohttp.ClientSession() as session:
               async with session.get(url) as response:
                   if response.status != 200:
                       return await event.edit(f"❌ Failed to download. Status code: {response.status}")
                   
                   content = await response.read()
                   async with aiofiles.open(filepath, 'wb') as f:
                       await f.write(content)
                       
           # Load into the MAIN loader
           loader = self.client.loader
           await loader.load_module(filename[:-3], filepath)
           await event.edit(f"✅ Module `{filename}` downloaded and loaded!")
        except Exception as e:
            await event.edit(f"❌ Error downloading module: {e}")
