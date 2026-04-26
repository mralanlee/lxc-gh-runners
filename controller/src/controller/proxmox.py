class ProxmoxClient:
    def __init__(self, *, api, node: str):
        self._api = api
        self._node = node

    def _node_lxc(self):
        return self._api.nodes(self._node).lxc

    def _lxc(self, vmid: int):
        return self._api.nodes(self._node).lxc(str(vmid))

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
        self._lxc(template_vmid).clone.post(newid=new_vmid)

    def set_description(self, *, vmid: int, description: str) -> None:
        self._lxc(vmid).config.put(description=description)

    def get_description(self, *, vmid: int) -> str:
        cfg = self._lxc(vmid).config.get()
        return cfg.get("description", "")

    def start(self, *, vmid: int) -> None:
        self._lxc(vmid).status.start.post()

    def stop(self, *, vmid: int) -> None:
        self._lxc(vmid).status.stop.post()

    def destroy(self, *, vmid: int) -> None:
        self._lxc(vmid).delete()
