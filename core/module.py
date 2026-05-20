class Module:
    """Base class for all Zenkai modules.
    Modules should inherit from this and define commands using the @command decorator.
    
    Attributes:
        name (str): Name of the module.
        description (str): Description of the module.
    """
    name = "Unnamed"
    description = "No description provided."

    def __init__(self):
        self.client = None
        
    async def on_load(self):
        """Called when the module is loaded."""
        pass
        
    async def on_unload(self):
        """Called when the module is unloaded."""
        pass

def command(name=None, aliases=None, description=""):
    """Decorator to register a method as a module command.
    
    Args:
        name (str): Name of the command. Defaults to the method name.
        aliases (list): List of alternative command names.
        description (str): Description of what the command does.
    """
    def decorator(func):
        func.is_command = True
        func.command_name = name or func.__name__
        func.command_aliases = aliases or []
        func.command_description = description
        return func
    return decorator
