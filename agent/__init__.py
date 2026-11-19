"""Small local Ollama agent for deterministic Excel and Blender workflows."""


def handle(message):
    from .run import handle as run_handle

    return run_handle(message)


__all__ = ["handle"]
