"""Offline smoke check: python -m nawa.intelligence.smoke

Calls the local chat and embedding models through the gateway and confirms that
outbound internet access fails. Exit code 0 means the offline guarantees hold.
"""

import asyncio
import sys
import urllib.request

from nawa.core.config import get_settings
from nawa.intelligence.gateway import ChatMessage, LiteLLMClient, LLMGateway, TraceInfo


def _internet_reachable() -> bool:
    try:
        urllib.request.urlopen("https://pypi.org", timeout=5)  # noqa: S310 - fixed https URL
    except OSError:
        return False
    return True


async def _main() -> int:
    settings = get_settings()
    if not settings.offline_mode:
        print("FAIL: OFFLINE_MODE is not enabled")
        return 1
    if _internet_reachable():
        print("FAIL: outbound internet is reachable")
        return 1
    gateway = LLMGateway(LiteLLMClient(), settings, model=settings.local_llm_model)
    result = await gateway.chat([ChatMessage("user", "Say OK.")], TraceInfo(name="offline-smoke"))
    vectors = await gateway.embed(["offline embedding check"])
    print(f"OK: chat via {result.model}, embedding dim {len(vectors[0])}, internet blocked")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
