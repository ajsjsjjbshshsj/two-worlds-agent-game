"""The Windows local demo must publish loopback ports and a read-only bundle."""

import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def test_demo_compose_is_loopback_only_and_mounts_demo_content_read_only():
    result = subprocess.run(
        ["docker", "compose", "-f", "compose.demo.yml", "config", "--format", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    config = json.loads(result.stdout)
    backend = config["services"]["backend"]
    frontend = config["services"]["frontend"]
    assert backend["environment"]["TWOWORLDS_MODE"] == "demo"
    assert backend["environment"]["TWOWORLDS_STORAGE_BACKEND"] == "sqlite"
    assert backend["environment"]["TWOWORLDS_AI_MODE"] == "demo"
    assert backend["environment"]["TWOWORLDS_EMAIL_MODE"] == "console"
    assert (
        backend["environment"]["TWOWORLDS_DEMO_PUBLICATION_ROOT"]
        == "/demo-content/releases"
    )
    assert any(
        port["published"] == "8000" and port["host_ip"] == "127.0.0.1"
        for port in backend["ports"]
    )
    assert any(
        port["published"] == "8080" and port["host_ip"] == "127.0.0.1"
        for port in frontend["ports"]
    )
    assert any(
        volume["type"] == "bind"
        and volume["source"].endswith(".local-demo-content")
        and volume["target"] == "/demo-content"
        and volume["read_only"] is True
        for volume in backend["volumes"]
    )
    assert frontend["build"]["args"]["VITE_DEMO_MODE"] == "true"
    assert frontend["build"]["args"]["VITE_API_BASE_URL"] == ""
    demo_nginx = (ROOT / "frontend/nginx.demo.conf").read_text("utf-8")
    assert "location /api/" in demo_nginx
    assert "proxy_pass http://backend:8000;" in demo_nginx
    assert "proxy_set_header Upgrade $http_upgrade;" in demo_nginx
    dockerfile = (ROOT / "frontend/Dockerfile").read_text("utf-8")
    assert 'if [ "$VITE_DEMO_MODE" = "true" ]' in dockerfile
    assert "cp /tmp/nginx.conf /etc/nginx/conf.d/default.conf" in dockerfile
