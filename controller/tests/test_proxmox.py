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
    return ProxmoxClient(api=fake_api, node="pve")


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
