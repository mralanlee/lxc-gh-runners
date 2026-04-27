import re
import subprocess
import time
from datetime import datetime

_DESC_TS_RE = re.compile(r"started_at=(\S+)")


class ProxmoxClient:
    def __init__(
        self,
        *,
        api,
        node: str,
        ssh_host: str | None = None,
        ssh_user: str = "root",
        ssh_key_path: str = "/etc/controller/proxmox_ssh_key",
        ssh_strict_host_key_checking: str = "accept-new",
    ):
        self._api = api
        self._node = node
        self._ssh_host = ssh_host
        self._ssh_user = ssh_user
        self._ssh_key_path = ssh_key_path
        self._ssh_strict_host_key_checking = ssh_strict_host_key_checking

    def _node_lxc(self):
        return self._api.nodes(self._node).lxc

    def _lxc(self, vmid: int):
        return self._api.nodes(self._node).lxc(str(vmid))

    def _wait_task(self, upid: str, *, timeout: float = 120.0, interval: float = 0.5) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self._api.nodes(self._node).tasks(upid).status.get()
            if status.get("status") == "stopped":
                exit_status = status.get("exitstatus", "")
                if exit_status != "OK":
                    raise RuntimeError(
                        f"proxmox task {upid} failed: exitstatus={exit_status!r}"
                    )
                return
            time.sleep(interval)
        raise TimeoutError(
            f"proxmox task {upid} did not complete within {timeout}s"
        )

    def list_lxcs_in_range(self, *, start: int, end: int) -> list[int]:
        all_lxcs = self._node_lxc().get()
        return [
            int(c["vmid"])
            for c in all_lxcs
            if start <= int(c["vmid"]) <= end
        ]

    def allocate_vmid(self, *, start: int, end: int) -> int:
        used = set(self.list_lxcs_in_range(start=start, end=end))
        for v in range(start, end + 1):
            if v not in used:
                return v
        raise RuntimeError(f"no free VMID in range {start}-{end}")

    def clone(self, *, template_vmid: int, new_vmid: int) -> None:
        upid = self._lxc(template_vmid).clone.post(newid=new_vmid)
        self._wait_task(upid)

    def set_description(self, *, vmid: int, description: str) -> None:
        self._lxc(vmid).config.put(description=description)

    def get_description(self, *, vmid: int) -> str:
        cfg = self._lxc(vmid).config.get()
        return cfg.get("description", "")

    def start(self, *, vmid: int) -> None:
        upid = self._lxc(vmid).status.start.post()
        self._wait_task(upid)

    def stop(self, *, vmid: int) -> None:
        upid = self._lxc(vmid).status.stop.post()
        self._wait_task(upid)

    def destroy(self, *, vmid: int) -> None:
        upid = self._lxc(vmid).delete()
        self._wait_task(upid)

    def get_status(self, *, vmid: int) -> str:
        return self._lxc(vmid).status.current.get()["status"]

    def get_create_time(self, *, vmid: int) -> datetime:
        desc = self.get_description(vmid=vmid)
        m = _DESC_TS_RE.search(desc)
        if not m:
            raise ValueError(f"vmid {vmid} description missing started_at")
        return datetime.fromisoformat(m.group(1))

    def wait_until_ready(
        self, *, vmid: int, timeout: float = 30.0, interval: float = 1.0
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.get_status(vmid=vmid) == "running":
                time.sleep(interval)
                return
            time.sleep(interval)
        raise TimeoutError(f"vmid {vmid} did not become running within {timeout}s")

    def exec(self, *, vmid: int, cmd: list[str]) -> tuple[str, str, int]:
        if self._ssh_host is None:
            raise RuntimeError("ssh_host not configured on ProxmoxClient")
        pct_cmd = ["pct", "exec", str(vmid), "--", *cmd]
        ssh_args = [
            "ssh",
            "-i", self._ssh_key_path,
            "-o", f"StrictHostKeyChecking={self._ssh_strict_host_key_checking}",
            "-o", "BatchMode=yes",
            f"{self._ssh_user}@{self._ssh_host}",
            "--",
            *pct_cmd,
        ]
        result = subprocess.run(ssh_args, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"exec failed: exit_code={result.returncode} stderr={result.stderr!r}"
            )
        return result.stdout, result.stderr, result.returncode
