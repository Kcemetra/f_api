import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock
import uuid
import datetime
from src.main import app
from src.database import get_async_session
from src.models import Link, User
from src.auth import current_user, current_user_optional
from contextlib import asynccontextmanager

client = TestClient(app)

# юзер для тестов авторизации
TEST_USER_ID = uuid.uuid4()
mock_user = User(id=TEST_USER_ID, email="test@test.com", is_superuser=False)

# фейковая ссылка
mock_link = Link(
    original_url="https://test.com",
    short_code="testcode",
    clicks_count=0,
    user_id=TEST_USER_ID,
    created_at=datetime.datetime.now(datetime.timezone.utc)
)

# фейковая сессия БД
@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    # ответ от БД по умолчанию
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_link
    mock_result.scalars().all.return_value = [mock_link]
    session.execute.return_value = mock_result
    return session

# подменяем всё реальное на моки
@pytest.fixture(autouse=True)
def override_dependencies(mock_db_session, mocker):

    async def _override_db():
        yield mock_db_session
    async def _override_user():
        return mock_user

    app.dependency_overrides[get_async_session] = _override_db
    app.dependency_overrides[current_user] = _override_user
    app.dependency_overrides[current_user_optional] = _override_user

    @asynccontextmanager
    async def _mock_maker():
        yield mock_db_session

    mocker.patch("src.router_links.async_session_maker", _mock_maker)
    mocker.patch("src.background.async_session_maker", _mock_maker)

    yield
    app.dependency_overrides.clear()

# фейковый redis
@pytest.fixture(autouse=True)
def mock_redis(mocker):
    mock = AsyncMock()
    mock.get.return_value = None
    mocker.patch("src.router_links.redis_client", mock)
    mocker.patch("src.main.redis_client", mock)
    mocker.patch("src.background.redis_client", mock)
    return mock


# тесты запросов

def test_create_short_link(mock_db_session, mock_redis):
    response = client.post("/links/shorten", json={"original_url": "https://yandex.ru", "custom_alias": "yndx"})
    assert response.status_code == 200
    assert response.json()["short_code"] == "yndx"

def test_redirect_cache_hit(mock_redis):
    mock_redis.get.return_value = "https://cached-url.com"
    response = client.get("/somecode", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "https://cached-url.com"

def test_redirect_db_hit(mock_db_session, mock_redis):
    mock_redis.get.return_value = None
    response = client.get("/testcode", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "https://test.com"

def test_redirect_not_found(mock_db_session, mock_redis):
    mock_redis.get.return_value = None
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_result

    response = client.get("/notfound", follow_redirects=False)
    assert response.status_code == 404

def test_redirect_expired(mock_db_session, mock_redis):
    mock_redis.get.return_value = None
    expired_link = Link(
        original_url="https://test.com",
        short_code="exp",
        expires_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)
    )
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = expired_link
    mock_db_session.execute.return_value = mock_result

    response = client.get("/exp", follow_redirects=False)
    assert response.status_code == 410

def test_get_stats():
    response = client.get("/links/testcode/stats")
    assert response.status_code == 200
    assert "clicks_count" in response.json()

def test_search_link():
    response = client.get("/links/search/original?original_url=https://test.com")
    assert response.status_code == 200

def test_delete_link():
    response = client.delete("/links/testcode")
    assert response.status_code == 204

def test_update_link():
    response = client.put("/links/testcode", json={"original_url": "https://new.com"})
    assert response.status_code == 200

def test_get_my_profile():
    response = client.get("/links/my/profile")
    assert response.status_code == 200

def test_delete_all_my_links():
    response = client.delete("/links/my/all")
    assert response.status_code == 200

def test_update_all_my_links():
    response = client.put("/links/my/all", json={"original_url": "https://new.com"})
    assert response.status_code == 200

def test_delete_link_not_found(mock_db_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_result

    response = client.delete("/links/unknown_code")
    assert response.status_code == 404

def test_delete_link_forbidden(mock_db_session):
    mock_result = MagicMock()
    other_user_link = Link(original_url="https://test.com", short_code="testcode", user_id=uuid.uuid4())
    mock_result.scalar_one_or_none.return_value = other_user_link
    mock_db_session.execute.return_value = mock_result

    response = client.delete("/links/testcode")
    assert response.status_code == 403

def test_update_link_not_found(mock_db_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_result

    response = client.put("/links/unknown_code", json={"original_url": "https://new.com"})
    assert response.status_code == 404

def test_update_link_forbidden(mock_db_session):
    mock_result = MagicMock()
    other_user_link = Link(original_url="https://test.com", short_code="testcode", user_id=uuid.uuid4())
    mock_result.scalar_one_or_none.return_value = other_user_link
    mock_db_session.execute.return_value = mock_result

    response = client.put("/links/testcode", json={"original_url": "https://new.com"})
    assert response.status_code == 403

def test_get_stats_not_found(mock_db_session):
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_db_session.execute.return_value = mock_result

    response = client.get("/links/unknown_code/stats")
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_background_cleanup(mock_db_session, mock_redis):
    from src.background import clear_old_links

    mock_result = MagicMock()
    mock_result.scalars().all.return_value = [mock_link]
    mock_db_session.execute.return_value = mock_result

    await clear_old_links(mock_db_session)

    mock_redis.delete.assert_called_once()
    mock_db_session.delete.assert_called_once()
    mock_db_session.commit.assert_called_once()