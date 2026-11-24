"""Opt-in isolated Compose acceptance using synthetic data, TCP and real MongoDB."""

import argparse
from hashlib import sha256
from ipaddress import ip_network
import json
import os
from pathlib import Path
import secrets
import subprocess
from tempfile import TemporaryDirectory
from uuid import uuid4

from tests.deployment_smoke import run
from tests.save_support import make_publications
from twoworlds.content.publication import PublicationStore

ROOT = Path(__file__).resolve().parents[2]
CONTAINER_CLIENT = Path(__file__).with_name("playtest_gateway_client.py")
DATABASE = "twoworlds_playtest_container"
ORGANIZER = """
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import subprocess
import sys

with TemporaryDirectory() as folder:
    root = Path(folder)
    aliases, journal = root / "approved.json", root / "accounts.jsonl"
    aliases.write_text('["fixture-a", "fixture-b"]')
    subprocess.run(
        [sys.executable, "-m", "twoworlds.provision_playtest_accounts", str(aliases), str(journal)],
        check=True, capture_output=True,
    )
    accounts = [json.loads(line) for line in journal.read_text().splitlines()]
    print(json.dumps([entry for entry in accounts if entry["result"] == "pending"]))
"""
DATABASE_PROBE = """
import os
from pathlib import Path
from pymongo import MongoClient
from pymongo.errors import OperationFailure
from twoworlds.playtest import _mongo_target

uri, name, anon = _mongo_target(os.environ)
with MongoClient(uri) as connection:
    status = connection[name].command("connectionStatus")["authInfo"]
    assert status["authenticatedUsers"] == [{"user": "playtest_app", "db": name}]
    assert status["authenticatedUserRoles"] == [{"role": "readWrite", "db": name}]
    assert connection[name].accounts.count_documents({"sessions": []}) == 2
    for forbidden in (connection["twoworlds"], connection["admin"]):
        try:
            forbidden.accounts.count_documents({})
        except OperationFailure as error:
            assert error.code == 13
        else:
            raise AssertionError("Application role reached another database")
with MongoClient(anon) as connection:
    try:
        connection[name].list_collection_names()
    except OperationFailure as error:
        assert error.code == 13
    else:
        raise AssertionError("Anonymous Mongo access succeeded")
assert not Path("/run/secrets/mongo-admin-password").exists()
try:
    Path("/srv/playtest/publications/should-not-exist").touch()
except OSError as error:
    assert error.errno == 30
else:
    raise AssertionError("Release mount accepted writes")
"""
SENTINEL = """
const fs = require("node:fs");
db.auth({
    user: "playtest_admin", mechanism: "SCRAM-SHA-256",
    pwd: fs.readFileSync("/run/secrets/mongo-admin-password", "utf8").trim(),
});
const sentinel = db.getSiblingDB("twoworlds_playtest_sentinel").checks;
if (process.env.SEED_SENTINEL === "yes") sentinel.insertOne({_id: "unchanged"});
if (sentinel.countDocuments({_id: "unchanged"}) !== 1) quit(1);
"""


def approval(root, purpose):
    records = {}
    for path in root.glob("*/*/release.json"):
        records[path.parent.relative_to(root).as_posix()] = sha256(
            path.read_bytes()
        ).hexdigest()
    return json.dumps({"purpose": purpose, "releases": records})


def fixture(root):
    tls, credentials = root / "tls", root / "secrets"
    tls.mkdir()
    tls.chmod(0o755)
    credentials.mkdir(mode=0o700)
    run(
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-sha256",
        "-noenc",
        "-days",
        "1",
        "-subj",
        "/CN=gateway",
        "-addext",
        "subjectAltName=DNS:gateway",
        "-keyout",
        str(tls / "privkey.pem"),
        "-out",
        str(tls / "fullchain.pem"),
    )
    secret_values = {}
    for name in ("mongo-admin-password", "mongo-app-password", "verification-secret"):
        secret_values[name] = secrets.token_hex(32)
        (credentials / name).write_text(secret_values[name] + "\n", encoding="ascii")
        # Disposable fixture files only, inside a host-owned private temp directory.
        (credentials / name).chmod(0o444)
    (tls / "privkey.pem").chmod(0o444)
    (tls / "fullchain.pem").chmod(0o444)
    _, publish = make_publications(root)
    publish()
    releases = root / "releases"
    for asset in (releases, *releases.rglob("*")):
        asset.chmod(0o755 if asset.is_dir() else 0o444)
    manifest = root / "approval.json"
    manifest.write_text(approval(releases, "internal-drill"), encoding="utf-8")
    manifest.chmod(0o444)
    empty = root / "empty"
    PublicationStore.initialize(empty)
    for path in (empty, *empty.iterdir()):
        path.chmod(0o755 if path.is_dir() else 0o444)
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("TWOWORLDS_", "MONGO_", "SMTP_", "COMPOSE_", "VITE_"))
    }
    env.update(
        TWOWORLDS_PLAYTEST_HOST="gateway",
        TWOWORLDS_PLAYTEST_ALLOWLIST="192.0.2.1",
        TWOWORLDS_PLAYTEST_TLS_DIR=str(tls),
        TWOWORLDS_PLAYTEST_SECRET_DIR=str(credentials),
        TWOWORLDS_PLAYTEST_PUBLICATION_ROOT=str(releases),
        TWOWORLDS_PLAYTEST_APPROVAL_FILE=str(manifest),
        TWOWORLDS_PLAYTEST_MONGO_DATABASE=DATABASE,
        TWOWORLDS_PLAYTEST_CONTENT_PURPOSE="internal-drill",
        MONGO_URI="mongodb://production.invalid",
        TWOWORLDS_AI_API_KEY="inherited-provider-marker",
        SMTP_PASSWORD="inherited-smtp-marker",
    )
    return env, list(secret_values.values()) + [
        env["TWOWORLDS_AI_API_KEY"],
        env["SMTP_PASSWORD"],
    ]


def report(message):
    print("PASS " + message, flush=True)


def safe_failure(command, message, markers=()):
    try:
        command()
    except subprocess.CalledProcessError as error:
        output = error.stdout + error.stderr
        assert message.encode() in output, f"Missing refusal diagnosis: {message}"
        assert all(marker.encode() not in output for marker in markers)
    else:
        raise AssertionError("Unsafe configuration or operation unexpectedly succeeded")


def exercise(compose, project, root, env, markers, ingress_subnet):
    concrete = json.loads(compose("config", "--format", "json").stdout)
    for name, service in concrete["services"].items():
        assert service["read_only"] and service["cap_drop"] == ["ALL"]
        assert ("ports" in service) == (name == "gateway")
        assert "mongodb://" not in json.dumps(
            service["environment"] if "environment" in service else {}
        )
    assert concrete["services"]["gateway"]["ports"][0]["host_ip"] == "127.0.0.1"
    assert (
        concrete["networks"]["app"]["internal"]
        and concrete["networks"]["data"]["internal"]
    )
    unset = env | {"TWOWORLDS_PLAYTEST_ALLOWLIST": ""}
    safe_failure(
        lambda: compose("config", "--quiet", custom_env=unset),
        "set approved IPv4 source addresses",
    )
    report("Compose closed defaults, private port scope and explicit allowlist")

    compose("up", "-d", "--wait", "--wait-timeout", "90", "backend", "frontend")
    compose(
        "exec",
        "-T",
        "-e",
        "SEED_SENTINEL=yes",
        "playtest-mongo",
        "mongosh",
        "--quiet",
        "admin",
        "--eval",
        SENTINEL,
    )
    accounts = json.loads(
        compose("exec", "-T", "backend", "python", "-c", ORGANIZER).stdout
    )
    markers.extend(item["password"] for item in accounts)
    compose("exec", "-T", "backend", "python", "-c", DATABASE_PROBE)
    report(
        "Real MongoDB SCRAM, no anonymous or cross-database access, CLI and read-only publications"
    )

    for name in ("backend", "frontend", "playtest-mongo"):
        assert int(compose("exec", "-T", name, "id", "-u").stdout) > 0
    allowed, denied = [str(ingress_subnet[-index]) for index in (11, 12)]
    env["TWOWORLDS_PLAYTEST_ALLOWLIST"] = allowed
    compose("up", "-d", "--wait", "--wait-timeout", "60", "gateway")
    assert int(compose("exec", "-T", "gateway", "id", "-u").stdout) > 0
    backend_image = image(compose, "backend")
    gateway_image = image(compose, "gateway")

    def client(action, ip, payload):
        return run(
            "docker",
            "run",
            "--rm",
            "-i",
            "--network",
            project + "_ingress",
            "--ip",
            ip,
            "--mount",
            f"type=bind,source={root / 'tls/fullchain.pem'},target=/trust.pem,readonly",
            backend_image,
            "python",
            "-c",
            CONTAINER_CLIENT.read_text(),
            action,
            input=json.dumps(payload).encode(),
            timeout=55,
        )

    endpoints = []
    for service, network, port in (
        ("backend", "app", 8000),
        ("frontend", "app", 8080),
        ("playtest-mongo", "data", 27017),
    ):
        container_id = compose("ps", "-q", service).stdout.decode().strip()
        ip = (
            run(
                "docker",
                "inspect",
                "--format",
                '{{(index .NetworkSettings.Networks "'
                + project
                + f'_{network}").IPAddress}}}}}}',
                container_id,
            )
            .stdout.decode()
            .strip()
        )
        endpoints.append([ip, port])
    logged = json.loads(
        client(
            "allowed", allowed, {"accounts": accounts, "internal_endpoints": endpoints}
        ).stdout
    )
    client("denied", denied, logged | {"allowed": allowed})
    markers.extend([logged["cookie"].removeprefix("tw_session="), logged["invite"]])
    report(
        "TLS 1.2/1.3, plaintext exclusion, HTTPS and WSS, direct IP ACL and media role privacy"
    )

    empty_env = env | {"TWOWORLDS_PLAYTEST_PUBLICATION_ROOT": str(root / "empty")}
    participant_env = env | {"TWOWORLDS_PLAYTEST_CONTENT_PURPOSE": "participant"}
    bad_approval = root / "bad-approval.json"
    bad_approval.write_text(
        '{"purpose":"internal-drill","releases":{}}', encoding="utf-8"
    )
    bad_approval.chmod(0o444)
    for invalid_env in (
        empty_env,
        participant_env,
        env | {"TWOWORLDS_PLAYTEST_APPROVAL_FILE": str(bad_approval)},
    ):
        safe_failure(
            lambda: compose(
                "run", "--no-deps", "--rm", "-T", "backend", custom_env=invalid_env
            ),
            "Playtest deployment requires a nonempty, approved release catalog",
            markers,
        )

    bad_tls = root / "bad-tls"
    bad_tls.mkdir()
    bad_tls.chmod(0o755)
    private_key = bad_tls / "privkey.pem"
    private_key.write_bytes((root / "tls/privkey.pem").read_bytes())
    private_key.chmod(0o444)
    invalid_cert = bad_tls / "fullchain.pem"
    for case in (
        "missing-certificate",
        "invalid-certificate",
        "invalid-allowlist",
        "public-drill",
    ):
        if case == "invalid-certificate":
            invalid_cert.write_text("invalid PEM", encoding="utf-8")
            invalid_cert.chmod(0o444)
        allowlist = "0.0.0.0/0" if case == "invalid-allowlist" else allowed
        mount = (
            root / "tls" if case in {"invalid-allowlist", "public-drill"} else bad_tls
        )
        bind = "192.0.2.7" if case == "public-drill" else "127.0.0.1"
        error_message = {
            "invalid-allowlist": "explicit list of IPv4",
            "public-drill": "Internal Playtest drills must bind to loopback",
        }.get(case, "TLS or gateway configuration is invalid")
        safe_failure(
            lambda: run(
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "-e",
                "TWOWORLDS_PLAYTEST_HOST=gateway",
                "-e",
                "TWOWORLDS_PLAYTEST_ALLOWLIST=" + allowlist,
                "-e",
                "TWOWORLDS_PLAYTEST_BIND_IP=" + bind,
                "-e",
                "TWOWORLDS_PLAYTEST_CONTENT_PURPOSE=internal-drill",
                "--mount",
                f"type=bind,source={mount},target=/etc/twoworlds-tls,readonly",
                "--tmpfs",
                "/tmp:uid=101,gid=101,mode=0700",
                gateway_image,
                timeout=10,
            ),
            error_message,
        )
    report("Fail-closed missing or unapproved releases, TLS and unsafe allowlist")

    logs = compose("logs", "--no-color").stdout
    assert all(marker.encode() not in logs for marker in markers)
    assert all(
        marker.encode() not in json.dumps(concrete).encode() for marker in markers
    )
    bundle = compose(
        "exec", "-T", "frontend", "tar", "cf", "-", "-C", "/usr/share/nginx/html", "."
    ).stdout
    assert all(marker.encode() not in bundle for marker in markers)
    report("Deployment config, images and logs exclude fixture secrets")

    def maintenance(confirmation=""):
        result = compose(
            "exec",
            "-T",
            "-e",
            "PLAYTEST_CONFIRM=" + confirmation,
            "playtest-mongo",
            "mongosh",
            "--quiet",
            "--nodb",
            "--file",
            "/opt/playtest/maintenance.js",
        )
        return json.loads(result.stdout)

    compose("stop", "gateway", "frontend", "backend")
    client("closed", allowed, {})
    before = maintenance()
    assert before["result"] == "dry-run" and before["accountsWithSessions"] == 2
    assert before["aliases"] == [
        "fixture-a@playtest.invalid",
        "fixture-b@playtest.invalid",
    ]
    for unsafe in ("DROP:twoworlds", "DROP:" + DATABASE):
        safe_failure(lambda: maintenance(unsafe), "maintenance refused", markers)
    assert maintenance() == before
    revoked = maintenance("REVOKE:" + DATABASE)
    assert revoked["result"] == "revoked" and revoked["accountsWithSessions"] == 0
    compose("up", "-d", "--wait", "--wait-timeout", "60", "gateway")
    client("revoked", allowed, logged)
    compose("stop", "gateway", "frontend", "backend")
    assert maintenance("DROP:" + DATABASE)["result"] == "dropped"
    assert maintenance()["aliases"] == []
    compose(
        "exec",
        "-T",
        "playtest-mongo",
        "mongosh",
        "--quiet",
        "admin",
        "--eval",
        SENTINEL,
    )
    compose("down")
    volume = project + "_mongo_data"
    assert (
        run(
            "docker",
            "volume",
            "inspect",
            volume,
            "--format",
            '{{index .Labels "com.docker.compose.project"}}',
        )
        .stdout.decode()
        .strip()
        == project
    )
    run("docker", "volume", "rm", volume)
    report(
        "Dry-run, explicit revoke and drop, old-cookie denial, peer DB intact and volume removed"
    )


def image(compose, service):
    container = compose("ps", "-q", service).stdout.decode().strip()
    return (
        run("docker", "inspect", "--format", "{{.Image}}", container)
        .stdout.decode()
        .strip()
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prebuilt", nargs=4, metavar=("BACKEND", "FRONTEND", "GATEWAY", "MONGO")
    )
    args = parser.parse_args()
    with TemporaryDirectory(prefix="tw-playtest-compose-") as folder:
        root = Path(folder)
        env, markers = fixture(root)
        project = "tw-playtest-ci-" + uuid4().hex[:10]
        segment = secrets.randbelow(235) + 10
        ingress_subnet = ip_network(f"10.214.{segment}.0/24")
        env.update(
            TWOWORLDS_PLAYTEST_APP_SUBNET=f"10.213.{segment}.0/24",
            TWOWORLDS_PLAYTEST_APP_RANGE=f"10.213.{segment}.128/25",
            TWOWORLDS_PLAYTEST_GATEWAY_IP=f"10.213.{segment}.2",
        )
        # Replacement keeps CI isolated and avoids colliding with a workstation's port 443.
        overlay = root / "test-compose.yml"
        overlay.write_text(
            "services:\n  gateway:\n    ports: !override\n"
            "      - {target: 8443, published: '0', host_ip: 127.0.0.1}\n"
            f"networks:\n  ingress:\n    ipam:\n      config: [{{subnet: {ingress_subnet}}}]\n",
            encoding="utf-8",
        )
        files = ["-f", str(ROOT / "compose.playtest.yml"), "-f", str(overlay)]
        if args.prebuilt:
            images = root / "images.json"
            names = ("backend", "frontend", "gateway", "playtest-mongo")
            images.write_text(
                json.dumps(
                    {
                        "services": {
                            name: {"image": tag}
                            for name, tag in zip(names, args.prebuilt, strict=True)
                        }
                    }
                ),
                encoding="utf-8",
            )
            files.extend(("-f", str(images)))

        def compose(*command, custom_env=None):
            return run(
                "docker",
                "compose",
                "--env-file",
                os.devnull,
                "-p",
                project,
                *files,
                *command,
                env=env if custom_env is None else custom_env,
                timeout=450,
            )

        try:
            if not args.prebuilt:
                compose("build")
            exercise(compose, project, root, env, markers, ingress_subnet)
        except subprocess.CalledProcessError as error:
            diagnostic = (error.stderr or b"").decode(errors="replace")
            diagnostic += compose("logs", "--no-color", "--tail", "10").stdout.decode(
                errors="replace"
            )
            for secret in markers:
                diagnostic = diagnostic.replace(secret, "[redacted]")
            raise SystemExit(diagnostic) from None
        finally:
            # This random CI project owns only test fixtures.
            compose("down", "--volumes", "--remove-orphans")


if __name__ == "__main__":
    main()
