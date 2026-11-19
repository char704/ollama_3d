"""Small local Ollama agent that does not depend on MCP."""


def handle(message):
    from .run import handle as run_handle

    return run_handle(message)


__all__ = ["handle"]
