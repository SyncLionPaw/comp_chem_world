"""Fail-closed Landlock filesystem sandbox for the untrusted task 90 child."""
from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path
import stat

SYS_LANDLOCK_CREATE_RULESET = 444
SYS_LANDLOCK_ADD_RULE = 445
SYS_LANDLOCK_RESTRICT_SELF = 446
LANDLOCK_CREATE_RULESET_VERSION = 1
LANDLOCK_RULE_PATH_BENEATH = 1

LANDLOCK_ACCESS_FS_EXECUTE = 1 << 0
LANDLOCK_ACCESS_FS_WRITE_FILE = 1 << 1
LANDLOCK_ACCESS_FS_READ_FILE = 1 << 2
LANDLOCK_ACCESS_FS_READ_DIR = 1 << 3
LANDLOCK_ACCESS_FS_REMOVE_DIR = 1 << 4
LANDLOCK_ACCESS_FS_REMOVE_FILE = 1 << 5
LANDLOCK_ACCESS_FS_MAKE_CHAR = 1 << 6
LANDLOCK_ACCESS_FS_MAKE_DIR = 1 << 7
LANDLOCK_ACCESS_FS_MAKE_REG = 1 << 8
LANDLOCK_ACCESS_FS_MAKE_SOCK = 1 << 9
LANDLOCK_ACCESS_FS_MAKE_FIFO = 1 << 10
LANDLOCK_ACCESS_FS_MAKE_BLOCK = 1 << 11
LANDLOCK_ACCESS_FS_MAKE_SYM = 1 << 12
LANDLOCK_ACCESS_FS_REFER = 1 << 13
LANDLOCK_ACCESS_FS_TRUNCATE = 1 << 14

_HANDLED_FS = (1 << 15) - 1
_READ_ONLY_DIR = LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR
_READ_WRITE_WORKSPACE = (
    LANDLOCK_ACCESS_FS_WRITE_FILE
    | LANDLOCK_ACCESS_FS_READ_FILE
    | LANDLOCK_ACCESS_FS_READ_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_DIR
    | LANDLOCK_ACCESS_FS_REMOVE_FILE
    | LANDLOCK_ACCESS_FS_MAKE_DIR
    | LANDLOCK_ACCESS_FS_MAKE_REG
    | LANDLOCK_ACCESS_FS_REFER
    | LANDLOCK_ACCESS_FS_TRUNCATE
)


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64)]


class _PathBeneathAttr(ctypes.Structure):
    _fields_ = [
        ("allowed_access", ctypes.c_uint64),
        ("parent_fd", ctypes.c_int32),
        ("reserved", ctypes.c_uint32),
    ]


def _libc():
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    return libc


def _syscall(libc, number: int, *arguments: object, operation: str) -> int:
    ctypes.set_errno(0)
    result = int(libc.syscall(ctypes.c_long(number), *arguments))
    if result < 0:
        error = ctypes.get_errno()
        if error == 0:
            error = errno.EIO
        raise OSError(error, f"{operation}: {os.strerror(error)}")
    return result


def landlock_abi_version() -> int:
    """Return the kernel Landlock ABI or raise; unsupported hosts fail closed."""
    libc = _libc()
    ctypes.set_errno(0)
    result = int(libc.syscall(
        ctypes.c_long(SYS_LANDLOCK_CREATE_RULESET),
        ctypes.c_void_p(0),
        ctypes.c_size_t(0),
        ctypes.c_uint32(LANDLOCK_CREATE_RULESET_VERSION),
    ))
    if result < 0:
        error = ctypes.get_errno() or errno.EIO
        raise OSError(error, f"Landlock ABI query failed: {os.strerror(error)}")
    return result


def _resolved_directory(path: str) -> Path | None:
    candidate = Path(path)
    if not candidate.exists():
        return None
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise OSError(errno.ENOTDIR, f"Landlock runtime allowlist entry is not a directory: {path}")
    return resolved


def _open_path(path: Path) -> int:
    path_flag = getattr(os, "O_PATH", None)
    if path_flag is None:
        raise OSError(errno.EOPNOTSUPP, "O_PATH is unavailable; refusing an incomplete Landlock policy")
    return os.open(path, path_flag | os.O_CLOEXEC)


def _add_path_rule(libc, ruleset_fd: int, path: Path, allowed_access: int) -> None:
    parent_fd = _open_path(path)
    try:
        attr = _PathBeneathAttr(allowed_access=allowed_access, parent_fd=parent_fd, reserved=0)
        _syscall(
            libc,
            SYS_LANDLOCK_ADD_RULE,
            ctypes.c_int(ruleset_fd),
            ctypes.c_int(LANDLOCK_RULE_PATH_BENEATH),
            ctypes.byref(attr),
            ctypes.c_uint32(0),
            operation=f"Landlock add_rule({path})",
        )
    finally:
        os.close(parent_fd)


def _add_runtime_directory_rules(libc, ruleset_fd: int) -> None:
    usr = _resolved_directory("/usr")
    if usr is None:
        raise OSError(errno.ENOENT, "required runtime directory /usr is missing")
    _add_path_rule(libc, ruleset_fd, usr, _READ_ONLY_DIR)

    runtime_paths = {usr}
    for name in ("/lib", "/lib64", "/bin"):
        resolved = _resolved_directory(name)
        if resolved is None or resolved in runtime_paths:
            continue
        if usr in resolved.parents:
            continue
        runtime_paths.add(resolved)
        _add_path_rule(libc, ruleset_fd, resolved, _READ_ONLY_DIR)

    etc = _resolved_directory("/etc")
    if etc is None:
        raise OSError(errno.ENOENT, "required runtime directory /etc is missing")
    _add_path_rule(libc, ruleset_fd, etc, LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR)


def _add_device_rule(libc, ruleset_fd: int, name: str, allowed_access: int) -> None:
    path = Path(name).resolve(strict=True)
    info = path.stat()
    if not stat.S_ISCHR(info.st_mode):
        raise OSError(errno.ENODEV, f"required character device is missing: {name}")
    _add_path_rule(libc, ruleset_fd, path, allowed_access)


def apply_landlock(workspace: str | os.PathLike[str]) -> int:
    """Restrict the current child to runtime reads and one private RW workspace."""
    workspace_path = Path(workspace).resolve(strict=True)
    if not workspace_path.is_dir():
        raise OSError(errno.ENOTDIR, "Landlock workspace must be a directory")
    if workspace_path in {
        Path("/"), Path("/tmp"), Path("/app"), Path("/tests"),
        Path("/solution"), Path("/logs"), Path("/usr"),
    }:
        raise OSError(errno.EPERM, f"refusing broad Landlock workspace: {workspace_path}")

    abi = landlock_abi_version()
    if abi < 3:
        raise OSError(errno.EOPNOTSUPP, f"Landlock ABI {abi} lacks required truncate mediation")

    libc = _libc()
    ruleset_attr = _RulesetAttr(handled_access_fs=_HANDLED_FS)
    ruleset_fd = _syscall(
        libc,
        SYS_LANDLOCK_CREATE_RULESET,
        ctypes.byref(ruleset_attr),
        ctypes.c_size_t(ctypes.sizeof(ruleset_attr)),
        ctypes.c_uint32(0),
        operation="Landlock create_ruleset",
    )
    try:
        _add_runtime_directory_rules(libc, ruleset_fd)
        _add_device_rule(
            libc,
            ruleset_fd,
            "/dev/null",
            LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_WRITE_FILE,
        )
        _add_device_rule(libc, ruleset_fd, "/dev/urandom", LANDLOCK_ACCESS_FS_READ_FILE)
        _add_path_rule(libc, ruleset_fd, workspace_path, _READ_WRITE_WORKSPACE)
        _syscall(
            libc,
            SYS_LANDLOCK_RESTRICT_SELF,
            ctypes.c_int(ruleset_fd),
            ctypes.c_uint32(0),
            operation="Landlock restrict_self",
        )
    finally:
        os.close(ruleset_fd)
    return abi
