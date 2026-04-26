import pytest


@pytest.fixture
def env_overrides(monkeypatch):
    """Set the minimum env vars needed to construct Settings()."""
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("GITHUB_PAT", "ghp_test")
    monkeypatch.setenv("GITHUB_ORG", "testorg")
    monkeypatch.setenv("RUNNER_LABELS", "self-hosted,lxc")
    monkeypatch.setenv("PROXMOX_URL", "https://prox.test:8006")
    monkeypatch.setenv("PROXMOX_TOKEN_ID", "ctrl@pve!t")
    monkeypatch.setenv("PROXMOX_TOKEN_SECRET", "tok")
    monkeypatch.setenv("PROXMOX_NODE", "pve")
    monkeypatch.setenv("PROXMOX_HOST", "prox.test")
    monkeypatch.setenv("TEMPLATE_VMID", "9000")
    monkeypatch.setenv("RUNNER_VMID_RANGE_START", "9100")
    monkeypatch.setenv("RUNNER_VMID_RANGE_END", "9199")
    monkeypatch.setenv("MAX_CONCURRENT_RUNNERS", "3")
    monkeypatch.setenv("MAX_JOB_DURATION_HOURS", "6")
    monkeypatch.setenv("DB_PATH", ":memory:")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
