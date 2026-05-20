# Zenkai Userbot Module Developer Guide

Welcome to the Zenkai Userbot developer guide! Zenkai features a dynamic module loading system that makes creating custom commands incredibly simple. Zenkai is built on **Telethon**.

## Creating a new Module

To create a module, create a new `.py` file inside the `modules/` directory.

### Basic Structure

```python
from core.module import Module, command
from telethon import events

class MyModule(Module):
    # These properties define how your module appears in menus
    name = "MyAwesomeModule"
    description = "Does awesome things."

    async def on_load(self):
        # Optional: Code to execute when the module is loaded
        print(f"{self.name} loaded!")

    async def on_unload(self):
        # Optional: Code to execute when the module is unloaded
        pass

    @command(name="hello", aliases=["hi", "hey"], description="Says hello to the chat.")
    async def hello_cmd(self, event):
        # 'event' is a Telethon Message object
        # You can access self.client (the Telethon client) here
        
        # Get the arguments passed to the command
        args = event.pattern_match.group("args")
        
        if args:
            await event.edit(f"Hello, {args}!")
        else:
            await event.edit("Hello, World!")
```

## Using the Telethon Client

Because Zenkai inherits from `Module`, your class will have a `self.client` attribute populated after initialization.
You can use it to perform any Telethon operations:

```python
@command(name="getme")
async def getme_cmd(self, event):
    me = await self.client.get_me()
    await event.edit(f"My name is {me.first_name}")
```

## Creating Interactive Messages (Inline Bot)

Zenkai supports inline bots integrated seamlessly. The guide on routing inline callbacks directly into modules will be expanded in future versions, but for now, you can send interactive buttons via inline bots using standard Telethon methods.
