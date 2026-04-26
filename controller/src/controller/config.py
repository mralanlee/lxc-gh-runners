from typing import Annotated

from pydantic import BeforeValidator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_labels(v):
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if s.strip()]
    return v


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    github_webhook_secret: str
    github_pat: str
    github_org: str
    runner_labels: Annotated[list[str], NoDecode, BeforeValidator(_split_labels)]

    proxmox_url: str
    proxmox_token_id: str
    proxmox_token_secret: str
    proxmox_node: str
    proxmox_host: str

    template_vmid: int
    runner_vmid_range_start: int
    runner_vmid_range_end: int
    max_concurrent_runners: int = 3
    max_job_duration_hours: int = 6

    db_path: str = "/data/controller.sqlite"
    log_level: str = "INFO"
