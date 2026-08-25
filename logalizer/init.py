"""Interactive / non-interactive configuration writer."""
import getpass
import sys

from logalizer.config import _as_bool, load_config, write_config


def _prompt(label, default):
    suffix = f" [{default}]" if default else ""
    val = input(f"{label}{suffix}: ").strip()
    return val if val else default


def _prompt_password(default):
    suffix = " [set]" if default else ""
    val = getpass.getpass(f"Password{suffix} (blank to keep): ")
    return val if val else default


def run_init(args, env, config_path=None):
    existing = load_config(config_path)
    kb = existing.get("kibana", {})
    df = existing.get("defaults", {})

    url = args.url or kb.get("url", "")
    username = args.username or kb.get("username", "")
    password = args.password or env.get("KIBANA_PASSWORD") or kb.get("password", "")
    space = args.space or df.get("space", "default")
    index = args.index or df.get("index", "")
    insecure = args.insecure if args.insecure else _as_bool(kb.get("insecure"))

    interactive = not (url and username and password)

    if interactive:
        print("Configuring logalizer (blank = keep existing)", file=sys.stderr)
        if not url:
            url = _prompt("Kibana URL", url)
        if not username:
            username = _prompt("Username", username)
        if not password:
            password = _prompt_password(password)

    if not url or not username or not password:
        print("logalizer: url, username and password are required.", file=sys.stderr)
        return 2

    merged = {section: dict(items) for section, items in existing.items()}
    merged.setdefault("kibana", {}).update({
        "url": url, "username": username, "password": password,
        "insecure": "true" if insecure else "false",
    })
    merged.setdefault("defaults", {}).update({"space": space})
    if index:
        merged["defaults"]["index"] = index
    else:
        merged["defaults"].pop("index", None)

    path = write_config(merged, path=config_path)
    print(f"Wrote {path} (password: ***)")
    return 0
