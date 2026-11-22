# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import sys

from PyInstaller.utils.hooks import collect_data_files

# Conda puts shared runtime DLLs outside Python's usual DLL directory.
conda_bin = Path(sys.base_prefix) / "Library" / "bin"
runtime_names = ("tcl86t.dll", "tk86t.dll", "sqlite3.dll", "ffi.dll", "libmpdec-4.dll")
runtime_dlls = [(str(conda_bin / name), ".") for name in runtime_names if (conda_bin / name).is_file()]

a = Analysis(
    ["launch.pyw"],
    binaries=runtime_dlls,
    datas=collect_data_files("tkinterdnd2") + collect_data_files("jieba"),
    hiddenimports=["keyring.backends.Windows"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="FolioMind", console=False, upx=False)
dist = COLLECT(exe, a.binaries, a.datas, name="FolioMind", upx=False)
