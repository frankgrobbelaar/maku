"""Keys Maku keeps for the owner, today the TMDB key.

They live in the data folder's `credentials.json`, never in the database, so no export or backup
carries them, and each is encrypted by Windows for the signed-in user (DPAPI): copied to another
PC or account, the file is useless. Maku then simply asks for the key again.
"""

import base64
import binascii
import ctypes
import json
import logging
import sys
from collections.abc import Mapping
from ctypes import wintypes
from typing import Literal, cast

from maku.config import DataPaths

log = logging.getLogger(__name__)

type Name = Literal["tmdb"]

FILE = "credentials.json"
_PURPOSE = "Maku"  # DPAPI's description of each secret


def load(paths: DataPaths, name: Name) -> str | None:
    """The stored key, or None when there's none or it can't be read here."""
    stored = _read(paths).get(name)
    if stored is None:
        return None
    try:
        return _unprotect(base64.b64decode(stored)).decode("utf-8")
    except (OSError, ValueError, binascii.Error) as error:
        log.warning("Maku couldn't read the stored %s key: %s", name, error)
        return None


def save(paths: DataPaths, name: Name, secret: str) -> None:
    stored = _read(paths)
    stored[name] = base64.b64encode(_protect(secret.encode("utf-8"))).decode("ascii")
    _write(paths, stored)


def forget(paths: DataPaths, name: Name) -> None:
    stored = _read(paths)
    if stored.pop(name, None) is not None:
        _write(paths, stored)


def _read(paths: DataPaths) -> dict[str, str]:
    try:
        answer: object = json.loads((paths.root / FILE).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}
    if not isinstance(answer, Mapping):
        return {}
    entries = cast("Mapping[object, object]", answer)
    return {k: v for k, v in entries.items() if isinstance(k, str) and isinstance(v, str)}


def _write(paths: DataPaths, stored: dict[str, str]) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    target = paths.root / FILE
    partial = target.with_name(f"{FILE}.partial")
    partial.write_text(json.dumps(stored, indent=2), encoding="utf-8")
    partial.replace(target)  # all or nothing


class _Blob(ctypes.Structure):
    _fields_ = (("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char)))


_UI_FORBIDDEN = 0x1  # CRYPTPROTECT_UI_FORBIDDEN: never ask anything on screen


def _protect(data: bytes) -> bytes:
    return _dpapi(data, protect=True)


def _unprotect(data: bytes) -> bytes:
    return _dpapi(data, protect=False)


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    if sys.platform != "win32":
        raise OSError("Keys can only be kept on Windows.")
    buffer = ctypes.create_string_buffer(data, len(data))
    source = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    result = _Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    call = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    description = _PURPOSE if protect else None
    worked = call(
        ctypes.byref(source), description, None, None, None, _UI_FORBIDDEN, ctypes.byref(result)
    )
    if not worked:
        raise OSError(ctypes.get_last_error(), "Windows couldn't protect or read the key")
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32.LocalFree(result.pbData)
