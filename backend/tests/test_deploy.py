"""The Docker files cannot be built in the test run, so check what can go wrong without building: a wrong path, a stage compose asks for
that does not exist, a variable the app never reads, a template variable nothing defines, or the backend being published."""
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")
ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
BACKEND_SRC = "\n".join(p.read_text() for p in (ROOT / "backend" / "app").rglob("*.py"))


@pytest.fixture(scope="module")
def compose():
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text())


def stage(name: str) -> str:
    """The text of one Dockerfile stage."""
    parts = re.split(r"^FROM .* AS (\S+)\s*$", DOCKERFILE, flags=re.M)
    stages = dict(zip(parts[1::2], parts[2::2]))
    assert name in stages, f"no stage named {name!r}; there are {sorted(stages)}"
    return stages[name]


def test_there_is_one_dockerfile_at_the_root_and_compose_builds_its_two_targets(compose):
    assert not (ROOT / "backend" / "Dockerfile").exists() and not (ROOT / "frontend" / "Dockerfile").exists()
    assert set(compose["services"]) == {"backend", "frontend"}
    for name, svc in compose["services"].items():
        assert svc["build"]["context"] == "." and svc["build"].get("dockerfile", "Dockerfile") == "Dockerfile"
        stage(svc["build"]["target"])                                         # the stage compose asks for exists
        assert svc["build"]["target"] == name
    ignore = (ROOT / ".dockerignore").read_text()
    for must in (".env", "node_modules", "backend/data"):
        assert must in ignore, f".dockerignore must keep {must} out of the build"


def test_every_path_the_dockerfile_copies_exists():
    sources = []
    for line in DOCKERFILE.splitlines():
        m = re.match(r"^COPY\s+(?!--from)(.+)\s+\S+$", line)
        if m:
            sources += m.group(1).split()
    assert sources
    for src in sources:
        assert (ROOT / src).exists(), f"the Dockerfile copies {src}, which does not exist"
    assert (ROOT / "backend" / "requirements-ocr.txt").is_file() and (ROOT / "frontend" / "nginx.conf.template").is_file()


def test_only_the_web_app_is_published_and_it_waits_for_a_healthy_backend(compose):
    assert "ports" not in compose["services"]["backend"]                       # reachable only through the web app
    assert compose["services"]["frontend"]["ports"] == ["${WEB_PORT:-8080}:80"]
    assert compose["services"]["frontend"]["depends_on"]["backend"]["condition"] == "service_healthy"
    assert "/health" in str(compose["services"]["backend"]["healthcheck"]["test"])
    assert "pagewise-data:/data" in compose["services"]["backend"]["volumes"] and "pagewise-data" in compose["volumes"]


def test_container_paths_are_fixed_and_every_backend_variable_is_one_the_app_reads(compose):
    env = compose["services"]["backend"]["environment"]
    assert env["DATA_DIR"] == "/data" and env["MODELS_DIR"] == "/opt/models"     # literals, so a local .env cannot move them
    assert "DATA_DIR=/data" in stage("backend") and "MODELS_DIR=/opt/models" in stage("backend")
    for name in env:
        assert name in BACKEND_SRC, f"{name} is set in docker-compose.yml but nothing in the backend reads it"


def test_the_env_example_covers_what_compose_substitutes():
    wanted = set(re.findall(r"\$\{(\w+)(?::-[^}]*)?\}", (ROOT / "docker-compose.yml").read_text()))
    shown = {line.split("=")[0].lstrip("# ").strip() for line in (ROOT / ".env.example").read_text().splitlines() if "=" in line}
    assert wanted <= shown, f"missing from .env.example: {sorted(wanted - shown)}"


def test_the_web_server_template_only_uses_variables_the_image_defines():
    template = (ROOT / "frontend" / "nginx.conf.template").read_text()
    used = set(re.findall(r"\$\{(\w+)\}", template))
    assert used == {"BACKEND_URL", "APP_API_KEY"}
    for name in used:
        assert f"{name}=" in stage("frontend")                                    # a default, so nginx never starts with it unset
    assert "location /api/" in template and "try_files $uri /index.html" in template   # the API is proxied, the app's own routes fall back to it
    assert 'VITE_API_BASE_URL=""' in stage("web-build")                           # same-origin build
    assert "X-API-Key" in template and "client_max_body_size" in template


def test_the_backend_image_checks_every_engine_it_installs():
    from app.engines.ocr import local
    line = next(l for l in stage("backend").splitlines() if "app.engines.warmup" in l)
    named = line.split("app.engines.warmup")[1].split()
    assert named and all(local.get(n) is not None for n in named)
    ocr = (ROOT / "backend" / "requirements-ocr.txt").read_text()
    for pkg in ("rapidocr", "paddleocr", "doctr"):
        assert pkg in ocr
