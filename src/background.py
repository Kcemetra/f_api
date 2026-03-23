import asyncio
from datetime import datetime, timezone, timedelta
from sqlalchemy import select
from src.database import async_session_maker
from src.models import Link
from src.router_links import redis_client

# логика проверки и удаления старых ссылок
async def clear_old_links(session):
    now = datetime.now(timezone.utc)
    month_ago = now - timedelta(days=30)
    stmt = select(Link).where(
        (Link.expires_at < now) |
        ((Link.last_clicked < month_ago) & (Link.clicks_count > 0)) |
        ((Link.created_at < month_ago) & (Link.clicks_count == 0))
    )
    result = await session.execute(stmt)
    old_links = result.scalars().all()

    for link in old_links:
        await redis_client.delete(link.short_code)
        await session.delete(link)

    if old_links:
        await session.commit()
        print(f"Удалено старых ссылок: {len(old_links)}")

# фоновый цикл, раз в 24 часа просыпается и очищает старые ссылки
async def cleanup():
    while True:
        try:
            async with async_session_maker() as session:
                await clear_old_links(session)
        except Exception as e:
            print(f"Ошибка при очистке БД: {e}")

        await asyncio.sleep(86400)