import logging

from sqlalchemy.engine import make_url

from nawa.core.config import Settings

logger = logging.getLogger("nawa.demo")


def demo_database_urls(owner_url: str, name: str) -> tuple[str, str]:
    """Return (maintenance URL, demo database URL) derived from the owner connection URL."""
    base = make_url(owner_url)

    def render(database: str) -> str:
        return base.set(database=database).render_as_string(hide_password=False)

    return render("postgres"), render(name)


async def load_demo_data(settings: Settings) -> bool:
    """Create the demo database if needed and load Resto Noesantara into it.

    Runs after setup completes, in the background. It never raises: a failed demo load must
    not turn a successful setup into an error.
    """
    if not settings.database_owner_url:
        logger.warning("Demo data requested but DATABASE_OWNER_URL is not set; skipping")
        return False
    try:
        from noesantara_seed import load as seed_load  # on PYTHONPATH in the image

        admin_url, target_url = demo_database_urls(
            settings.database_owner_url, settings.demo_database_name
        )
        await seed_load.ensure_database(admin_url, settings.demo_database_name)
        counts = await seed_load.load_async(target_url)
    except Exception:
        logger.exception("Demo data load failed")
        return False
    logger.info("Demo data loaded into %s: %s", settings.demo_database_name, counts)
    return True


if __name__ == "__main__":  # `make seed`: python -m nawa.workspace.demo
    import asyncio
    import sys

    from nawa.core.config import get_settings

    logging.basicConfig(level=logging.INFO)
    sys.exit(0 if asyncio.run(load_demo_data(get_settings())) else 1)
