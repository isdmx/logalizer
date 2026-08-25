"""Config + connectivity health check."""
import json

from logalizer.client import Client, ClientError


def _parse_version(body):
    try:
        return json.loads(body)["version"]["number"]
    except (ValueError, KeyError, TypeError):
        return "unknown"


def run_ping(settings, config_path):
    print("logalizer ping")

    if config_path.exists():
        print(f"  ✓ config: {config_path}")
    else:
        print(f"  - no config file (using env vars) — run `logalizer --init` to persist")

    if settings.url and settings.username and settings.password:
        print(f"  ✓ credentials present (user={settings.username}, password=***)")
    else:
        print("  ✗ missing credentials (url/username/password) — run `logalizer --init` "
              "or set KIBANA_URL/KIBANA_USERNAME/KIBANA_PASSWORD")
        return 2

    client = Client(settings.url, settings.username, settings.password,
                    insecure=settings.insecure)

    try:
        status, body = client.request("GET", "/api/status")
    except ClientError as e:
        print(f"  ✗ TLS/connectivity: {e}")
        return 5
    version = _parse_version(body) if status == 200 else "?"
    print(f"  ✓ TLS + connectivity (Kibana {version})")

    status, body = client.request("GET", "/internal/security/me")
    if status in (401, 403):
        print("  ✗ auth failed (401/403) — check KIBANA_USERNAME/KIBANA_PASSWORD")
        return 3
    if status != 200:
        print(f"  ✗ auth endpoint returned HTTP {status}")
        return 5
    username = json.loads(body).get("username", "unknown")
    roles = json.loads(body).get("roles", [])
    print(f"  ✓ auth OK — logged in as {username} (roles: {', '.join(roles)})")

    if not settings.space:
        print("  - space check skipped (no space configured)")
    else:
        status, body = client.request("GET", "/api/spaces/space")
        if status != 200:
            print(f"  ✗ spaces list HTTP {status}")
            return 5
        spaces = [s["id"] for s in json.loads(body)]
        if settings.space in spaces:
            print(f"  ✓ space '{settings.space}' exists")
        else:
            avail = ", ".join(spaces) or "none"
            print(f"  ✗ space '{settings.space}' not found (available: {avail})")
            return 2

    if not settings.index:
        print("  - index check skipped (no index configured)")
    else:
        from logalizer.indexpatterns import resolve_index_pattern
        index_id = resolve_index_pattern(client, settings.space or "default", settings.index)
        if index_id:
            print(f"  ✓ index '{settings.index}' resolves → data-view {index_id}")
        else:
            print(f"  ✗ index '{settings.index}' not found in space '{settings.space or 'default'}'")
            return 2

    print("All checks passed.")
    return 0
