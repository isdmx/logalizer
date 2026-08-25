"""XDG path resolution and credential/settings assembly."""
import configparser
import os
from dataclasses import dataclass
from pathlib import Path


def xdg_config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def xdg_state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))


def xdg_cache_home() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))


def config_file_path() -> Path:
    return xdg_config_home() / "logalizer" / "config.ini"


def load_config(path=None) -> dict:
    """Return parsed config as a nested dict; {} if missing."""
    p = Path(path) if path else config_file_path()
    if not p.exists():
        return {}
    parser = configparser.ConfigParser()
    parser.read(str(p))
    return {section: dict(parser.items(section)) for section in parser.sections()}


def _as_bool(value, default=False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    url: str = ""
    username: str = ""
    password: str = ""
    space: str = "default"
    index: str = None
    fields: str = None
    timeout: int = 120
    insecure: bool = False


def build_settings(env, cfg, space=None, index=None, fields=None,
                   timeout=None, insecure=None) -> Settings:
    """Resolve settings with precedence flag > env > config > default."""
    kb = cfg.get("kibana", {})
    df = cfg.get("defaults", {})

    url = env.get("KIBANA_URL") or kb.get("url", "")
    username = env.get("KIBANA_USERNAME") or kb.get("username", "")
    password = env.get("KIBANA_PASSWORD") or kb.get("password", "")

    resolved_space = space or env.get("KIBANA_SPACE") or df.get("space", "default")

    resolved_timeout = timeout
    if resolved_timeout is None and df.get("timeout"):
        resolved_timeout = int(df["timeout"])
    if resolved_timeout is None:
        resolved_timeout = 120

    if insecure is None:
        insecure = _as_bool(env.get("KIBANA_INSECURE"))
    if not insecure:
        insecure = _as_bool(kb.get("insecure"))

    return Settings(
        url=url,
        username=username,
        password=password,
        space=resolved_space,
        index=index if index else df.get("index"),
        fields=fields if fields else df.get("fields"),
        timeout=resolved_timeout,
        insecure=insecure,
    )
