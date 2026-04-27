from controller.config import Settings


def test_settings_loads_from_env(env_overrides):
    s = Settings()
    assert s.github_org == "testorg"
    assert s.runner_labels == ["self-hosted", "lxc"]
    assert s.template_vmid == 9000
    assert s.runner_vmid_range_start == 9100
    assert s.max_concurrent_runners == 3
    assert s.proxmox_url == "https://prox.test:8006"
    assert s.proxmox_host == "prox.test"


def test_runner_labels_split_on_comma_and_strip(monkeypatch, env_overrides):
    monkeypatch.setenv("RUNNER_LABELS", "  self-hosted , lxc , gpu  ")
    s = Settings()
    assert s.runner_labels == ["self-hosted", "lxc", "gpu"]
