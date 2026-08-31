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


def write_config(sections, path=None):
    """Write a nested {section: {key: value}} dict to config.ini, chmod 0600."""
    p = Path(path) if path else config_file_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    parser = configparser.ConfigParser()
    for section, items in sections.items():
        clean = {str(k): str(v) for k, v in items.items()
                 if v is not None and v != ""}
        if clean:
            parser[section] = clean
    with open(p, "w", encoding="utf-8") as fh:
        parser.write(fh)
    os.chmod(p, 0o600)
    return p


def _as_bool(value, default=False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on")


_KIBANA_KEYS = {"url", "username", "password", "insecure"}


def list_profiles(cfg) -> list:
    """Return sorted profile names, including ``default`` when legacy config exists."""
    names = set()
    if "kibana" in cfg or "defaults" in cfg:
        names.add("default")
    for key in cfg:
        if key.startswith("profile."):
            names.add(key[len("profile."):])
    return sorted(names)


def select_profile(cfg, name) -> dict:
    """Resolve ``name`` into a ``{"kibana": ..., "defaults": ...}`` dict.

    ``None``/empty and the literal ``"default"`` both resolve to the legacy
    ``[kibana]``/``[defaults]`` blocks.
    """
    if not name or name == "default":
        return {
            "kibana": cfg.get("kibana", {}),
            "defaults": cfg.get("defaults", {}),
        }
    section = cfg.get(f"profile.{name}")
    if section is None:
        raise ValueError(f"unknown profile: {name!r}")
    kb = {}
    df = {}
    for key, value in section.items():
        if key in _KIBANA_KEYS:
            kb[key] = value
        else:
            df[key] = value
    return {"kibana": kb, "defaults": df}


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
    export_backend: str = "reporting"


def build_settings(env, cfg, space=None, index=None, fields=None,
                   timeout=None, insecure=None, profile=None,
                   export_backend=None) -> Settings:
    """Resolve settings with precedence flag > env > config > default."""
    if profile:
        selected = select_profile(cfg, profile)
        kb = selected["kibana"]
        df = selected["defaults"]
    else:
        kb = cfg.get("kibana", {})
        df = cfg.get("defaults", {})

    url = env.get("KIBANA_URL") or kb.get("url", "")
    username = env.get("KIBANA_USERNAME") or kb.get("username", "")
    password = env.get("KIBANA_PASSWORD") or kb.get("password", "")

    resolved_space = space or env.get("KIBANA_SPACE") or df.get("space", "default")

    export_backend = export_backend or df.get("export_backend", "reporting")

    resolved_timeout = timeout
    if resolved_timeout is None and df.get("timeout"):
        resolved_timeout = int(df["timeout"])
    if resolved_timeout is None:
        resolved_timeout = 120

    if insecure is None:
        env_val = env.get("KIBANA_INSECURE")
        if env_val is not None:
            insecure = _as_bool(env_val)
        else:
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
        export_backend=export_backend,
    )
