"""Small local Ollama agent for deterministic Excel and Blender workflows."""


def handle(message, history=None):
    from .run import handle as run_handle

    return run_handle(message, history=history)


__all__ = ["handle"]
