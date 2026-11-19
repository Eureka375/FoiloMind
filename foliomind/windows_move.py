"""Same-volume, no-overwrite Windows rename bound to verified object handles."""

import ctypes
import hashlib
import os
import stat
from contextlib import ExitStack, contextmanager
from ctypes import wintypes as w
from pathlib import Path

from .documents import MAX_BYTES, ensure_unlinked, identity, ordinary, verified_handle_path


class RenameInfo(ctypes.Structure):
    _fields_ = [("flags", w.DWORD), ("root", w.HANDLE), ("length", w.DWORD), ("filename", w.WCHAR * 1)]


class BasicInfo(ctypes.Structure):
    _fields_ = [("creation", ctypes.c_longlong), ("access", ctypes.c_longlong), ("write", ctypes.c_longlong),
                ("change", ctypes.c_longlong), ("attributes", w.DWORD)]


def kernel():
    if os.name != "nt":
        raise OSError("Windows required")
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = (w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE)
    api.CreateFileW.restype = w.HANDLE
    api.CloseHandle.argtypes = (w.HANDLE,)
    api.CloseHandle.restype = w.BOOL
    api.GetFileInformationByHandleEx.argtypes = (w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD)
    api.GetFileInformationByHandleEx.restype = w.BOOL
    api.GetFinalPathNameByHandleW.argtypes = (w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD)
    api.GetFinalPathNameByHandleW.restype = w.DWORD
    api.SetFileInformationByHandle.argtypes = (w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD)
    api.SetFileInformationByHandle.restype = w.BOOL
    api.GetDriveTypeW.argtypes = (w.LPCWSTR,)
    api.GetDriveTypeW.restype = w.UINT
    return api


def open_path(api, path, access, sharing, flags):
    handle = api.CreateFileW(str(path), access, sharing, None, 3, flags | 0x00200000, None)
    if handle in (None, ctypes.c_void_p(-1).value):
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


@contextmanager
def directory_handle(api, path):
    # Exclude other writers and delete/rename access while resolving the target.
    handle = open_path(api, path, 0x80, 1, 0x02000000)
    try:
        attrs = BasicInfo()
        if not api.GetFileInformationByHandleEx(handle, 0, ctypes.byref(attrs), ctypes.sizeof(attrs)):
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(32768)
        size = api.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if (not attrs.attributes & 0x10 or attrs.attributes & 0x400 or not size
                or size >= len(buffer) or Path(buffer.value.removeprefix("\\\\?\\")) != path):
            raise OSError("invalid directory handle")
        yield handle
    finally:
        api.CloseHandle(handle)


def pin_parents(api, stack, path, pinned, create_under=None):
    for part in (*reversed(path.parents), path):
        if part in pinned:
            continue
        if create_under is not None and part != create_under and part.is_relative_to(create_under):
            try:
                part.mkdir()
            except FileExistsError:
                pass
        pinned[part] = stack.enter_context(directory_handle(api, part))
    return pinned[path]


@contextmanager
def guarded_directory(path):
    if os.name != "nt":
        yield
        return
    with ExitStack() as stack:
        pin_parents(kernel(), stack, path, {})
        yield


def rename_verified(source, target, digest, file_identity, authorized_root, root_identity):
    import msvcrt

    api = kernel()
    if source.drive != target.drive or api.GetDriveTypeW(source.anchor) != 3:
        raise OSError("only local same-drive paths are supported")
    with ExitStack() as stack:
        pinned = {}
        # Hold destination and source ancestors against changes through the
        # no-replace rename, and name the source by its verified handle.
        root = authorized_root
        if not target.parent.is_relative_to(root):
            raise OSError("target outside plan root")
        pin_parents(api, stack, root, pinned)
        if identity(ensure_unlinked(root)) != root_identity:
            raise OSError("approved target root has changed")
        pin_parents(api, stack, target.parent, pinned, root)
        pin_parents(api, stack, source.parent, pinned)
        handle = open_path(api, source, 0x80010000, 1, 0)
        try:
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except Exception:
            api.CloseHandle(handle)
            raise
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or not ordinary(info) or info.st_nlink != 1
                    or identity(info) != file_identity or verified_handle_path(stream) != source):
                raise OSError("source object changed")
            data = stream.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES or hashlib.sha256(data).hexdigest() != digest:
                raise OSError("source contents changed")
            name = str(target).encode("utf-16-le")
            buffer = ctypes.create_string_buffer(ctypes.sizeof(RenameInfo) + len(name) + 2)
            info = RenameInfo.from_buffer(buffer)
            info.flags, info.root, info.length = 0, None, len(name)
            ctypes.memmove(ctypes.addressof(buffer) + RenameInfo.filename.offset, name, len(name))
            if not api.SetFileInformationByHandle(handle, 3, buffer, len(buffer)):
                raise ctypes.WinError(ctypes.get_last_error())
