import hashlib
import hmac

import httpx


def verify_signature(*, secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    received = header[len("sha256=") :]
    return hmac.compare_digest(expected, received)


class GitHubClient:
    def __init__(self, *, pat: str, org: str):
        self._pat = pat
        self._org = org
        self._headers = {
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def generate_jit_config(self, *, name: str, labels: list[str]) -> str:
        url = f"https://api.github.com/orgs/{self._org}/actions/runners/generate-jitconfig"
        payload = {
            "name": name,
            "runner_group_id": 1,
            "labels": labels,
            "work_folder": "_work",
        }
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.post(url, headers=self._headers, json=payload)
            r.raise_for_status()
            return r.json()["encoded_jit_config"]

    async def get_workflow_job(self, *, repo: str, job_id: int) -> dict:
        url = f"https://api.github.com/repos/{repo}/actions/jobs/{job_id}"
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(url, headers=self._headers)
            r.raise_for_status()
            return r.json()
