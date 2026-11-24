"""Local organizer CLI for approved Playtest aliases and a private credential journal."""

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from uuid import uuid4

from twoworlds.application.identity import IdentityError, IdentityService
from twoworlds.playtest import PlaytestConfigurationError, open_playtest_repository

_ALIAS = re.compile(r"[a-z][a-z0-9-]{0,31}")
_ALIASES_MAX_BYTES = 16 * 1024


class ProvisioningError(ValueError):
    """Fixed operator guidance without paths, input data or credentials."""


def _read_aliases(path):
    try:
        with Path(path).open("rb") as source:
            raw = source.read(_ALIASES_MAX_BYTES + 1)
        if len(raw) > _ALIASES_MAX_BYTES:
            raise ValueError
        aliases = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        raise ProvisioningError("Cannot read a bounded UTF-8 JSON alias list") from None
    if not isinstance(aliases, list) or not aliases:
        raise ProvisioningError("The input must be a non-empty JSON array of aliases")
    if any(
        not isinstance(alias, str) or not _ALIAS.fullmatch(alias) for alias in aliases
    ):
        raise ProvisioningError("Every alias must match [a-z][a-z0-9-]{0,31}")
    if len(set(aliases)) != len(aliases):
        raise ProvisioningError("The alias list contains duplicates")
    return aliases


def _entry_exists(directory, name):
    try:
        os.stat(name, dir_fd=directory, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _inside_git(directory, flags):
    try:
        metadata = os.stat(".git", dir_fd=directory, follow_symlinks=False)
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISDIR(metadata.st_mode):
            return True  # Includes linked worktrees with a .git file.
        git = os.open(".git", flags, dir_fd=directory)
        try:
            if _entry_exists(git, "HEAD"):
                return True
        finally:
            os.close(git)
    return all(_entry_exists(directory, name) for name in ("HEAD", "objects", "refs"))


@contextmanager
def _output_directory(path):
    if (
        os.name != "posix"
        or not hasattr(os, "O_NOFOLLOW")
        or not hasattr(os, "O_DIRECTORY")
        or os.open not in os.supports_dir_fd
    ):
        raise ProvisioningError(
            "Credential delivery requires POSIX no-follow file protection"
        )
    path = Path(path)
    if not path.is_absolute():
        path = Path.cwd() / path
    if not path.name or ".." in path.parts:
        raise ProvisioningError(
            "Choose a credential file path without parent traversal"
        )
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    directory = os.open(path.anchor, flags)
    try:
        # Walk by directory descriptors to prevent symlink traversal, including
        # symlinks in ancestor directories. Check each ancestor for Git metadata.
        for component in (*path.parts[1:-1], None):
            if _inside_git(directory, flags):
                raise ProvisioningError(
                    "Credential files must be outside Git repositories"
                )
            if component is not None:
                child = os.open(component, flags, dir_fd=directory)
                os.close(directory)
                directory = child
        owner = os.fstat(directory)
        if owner.st_uid != os.geteuid() or stat.S_IMODE(owner.st_mode) != 0o700:
            raise ProvisioningError(
                "Use an owner-only credential directory with mode 0700"
            )
        if _entry_exists(directory, path.name):
            raise ProvisioningError("The credential file already exists")
        yield directory, path.name
    finally:
        os.close(directory)


def _entry(batch, result, alias=None):
    record = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "batch_id": batch,
        "result": result,
    }
    if alias is not None:
        record["alias"] = alias
    return record


def _write(journal, record):
    journal.write(json.dumps(record) + "\n")
    journal.flush()
    os.fsync(journal.fileno())


def _audit(record):
    print(json.dumps(record), flush=True)


def _provision(repository, aliases, directory, filename):
    accounts = [(alias, f"{alias}@playtest.invalid") for alias in aliases]
    # Check the entire input before writing credentials or accounts. MongoDB's
    # unique index still handles a concurrent insert after this preflight.
    if any(repository.get_account_by_email(email) is not None for _, email in accounts):
        raise ProvisioningError(
            "An alias already has an account. No accounts were created by this batch"
        )

    identity = IdentityService(repository)
    batch = uuid4().hex
    fd = os.open(
        filename,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory,
    )
    with os.fdopen(fd, "w", encoding="utf-8") as journal:
        os.fchmod(journal.fileno(), 0o600)
        os.fsync(directory)
        for alias, email in accounts:
            password = secrets.token_urlsafe(32)
            # Make the only recoverable password durable before attempting the
            # insert. A crash may leave a pending record, but no lost password.
            _write(
                journal,
                _entry(batch, "pending", alias)
                | {"email": email, "password": password},
            )
            try:
                identity.provision_account(email, password, alias)
            except IdentityError as error:
                result = (
                    "conflict"
                    if error.code == "EMAIL_ALREADY_REGISTERED"
                    else "unknown"
                )
            except Exception:
                result = "unknown"
            else:
                result = "created"
            audit = _entry(batch, result, alias)
            _write(journal, audit)
            _audit(audit)
            if result != "created":
                raise ProvisioningError(
                    "Batch stopped. Keep the private journal and review its results"
                )
        done = _entry(batch, "complete")
        _write(journal, done)
        _audit(done)


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse can otherwise echo arbitrary command line data on a typo.
        self.exit(
            2,
            "Invalid arguments. Provide an alias JSON file and a private credential file path.\n",
        )


def main(argv=None) -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument("aliases", help="UTF-8 JSON array of approved aliases")
    parser.add_argument("credentials", help="new file in a 0700 directory outside Git")
    args = parser.parse_args(argv)
    try:
        aliases = _read_aliases(args.aliases)
        with _output_directory(args.credentials) as (directory, filename):
            with closing(open_playtest_repository()) as repository:
                _provision(repository, aliases, directory, filename)
    except (ProvisioningError, PlaytestConfigurationError) as error:
        print(str(error), file=sys.stderr)
        return 1
    except (Exception, KeyboardInterrupt):
        print(
            "Provisioning stopped. Check configuration and retain any private journal.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
