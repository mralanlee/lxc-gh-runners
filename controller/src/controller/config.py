from pydantic import field_validator
from pydantic_settings import BaseSettings, EnvSettingsSource, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    github_webhook_secret: str
    github_pat: str
    github_org: str
    runner_labels: list[str]

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

    @classmethod
    def settings_customise_sources(cls, settings_cls, env_settings, **kwargs):
        # Prevent pydantic-settings from JSON-decoding runner_labels before
        # the field_validator runs; pass the raw comma-separated string through.
        class _RawEnv(EnvSettingsSource):
            def prepare_field_value(self, field_name, field, value, value_is_complex):
                if field_name == "runner_labels":
                    return value
                return super().prepare_field_value(field_name, field, value, value_is_complex)

        return (_RawEnv(settings_cls),)

    @field_validator("runner_labels", mode="before")
    @classmethod
    def split_labels(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v
