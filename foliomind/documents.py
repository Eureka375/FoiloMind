"""Read-only extraction with source locators and explicit coverage."""

import hashlib
import io
import os
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path


FORMATS = {".txt", ".md", ".docx", ".pdf"}
MAX_BYTES = 16 * 1024 * 1024
MAX_EXPANDED_DOCX = 48 * 1024 * 1024
MAX_CHARACTERS = 300_000
MAX_PDF_PAGES = 150
REPARSE_POINT = 0x400


@dataclass(frozen=True)
class Segment:
    locator: dict[str, int]
    text: str

    @property
    def label(self) -> str:
        loc = self.locator
        if "table" in loc:
            return f"表 {loc['table']} 第 {loc['row']} 行第 {loc['column']} 列"
        if "page" in loc:
            return f"第 {loc['page']} 页"
        if "paragraph" in loc:
            return f"第 {loc['paragraph']} 段"
        return f"第 {loc['line']} 行"


@dataclass(frozen=True)
class Extracted:
    path: Path
    status: str
    detail: str
    digest: str = ""
    identity: str = ""
    segments: tuple[Segment, ...] = ()


def identity(info: os.stat_result) -> str:
    return f"{info.st_dev}:{info.st_ino}"


def ordinary(info: os.stat_result) -> bool:
    return not stat.S_ISLNK(info.st_mode) and not (
        getattr(info, "st_file_attributes", 0) & REPARSE_POINT
    )


def ensure_unlinked(path: Path) -> os.stat_result:
    for parent in reversed(path.parents):
        if not ordinary(parent.lstat()):
            raise OSError("linked parent")
    info = path.lstat()
    if not ordinary(info):
        raise OSError("linked source")
    return info


def verified_handle_path(stream) -> Path:
    if os.name != "nt":
        return Path(f"/proc/self/fd/{stream.fileno()}").resolve(strict=True)
    import ctypes
    from ctypes import wintypes
    from msvcrt import get_osfhandle

    get_path = ctypes.WinDLL("kernel32", use_last_error=True).GetFinalPathNameByHandleW
    get_path.argtypes = (wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD)
    get_path.restype = wintypes.DWORD
    buf = ctypes.create_unicode_buffer(32768)
    size = get_path(get_osfhandle(stream.fileno()), buf, len(buf), 0)
    if not size or size >= len(buf):
        raise OSError("cannot verify open path")
    return Path(buf.value.removeprefix("\\\\?\\"))


def read_document(path: Path, *, expected_identity: str | None = None) -> tuple[bytes, str]:
    before = ensure_unlinked(path)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise OSError("not a regular single-link file")
    if expected_identity is not None and identity(before) != expected_identity:
        raise OSError("file identity changed")
    if before.st_size > MAX_BYTES:
        raise OverflowError
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if identity(before) != identity(opened) or opened.st_nlink != 1:
            raise OSError("file changed before open")
        if verified_handle_path(stream) != path:
            raise OSError("file is outside its authorized path")
        data = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
        if len(data) > MAX_BYTES:
            raise OverflowError
        if opened.st_mtime_ns != after.st_mtime_ns or opened.st_size != len(data):
            raise OSError("file changed during read")
    return data, identity(opened)


def text_segments(data: bytes):
    text = data.decode("utf-8-sig")
    if any(ord(c) < 32 and c not in "\t\r\n" for c in text):
        raise ValueError("binary data")
    return (Segment({"line": i}, line) for i, line in enumerate(text.splitlines(), 1))


def docx_segments(data: bytes):
    from docx import Document
    from docx.table import Table

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sum(member.file_size for member in archive.infolist()) > MAX_EXPANDED_DOCX:
            raise OverflowError
    paragraph = table = 0
    for block in Document(io.BytesIO(data)).iter_inner_content():
        if isinstance(block, Table):
            table += 1
            seen = set()
            for row_no, row in enumerate(block.rows, 1):
                for column_no, cell in enumerate(row.cells, 1):
                    if cell._tc not in seen:
                        seen.add(cell._tc)
                        yield Segment({"table": table, "row": row_no, "column": column_no}, cell.text)
        else:
            paragraph += 1
            yield Segment({"paragraph": paragraph}, block.text)


def pdf_segments(data: bytes):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        return (), "PDF 已加密"
    segments = []
    unreadable, failed = [], []
    pages = len(reader.pages)
    remaining = MAX_CHARACTERS
    for index in range(min(pages, MAX_PDF_PAGES)):
        try:
            page = reader.pages[index]
            text = page.extract_text().strip()
        except Exception:
            failed.append(str(index + 1))
            continue
        if text:
            segments.append(Segment({"page": index + 1}, text[:remaining]))
            if len(text) >= remaining and (len(text) > remaining or index + 1 < pages):
                return segments, "PDF 文字提取达到字符上限"
            remaining -= len(text)
        else:
            unreadable.append(str(index + 1))
    notes = []
    if unreadable:
        notes.append("以下页无可提取文字：" + "、".join(unreadable))
    if failed:
        if not segments and not unreadable:
            raise ValueError("PDF page extraction failed")
        notes.append("以下页解析失败：" + "、".join(failed))
    if pages > MAX_PDF_PAGES:
        notes.append(f"仅处理前 {MAX_PDF_PAGES} / {pages} 页")
    return segments, "；".join(notes)


def extract(path: Path, *, expected_identity: str | None = None) -> Extracted:
    path = path.absolute()
    extension = path.suffix.lower()
    if extension not in FORMATS:
        return Extracted(path, "UNSUPPORTED", "首版不提取此格式")
    try:
        data, file_identity = read_document(path, expected_identity=expected_identity)
    except OverflowError:
        return Extracted(path, "FAILED", "文档超过读取上限")
    except OSError:
        return Extracted(path, "FAILED", "文件不可读、已变化或路径无法验证")
    digest = hashlib.sha256(data).hexdigest()
    notes = ""
    try:
        if extension == ".pdf":
            incoming, notes = pdf_segments(data)
            if notes == "PDF 已加密":
                return Extracted(path, "FAILED", notes, digest, file_identity)
        elif extension == ".docx":
            incoming = docx_segments(data)
        else:
            incoming = text_segments(data)
        result = []
        remaining = MAX_CHARACTERS
        for segment in incoming:
            if not segment.text.strip():
                continue
            if len(segment.text) > remaining:
                if remaining:
                    result.append(Segment(segment.locator, segment.text[:remaining]))
                notes = "仅保留字符上限以内的正文"
                break
            result.append(segment)
            remaining -= len(segment.text)
    except ImportError:
        return Extracted(path, "FAILED", "缺少格式解析依赖，请安装 requirements.txt", digest, file_identity)
    except OverflowError:
        return Extracted(path, "FAILED", "解包后的正文超过处理上限", digest, file_identity)
    except Exception:
        return Extracted(path, "FAILED", "文件损坏或正文无法解码", digest, file_identity)
    status = ("PARTIAL" if notes else "EXTRACTED") if result else "EMPTY"
    detail = notes or ("正文已读取" if result else "无可提取正文")
    if extension == ".pdf":
        detail += "。仅提取已有文字层，不识别图像。"
    return Extracted(path, status, detail, digest, file_identity, tuple(result))
