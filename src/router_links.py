from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
import secrets
from datetime import datetime, timezone
import redis.asyncio as redis
from src.database import get_async_session, async_session_maker
from src.models import Link, User
from src.schemas import LinkCreate, LinkUpdate, LinkResponse, LinkStats, ProfileResponse, ProfileLink, BulkUpdateLinks
from src.auth import current_user, current_user_optional
from src.config import settings

router = APIRouter(prefix="/links")
redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)


async def update_click_stats(short_code: str):
    async with async_session_maker() as session:
        result = await session.execute(select(Link).where(Link.short_code == short_code))
        link = result.scalar_one_or_none()
        if link:
            link.clicks_count += 1
            link.last_clicked = datetime.now(timezone.utc)
            await session.commit()

TAG_1 = "Создание / удаление / изменение / получение информации по короткой ссылке"
@router.post("/shorten", response_model=LinkResponse, tags=[TAG_1])
async def create_short_link(data: LinkCreate, db: AsyncSession = Depends(get_async_session),
                            user: User = Depends(current_user_optional)):
    short_code = data.custom_alias if data.custom_alias else secrets.token_urlsafe(5)
    new_link = Link(
        original_url=str(data.original_url),
        short_code=short_code,
        expires_at=data.expires_at,
        user_id=user.id if user else None
    )
    db.add(new_link)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Alias уже занят.")

    await redis_client.set(short_code, str(data.original_url))
    return LinkResponse(short_code=short_code, original_url=str(data.original_url), expires_at=data.expires_at)

@router.delete("/{short_code}", status_code=204, tags=[TAG_1])
async def delete_link(short_code: str, db: AsyncSession = Depends(get_async_session),
                      user: User = Depends(current_user)):
    result = await db.execute(select(Link).where(Link.short_code == short_code))
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    if link.user_id != user.id and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Нет прав на удаление")

    await db.delete(link)
    await db.commit()
    await redis_client.delete(short_code)
    return None

@router.put("/{short_code}", response_model=LinkResponse, tags=[TAG_1])
async def update_link(short_code: str, data: LinkUpdate, db: AsyncSession = Depends(get_async_session),
                      user: User = Depends(current_user)):
    result = await db.execute(select(Link).where(Link.short_code == short_code))
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    if link.user_id != user.id and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Нет прав на изменение")

    link.original_url = str(data.original_url)
    await db.commit()
    await redis_client.set(short_code, link.original_url)
    return LinkResponse(short_code=link.short_code, original_url=link.original_url, expires_at=link.expires_at)

@router.get("/{short_code}/stats", response_model=LinkStats, tags=["Статистика по ссылке"])
async def get_stats(short_code: str, db: AsyncSession = Depends(get_async_session)):
    result = await db.execute(select(Link).where(Link.short_code == short_code))
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    return LinkStats(original_url=link.original_url, created_at=link.created_at, clicks_count=link.clicks_count,
                     last_clicked=link.last_clicked)

@router.get("/search/original", response_model=LinkResponse, tags=["Поиск ссылки по оригинальному URL"])
async def search_link(original_url: str, db: AsyncSession = Depends(get_async_session)):
    result = await db.execute(select(Link).where(Link.original_url == original_url))
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")
    return LinkResponse(short_code=link.short_code, original_url=link.original_url, expires_at=link.expires_at)

TAG_4 = "Профиль и массовые операции"
@router.get("/my/profile", response_model=ProfileResponse, tags=[TAG_4])
async def get_my_profile(db: AsyncSession = Depends(get_async_session), user: User = Depends(current_user)):
    result = await db.execute(select(Link).where(Link.user_id == user.id))
    links = result.scalars().all()
    active_links = [ProfileLink(short_code=l.short_code, original_url=l.original_url, expires_at=l.expires_at) for l in
                    links]
    return ProfileResponse(email=user.email, active_links=active_links)

@router.delete("/my/all", tags=[TAG_4])
async def delete_all_my_links(db: AsyncSession = Depends(get_async_session), user: User = Depends(current_user)):
    result = await db.execute(select(Link).where(Link.user_id == user.id))
    links = result.scalars().all()
    for link in links:
        await redis_client.delete(link.short_code)
        await db.delete(link)
    await db.commit()
    return {"message": f"Успешно удалено {len(links)} ваших ссылок"}

@router.put("/my/all", tags=[TAG_4])
async def update_all_my_links(data: BulkUpdateLinks, db: AsyncSession = Depends(get_async_session),
                              user: User = Depends(current_user)):
    result = await db.execute(select(Link).where(Link.user_id == user.id))
    links = result.scalars().all()
    updated_count = 0
    for link in links:
        changed = False
        if data.original_url != "leave_as_is":
            link.original_url = data.original_url
            changed = True
        if data.expires_at is not None:
            link.expires_at = data.expires_at
            changed = True

        if changed:
            await redis_client.set(link.short_code, link.original_url)
            updated_count += 1

    await db.commit()
    return {"message": f"Успешно обновлено {updated_count} ваших ссылок"}