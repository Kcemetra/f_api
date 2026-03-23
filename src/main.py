from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import asyncio
from datetime import datetime, timezone
from contextlib import asynccontextmanager
from src.auth import auth_backend, fastapi_users
from src.schemas import UserRead, UserCreate
from src.router_links import router as links_router, redis_client, update_click_stats
from src.database import get_async_session
from src.models import Link
from src.background import cleanup


# запускаем фоновую задачу очистки старых ссылок при запуске сервера
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(cleanup())
    yield
    task.cancel()

app = FastAPI(title="URL Shortener API", lifespan=lifespan)
AUTH_TAG = "Авторизация и регистрация"

# добавляем роутеры и эндпоинт

app.include_router(fastapi_users.get_auth_router(auth_backend), prefix="/auth/jwt", tags=[AUTH_TAG])
app.include_router(fastapi_users.get_register_router(UserRead, UserCreate), prefix="/auth", tags=[AUTH_TAG])
app.include_router(links_router)

@app.get("/{short_code}", tags=["Создание / удаление / изменение / получение информации по короткой ссылке"])
async def redirect_to_url(short_code: str, background_tasks: BackgroundTasks,
                          db: AsyncSession = Depends(get_async_session)):
    # проверяем кэш
    cached_url = await redis_client.get(short_code)

    if cached_url:
        background_tasks.add_task(update_click_stats, short_code)
        return RedirectResponse(url=cached_url)

    # если нет в кэше, идем в БД
    result = await db.execute(select(Link).where(Link.short_code == short_code))
    link = result.scalar_one_or_none()

    if not link:
        raise HTTPException(status_code=404, detail="Ссылка не найдена")

    if link.expires_at and link.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Ссылка истекла")

    # сохраняем в кэш
    await redis_client.set(short_code, link.original_url)

    # обновляем клики в фоне
    background_tasks.add_task(update_click_stats, short_code)

    return RedirectResponse(url=link.original_url)