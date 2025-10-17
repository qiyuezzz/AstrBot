import pytest
import pytest_asyncio
import os
import asyncio
from quart import Quart
from astrbot.dashboard.server import AstrBotDashboard
from astrbot.core.db.sqlite import SQLiteDatabase
from astrbot.core.core_lifecycle import AstrBotCoreLifecycle
from astrbot.core import LogBroker
from astrbot.core.star.star_handler import star_handlers_registry
from astrbot.core.star.star import star_registry


@pytest_asyncio.fixture(scope="module")
async def core_lifecycle_td(tmp_path_factory):
    """Creates and initializes a core lifecycle instance with a temporary database."""
    tmp_db_path = tmp_path_factory.mktemp("data") / "test_data_v3.db"
    db = SQLiteDatabase(str(tmp_db_path))
    log_broker = LogBroker()
    core_lifecycle = AstrBotCoreLifecycle(log_broker, db)
    await core_lifecycle.initialize()
    return core_lifecycle


@pytest.fixture(scope="module")
def app(core_lifecycle_td: AstrBotCoreLifecycle):
    """Creates a Quart app instance for testing."""
    shutdown_event = asyncio.Event()
    # The db instance is already part of the core_lifecycle_td
    server = AstrBotDashboard(core_lifecycle_td, core_lifecycle_td.db, shutdown_event)
    return server.app


@pytest_asyncio.fixture(scope="module")
async def authenticated_header(app: Quart, core_lifecycle_td: AstrBotCoreLifecycle):
    """Handles login and returns an authenticated header."""
    test_client = app.test_client()
    response = await test_client.post(
        "/api/auth/login",
        json={
            "username": core_lifecycle_td.astrbot_config["dashboard"]["username"],
            "password": core_lifecycle_td.astrbot_config["dashboard"]["password"],
        },
    )
    data = await response.get_json()
    assert data["status"] == "ok"
    token = data["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_auth_login(app: Quart, core_lifecycle_td: AstrBotCoreLifecycle):
    """Tests the login functionality with both wrong and correct credentials."""
    test_client = app.test_client()
    response = await test_client.post(
        "/api/auth/login", json={"username": "wrong", "password": "password"}
    )
    data = await response.get_json()
    assert data["status"] == "error"

    response = await test_client.post(
        "/api/auth/login",
        json={
            "username": core_lifecycle_td.astrbot_config["dashboard"]["username"],
            "password": core_lifecycle_td.astrbot_config["dashboard"]["password"],
        },
    )
    data = await response.get_json()
    assert data["status"] == "ok" and "token" in data["data"]


@pytest.mark.asyncio
async def test_get_stat(app: Quart, authenticated_header: dict):
    test_client = app.test_client()
    response = await test_client.get("/api/stat/get")
    assert response.status_code == 401
    response = await test_client.get("/api/stat/get", headers=authenticated_header)
    assert response.status_code == 200
    data = await response.get_json()
    assert data["status"] == "ok" and "platform" in data["data"]


@pytest.mark.asyncio
async def test_plugins(app: Quart, authenticated_header: dict):
    test_client = app.test_client()
    # 已经安装的插件
    response = await test_client.get("/api/plugin/get", headers=authenticated_header)
    assert response.status_code == 200
    data = await response.get_json()
    assert data["status"] == "ok"

    # 插件市场
    response = await test_client.get(
        "/api/plugin/market_list", headers=authenticated_header
    )
    assert response.status_code == 200
    data = await response.get_json()
    assert data["status"] == "ok"

    # 插件安装
    response = await test_client.post(
        "/api/plugin/install",
        json={"url": "https://github.com/Soulter/astrbot_plugin_essential"},
        headers=authenticated_header,
    )
    assert response.status_code == 200
    data = await response.get_json()
    assert data["status"] == "ok"
    exists = False
    for md in star_registry:
        if md.name == "astrbot_plugin_essential":
            exists = True
            break
    assert exists is True, "插件 astrbot_plugin_essential 未成功载入"

    # 插件更新
    response = await test_client.post(
        "/api/plugin/update",
        json={"name": "astrbot_plugin_essential"},
        headers=authenticated_header,
    )
    assert response.status_code == 200
    data = await response.get_json()
    assert data["status"] == "ok"

    # 插件卸载
    response = await test_client.post(
        "/api/plugin/uninstall",
        json={"name": "astrbot_plugin_essential"},
        headers=authenticated_header,
    )
    assert response.status_code == 200
    data = await response.get_json()
    assert data["status"] == "ok"
    exists = False
    for md in star_registry:
        if md.name == "astrbot_plugin_essential":
            exists = True
            break
    assert exists is False, "插件 astrbot_plugin_essential 未成功卸载"
    exists = False
    for md in star_handlers_registry:
        if "astrbot_plugin_essential" in md.handler_module_path:
            exists = True
            break
    assert exists is False, "插件 astrbot_plugin_essential 未成功卸载"


@pytest.mark.asyncio
async def test_check_update(app: Quart, authenticated_header: dict):
    test_client = app.test_client()
    response = await test_client.get("/api/update/check", headers=authenticated_header)
    assert response.status_code == 200
    data = await response.get_json()
    assert data["status"] == "success"


@pytest.mark.asyncio
async def test_do_update(
    app: Quart,
    authenticated_header: dict,
    core_lifecycle_td: AstrBotCoreLifecycle,
    monkeypatch,
    tmp_path_factory,
):
    test_client = app.test_client()

    # Use a temporary path for the mock update to avoid side effects
    temp_release_dir = tmp_path_factory.mktemp("release")
    release_path = temp_release_dir / "astrbot"

    async def mock_update(*args, **kwargs):
        """Mocks the update process by creating a directory in the temp path."""
        os.makedirs(release_path, exist_ok=True)
        return

    async def mock_download_dashboard(*args, **kwargs):
        """Mocks the dashboard download to prevent network access."""
        return

    async def mock_pip_install(*args, **kwargs):
        """Mocks pip install to prevent actual installation."""
        return

    monkeypatch.setattr(core_lifecycle_td.astrbot_updator, "update", mock_update)
    monkeypatch.setattr(
        "astrbot.dashboard.routes.update.download_dashboard", mock_download_dashboard
    )
    monkeypatch.setattr(
        "astrbot.dashboard.routes.update.pip_installer.install", mock_pip_install
    )

    response = await test_client.post(
        "/api/update/do",
        headers=authenticated_header,
        json={"version": "v3.4.0", "reboot": False},
    )
    assert response.status_code == 200
    data = await response.get_json()
    assert data["status"] == "ok"
    assert os.path.exists(release_path)
