"""Windows desktop entry point."""

if __name__ == "__main__":
    try:
        from foliomind.desktop import main

        main()
    except Exception:
        from ctypes import windll

        windll.user32.MessageBoxW(
            None,
            "无法启动 FolioMind。请确认 Python 3.11 或更新版本已安装，且包含 Tcl/Tk。",
            "FolioMind 启动失败",
            0x10,
        )
        raise SystemExit(1) from None
