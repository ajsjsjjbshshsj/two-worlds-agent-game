"""Fixed local reply, using the same approved text as the demo provider."""

from twoworlds.application.dialogue import DEMO_ANSWER
from twoworlds.ports.narrative import NarrativeRequest


def fallback_reply(request: NarrativeRequest):
    return {
        "text": DEMO_ANSWER,
        "mode": "fallback",
        "provider_name": "demo",
        "prompt_version": request.prompt_version,
    }
