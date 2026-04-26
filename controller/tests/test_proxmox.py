from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from controller.proxmox import ProxmoxClient


@pytest.fixture
def fake_api():
    """Build a MagicMock shaped like proxmoxer's ProxmoxAPI."""
    api = MagicMock()
    return api


@pytest.fixture
def client(fake_api):
    return ProxmoxClient(api=fake_api, node="pve", ssh_host="prox.test")


def test_list_lxcs_in_range_filters_by_vmid(client, fake_api):
    fake_api.nodes.return_value.lxc.get.return_value = [
        {"vmid": "9050", "status": "running"},
        {"vmid": "9100", "status": "running"},
        {"vmid": "9150", "status": "stopped"},
        {"vmid": "9200", "status": "running"},
    ]
    result = client.list_lxcs_in_range(start=9100, end=9199)
    assert sorted(result) == [9100, 9150]


def test_allocate_vmid_returns_lowest_free(client, fake_api):
    fake_api.nodes.return_value.lxc.get.return_value = [
        {"vmid": "9100", "status": "running"},
        {"vmid": "9102", "status": "running"},
    ]
    assert client.allocate_vmid(start=9100, end=9199) == 9101


def test_allocate_vmid_raises_when_full(client, fake_api):
    fake_api.nodes.return_value.lxc.get.return_value = [
        {"vmid": str(v), "status": "running"} for v in range(9100, 9105)
    ]
    with pytest.raises(RuntimeError, match="no free VMID"):
        client.allocate_vmid(start=9100, end=9104)


def test_clone_calls_api(client, fake_api):
    client.clone(template_vmid=9000, new_vmid=9100)
    fake_api.nodes.return_value.lxc.return_value.clone.post.assert_called_once_with(
        newid=9100
    )


def test_set_description_calls_config(client, fake_api):
    client.set_description(vmid=9100, description="job_id=42 started_at=now")
    fake_api.nodes.return_value.lxc.return_value.config.put.assert_called_once_with(
        description="job_id=42 started_at=now"
    )


def test_get_description_returns_string(client, fake_api):
    fake_api.nodes.return_value.lxc.return_value.config.get.return_value = {
        "description": "job_id=42 started_at=2026-04-26T00:00:00",
        "hostname": "CT9100",
    }
    assert client.get_description(vmid=9100) == "job_id=42 started_at=2026-04-26T00:00:00"


def test_start_calls_api(client, fake_api):
    client.start(vmid=9100)
    fake_api.nodes.return_value.lxc.return_value.status.start.post.assert_called_once()


def test_stop_calls_api(client, fake_api):
    client.stop(vmid=9100)
    fake_api.nodes.return_value.lxc.return_value.status.stop.post.assert_called_once()


def test_destroy_calls_api(client, fake_api):
    client.destroy(vmid=9100)
    fake_api.nodes.return_value.lxc.return_value.delete.assert_called_once()


def test_get_status(client, fake_api):
    fake_api.nodes.return_value.lxc.return_value.status.current.get.return_value = {
        "status": "running"
    }
    assert client.get_status(vmid=9100) == "running"


def test_get_create_time_parses_started_at_from_description(client, fake_api):
    fake_api.nodes.return_value.lxc.return_value.config.get.return_value = {
        "description": "job_id=42 started_at=2026-04-26T10:00:00+00:00",
    }
    ts = client.get_create_time(vmid=9100)
    assert ts.year == 2026 and ts.month == 4 and ts.day == 26


def test_get_create_time_raises_when_no_started_at(client, fake_api):
    fake_api.nodes.return_value.lxc.return_value.config.get.return_value = {
        "description": "no timestamp here",
    }
    with pytest.raises(ValueError, match="started_at"):
        client.get_create_time(vmid=9100)


def test_wait_until_ready_polls_status(client, fake_api, monkeypatch):
    statuses = iter([{"status": "stopped"}, {"status": "running"}])
    fake_api.nodes.return_value.lxc.return_value.status.current.get.side_effect = (
        lambda: next(statuses)
    )
    sleeps = []
    monkeypatch.setattr("controller.proxmox.time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr("controller.proxmox.time.monotonic", lambda: 0.0)
    client.wait_until_ready(vmid=9100, timeout=5.0, interval=0.1)
    assert len(sleeps) >= 1


def test_wait_until_ready_times_out(client, fake_api, monkeypatch):
    fake_api.nodes.return_value.lxc.return_value.status.current.get.return_value = {
        "status": "stopped"
    }
    monkeypatch.setattr("controller.proxmox.time.sleep", lambda s: None)
    times = iter([0.0, 0.05, 0.1, 0.5, 1.0])
    monkeypatch.setattr("controller.proxmox.time.monotonic", lambda: next(times))
    with pytest.raises(TimeoutError):
        client.wait_until_ready(vmid=9100, timeout=0.1, interval=0.05)


def test_exec_returns_stdout_stderr_exit_code(client, monkeypatch):
    completed = MagicMock(stdout="JITCONFIG written\n", stderr="", returncode=0)
    monkeypatch.setattr(
        "controller.proxmox.subprocess.run", lambda *a, **kw: completed
    )
    out, err, code = client.exec(vmid=9100, cmd=["sh", "-c", "echo hi"])
    assert "written" in out
    assert err == ""
    assert code == 0


def test_exec_raises_on_nonzero(client, monkeypatch):
    completed = MagicMock(stdout="", stderr="boom\n", returncode=1)
    monkeypatch.setattr(
        "controller.proxmox.subprocess.run", lambda *a, **kw: completed
    )
    with pytest.raises(RuntimeError, match="exit_code=1"):
        client.exec(vmid=9100, cmd=["false"])


def test_exec_builds_ssh_command_correctly(client, monkeypatch):
    captured = {}
    def fake_run(args, **kwargs):
        captured["args"] = args
        return MagicMock(stdout="", stderr="", returncode=0)
    monkeypatch.setattr("controller.proxmox.subprocess.run", fake_run)
    client.exec(vmid=9100, cmd=["sh", "-c", "echo hi"])
    args = captured["args"]
    assert args[0] == "ssh"
    assert "-i" in args
    assert "/etc/controller/proxmox_ssh_key" in args
    assert "root@prox.test" in args
    assert "pct" in args
    assert "exec" in args
    assert "9100" in args


def test_exec_raises_if_ssh_host_not_configured(fake_api, monkeypatch):
    bare_client = ProxmoxClient(api=fake_api, node="pve")  # no ssh_host
    with pytest.raises(RuntimeError, match="ssh_host"):
        bare_client.exec(vmid=9100, cmd=["echo"])
