"""HTTP uses the same validated envelope as the application boundary."""

from twoworlds.application.commands import GameCommand as SubmitCommand

__all__ = ["SubmitCommand"]
