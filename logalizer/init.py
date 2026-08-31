"""Interactive / non-interactive configuration writer."""
import getpass
import json
import sys

from logalizer import indexpatterns
from logalizer.client import Client, ClientError
from logalizer.config import _as_bool, load_config, write_config


def _prompt(label, default):
    suffix = f" [{default}]" if default else ""
    val = input(f"{label}{suffix}: ").strip()
    return val if val else default


def _prompt_password(default):
    suffix = " [set]" if default else ""
    val = getpass.getpass(f"Password{suffix} (blank to keep): ")
    return val if val else default


def _connect(url, username, password, insecure):
    """Return (client, message) on success, or (None, error) on failure."""
    client = Client(url, username, password, insecure=insecure)
    try:
        status, body = client.request("GET", "/api/status")
    except ClientError as e:
        return None, f"connection failed: {e}"
    version = "?"
    if status == 200:
        try:
            version = json.loads(body)["version"]["number"]
        except (ValueError, KeyError, TypeError):
            pass
    status, body = client.request("GET", "/internal/security/me")
    if status in (401, 403):
        return None, "authentication failed (wrong username/password?)"
    if status != 200:
        return None, f"auth endpoint returned HTTP {status}"
    username_real = json.loads(body).get("username", "unknown")
    return client, f"Kibana {version} as {username_real}"


def _pick_numbered(items, title, default):
    """Offer a numbered list; return selection, typed name, or default on blank.
    If items is None (listing failed), fall back to free-text."""
    if items:
        print(f"{title}:")
        for i, name in enumerate(items, 1):
            print(f"  [{i}] {name}")
        suffix = f" [{default}]" if default else ""
        val = input(f"Pick a number, type a name, or Enter{suffix}: ").strip()
        if val == "":
            return default
        if val.isdigit() and 1 <= int(val) <= len(items):
            return items[int(val) - 1]
        return val
    return _prompt(title, default)


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
        url = _prompt("Kibana URL", url)
        username = _prompt("Username", username)
        password = _prompt_password(password)
        ans = _prompt("Skip TLS verification? (y/N)", "y" if insecure else "")
        insecure = ans.strip().lower() in ("y", "yes")

        while True:
            client, msg = _connect(url, username, password, insecure)
            if client is not None:
                print(f"  ✓ {msg}")
                break
            print(f"  ✗ {msg} — fix and retry")
            url = _prompt("Kibana URL", url)
            username = _prompt("Username", username)
            password = _prompt_password(password)
            ans = _prompt("Skip TLS verification? (y/N)", "y" if insecure else "")
            insecure = ans.strip().lower() in ("y", "yes")

        try:
            spaces = indexpatterns.list_spaces(client)
        except ClientError:
            spaces = None
        space = _pick_numbered(spaces, "Available spaces", space)

        try:
            indices = indexpatterns.list_index_patterns(client, space)
        except ClientError:
            indices = None
        index = _pick_numbered(indices, f"Index patterns in '{space}'", index)

    if not url or not username or not password:
        print("logalizer: url, username and password are required.", file=sys.stderr)
        return 2

    merged = {section: dict(items) for section, items in existing.items()}

    profile = getattr(args, "profile", None)
    if profile:
        section = f"profile.{profile}"
        flat = {
            "url": url,
            "username": username,
            "password": password,
            "insecure": "true" if insecure else "false",
            "space": space,
        }
        if index:
            flat["index"] = index
        merged.setdefault(section, {}).update(flat)
    else:
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
