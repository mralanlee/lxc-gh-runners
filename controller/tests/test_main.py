import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client(env_overrides, monkeypatch):
    """Build the real app but override Proxmox + GitHub builders with fakes."""
    from unittest.mock import AsyncMock, MagicMock

    fake_proxmox = MagicMock()
    fake_proxmox.list_lxcs_in_range.return_value = []
    fake_github = MagicMock()
    fake_github.generate_jit_config = AsyncMock(return_value="JITSTRING")
    fake_github.get_workflow_job = AsyncMock(return_value={"status": "in_progress"})

    monkeypatch.setattr("controller.main._build_proxmox", lambda settings: fake_proxmox)
    monkeypatch.setattr("controller.main._build_github", lambda settings: fake_github)

    from controller.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def test_health_returns_state_counts(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert "states" in r.json()


async def test_audit_endpoint_returns_list(client):
    r = await client.get("/audit")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
