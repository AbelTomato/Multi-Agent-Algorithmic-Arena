"""Approved production application release only; does not run migrations."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import time
import urllib.request


APP = Path("/opt/multi-agent-arena/app")
RELEASE = Path("/opt/multi-agent-arena/history-release-20260919-1511")
BACKUP = Path("/opt/multi-agent-arena/history-app-release-20260919")
COMPOSE = APP / "compose.yaml"
NGINX = Path("/etc/nginx/conf.d/multi-agent-arena.conf")
FRONTEND = Path("/srv/multi-agent-arena/frontend/current")
STAGED = FRONTEND.with_name("history-20260919-staged")
PREVIOUS = FRONTEND.with_name("history-20260919-previous")
FAILED = FRONTEND.with_name("history-20260919-failed")
OLD = "sha256:4fe7a89e8a50372e8693e688d267fb1479fb7ead4e37d15384590a28494cf329"
NEW = "sha256:2cbcc94b937b2a4ff9643afe9669a2d0faa463b43dd8f5daa5bce4cbbc27e9cc"


def run(args):
    # Never print resolved Compose configuration or credentials.
    return subprocess.check_output(args, cwd=str(APP), stderr=subprocess.PIPE).decode()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace(path, content):
    temporary = path.with_name(path.name + ".history-next")
    with temporary.open("x") as stream:
        stream.write(content)
    shutil.copymode(str(path), str(temporary))
    os.replace(str(temporary), str(path))


def reload_nginx():
    run(["nginx", "-t"])
    run(["systemctl", "reload", "nginx"])


def healthy():
    for _ in range(60):
        status = run(["docker", "inspect", "--format", "{{.State.Health.Status}}", "app-backend-1"]).strip()
        if status == "healthy":
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=3) as response:
                assert json.load(response) == {"status": "ok"}
            return
        time.sleep(2)
    raise RuntimeError("backend health deadline exceeded")


def main():
    os.umask(0o077)
    assert digest(COMPOSE) == "5ab45d8cec0a9ccc41815235b43a02780064c019b511690c4fd4e7c970828292"
    assert digest(NGINX) == "0d2761b263bd795cc0fbef7b9c37aceb9b8abb3c2359037c1773c12590770298"
    assert digest(RELEASE / "nginx/multi-agent-arena.conf") == "f0bb1f07a09770e1f70cfc5764ec1abb2c9c7e9e2c3a048d95efe58fae5b4d54"
    assert run(["docker", "inspect", "--format", "{{.Image}}", "app-backend-1"]).strip() == OLD
    assert run(["docker", "image", "inspect", "--format", "{{.Id}}", NEW]).strip() == NEW
    revision = run(["docker", "compose", "exec", "-T", "postgres", "sh", "-c",
                    'psql -X -At -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 -c "SELECT version_num FROM alembic_version"'])
    assert revision.strip() == "0002"
    for path in (BACKUP, STAGED, PREVIOUS, FAILED):
        assert not path.exists() and not path.is_symlink()
    assert FRONTEND.is_dir() and not FRONTEND.is_symlink()
    # Check the uploaded, previously approved archives before consuming dist.
    assert digest(RELEASE / "frontend-dist.tar.gz") == "f1d4d7384e6b61bac1d9e257537a3fe5bd6f0a4c945235962dc46c6df085645b"
    with tarfile.open(str(RELEASE / "frontend-dist.tar.gz")) as archive:
        for member in archive.getmembers():
            assert not member.issym() and not member.islnk()
            assert not member.name.startswith("/") and ".." not in Path(member.name).parts
            if member.isfile():
                assert archive.extractfile(member).read() == (RELEASE / member.name).read_bytes()
    old_compose = COMPOSE.read_text()
    old_nginx = NGINX.read_text()
    assert old_compose.count(OLD) == 1
    assert old_compose.count("      EVALUATION_ENABLED: 'true'") == 1
    new_compose = old_compose.replace(OLD, NEW).replace(
        "      EVALUATION_ENABLED: 'true'",
        "      EVALUATION_ENABLED: 'true'\n"
        "      EVALUATION_HISTORY_ENABLED: 'true'\n"
        "      EVALUATION_HISTORY_COOKIE_SECURE: 'true'\n"
        "      EVALUATION_HISTORY_RETENTION_DAYS: '30'\n"
        "      EVALUATION_RUNNING_STALE_MINUTES: '10'",
    )
    maintenance = old_nginx
    for location in ("location = /api/evaluations {", "location = /api/solutions {", "location /api/ {"):
        assert maintenance.count(location) == 1
        maintenance = maintenance.replace(location, location + "\n        return 503;")
    BACKUP.mkdir(mode=0o700)
    shutil.copy2(str(COMPOSE), str(BACKUP / "compose.yaml"))
    shutil.copy2(str(NGINX), str(BACKUP / "nginx.conf"))
    shutil.copytree(str(RELEASE / "dist"), str(STAGED))
    for path in [STAGED] + list(STAGED.rglob("*")):
        assert not path.is_symlink()
        path.chmod(0o755 if path.is_dir() else 0o644)
    # Preserve old hashed assets for clients holding the previous index.html.
    if (FRONTEND / "assets").is_dir():
        for path in (FRONTEND / "assets").iterdir():
            target = STAGED / "assets" / path.name
            if path.is_file() and not target.exists():
                shutil.copy2(str(path), str(target))
    backend_changed = False
    nginx_changed = False
    frontend_changed = False
    try:
        nginx_changed = True
        replace(NGINX, maintenance)
        reload_nginx()
        print("maintenance_enabled draining_220_seconds", flush=True)
        # Existing requests keep their old workers; no new public API work enters.
        time.sleep(220)
        backend_changed = True
        replace(COMPOSE, new_compose)
        run(["docker", "compose", "config", "--quiet"])
        run(["docker", "compose", "up", "-d", "--no-deps", "--no-build", "--pull", "never", "backend"])
        healthy()
        assert run(["docker", "inspect", "--format", "{{.Image}}", "app-backend-1"]).strip() == NEW
        for _ in range(2):
            with urllib.request.urlopen("http://127.0.0.1:8000/api/evaluations?limit=1", timeout=5) as response:
                payload = json.load(response)
                assert payload["items"] == [] and payload["total"] == 0
                cookie = response.headers.get("Set-Cookie", "").lower()
                assert all(value in cookie for value in ("httponly", "secure", "samesite=lax", "path=/api/evaluations"))
        frontend_changed = True
        FRONTEND.rename(PREVIOUS)
        STAGED.rename(FRONTEND)
        replace(NGINX, (RELEASE / "nginx/multi-agent-arena.conf").read_text())
        reload_nginx()
        with urllib.request.urlopen("https://tomato-agent-arena.me/", timeout=10) as response:
            assert response.read() == (FRONTEND / "index.html").read_bytes()
        healthy()
        print("release_verified no_evaluation_post_sent", flush=True)
    except BaseException:
        print("release_failed restoring_application_only", flush=True)
        # Keep the API in maintenance while restoring the previous application.
        if nginx_changed:
            replace(NGINX, maintenance)
            reload_nginx()
        if frontend_changed and PREVIOUS.exists():
            if FRONTEND.exists():
                FRONTEND.rename(FAILED)
            PREVIOUS.rename(FRONTEND)
        if backend_changed:
            replace(COMPOSE, old_compose)
            run(["docker", "compose", "up", "-d", "--no-deps", "--no-build", "--pull", "never", "backend"])
            healthy()
        if nginx_changed:
            replace(NGINX, old_nginx)
            reload_nginx()
        print("application_restored schema_0002_retained", flush=True)
        raise


if __name__ == "__main__":
    main()