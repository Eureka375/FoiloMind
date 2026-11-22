"""Offline discovery of reviewable groups from an explicitly selected folder."""

import logging
import re
from collections import Counter
from pathlib import Path
from uuid import uuid4

from .analysis import Analysis, Evidence, Proposal
from .library import CatalogError, Source, absolute, path_key


MAX_DOCUMENTS = 500
MAX_SEGMENTS = 10
SEGMENT_CHARS = 600
MIN_SIMILARITY = 0.04
TOKEN_RUNS = re.compile(r"[\u3400-\u9fff]+|[a-z][a-z0-9+#]*", re.IGNORECASE)
STOP_TERMS = frozenset(
    "and the for with from this that each into are its then when "
    "可以 需要 使用 如果 以及 用户 进行 内容 通过 根据 当前 同时 分别 结果 "
    "记录 检查 对比 一次 对应 确认 校验 是否 观察 考虑 检查后 所有 需要 两个 "
    "一条 第一次 最后 当前 这样 那些 一个 里面 正常 单独 实际 之后 已经".split()
)


def terms(text, widths=(2,)):
    for match in TOKEN_RUNS.finditer(text.casefold()):
        token = match.group()
        if token.isascii():
            if len(token) > 1 and token not in STOP_TERMS:
                yield token
        else:
            for width in widths:
                for index in range(len(token) - width + 1):
                    candidate = token[index:index + width]
                    if candidate not in STOP_TERMS:
                        yield candidate


def samples(record):
    count = len(record.segments)
    take = min(count, MAX_SEGMENTS)
    if take == 0:
        return ()
    indices = (0,) if take == 1 else (i * (count - 1) // (take - 1) for i in range(take))
    result = []
    for index in indices:
        segment = record.segments[index]
        text = segment.text
        result.append((index, segment, 0, text[:SEGMENT_CHARS]))
        if len(text) > SEGMENT_CHARS:
            start = max(SEGMENT_CHARS, len(text) - SEGMENT_CHARS)
            result.append((index, segment, start, text[start:]))
    return tuple(result)


def find_groups(features):
    """Discover groups from a feature matrix. Negative labels stay unassigned."""
    import numpy as np
    from sklearn.cluster import HDBSCAN
    from sklearn.metrics.pairwise import cosine_distances
    from threadpoolctl import threadpool_limits

    count = features.shape[0]
    if count < 2:
        return ()
    with threadpool_limits(limits=4):
        distances = cosine_distances(features)
        labels = HDBSCAN(
            metric="precomputed", min_cluster_size=2, min_samples=2,
            cluster_selection_method="leaf", allow_single_cluster=True, copy=True,
        ).fit_predict(distances)
    similarities = 1 - distances
    np.fill_diagonal(similarities, 0)
    cutoff = max(MIN_SIMILARITY, float(np.median(similarities.max(axis=1))) * 0.75)
    groups = []
    for label in sorted(set(labels) - {-1}):
        members = np.flatnonzero(labels == label)
        related = similarities[np.ix_(members, members)].max(axis=1) >= cutoff
        if related.sum() > 1:
            groups.append(tuple(int(index) for index in members[related]))
    return tuple(sorted(groups))


def group_keywords(member_terms, corpus_counts):
    support = Counter(term for document in member_terms for term in document)
    ranked = sorted(
        (term for term, count in support.items() if count > 1),
        key=lambda term: (-support[term] ** 2 / corpus_counts[term], -len(term), term),
    )
    selected = []
    for term in ranked:
        if any(term in old or old in term for old in selected):
            continue
        selected.append(term)
        if len(selected) == 3:
            break
    return tuple(selected)


def naming_terms(text):
    import jieba

    jieba.setLogLevel(logging.WARNING)
    for word in jieba.cut(text.casefold(), HMM=False):
        word = word.strip()
        if len(word) > 1 and TOKEN_RUNS.fullmatch(word) and word not in STOP_TERMS:
            yield word


def representative_evidence(parts, keywords):
    patterns = [re.compile(re.escape(word), re.IGNORECASE) for word in keywords]
    best_part, best_hits = max(
        ((part, [hit for pattern in patterns if (hit := pattern.search(part[3]))])
         for part in parts if part[3].strip()),
        key=lambda item: len(item[1]),
    )
    index, segment, offset, snippet = best_part
    hit = best_hits[0].start() if best_hits else 0
    start = max(0, hit - 16)
    return Evidence(f"{index + 1}:{offset}", segment.label, offset + start, snippet[start:hit + 100])


def local_embeddings(texts, model_path, stop):
    import numpy as np
    from sklearn.preprocessing import normalize

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as error:
        raise CatalogError("本地语义模型不可用，请安装 requirements-local-model.txt，或用关键词方式运行。") from error
    if not Path(model_path).is_dir():
        raise CatalogError("请选择完整的本地 Sentence Transformer 模型目录。")
    try:
        model = SentenceTransformer(
            str(model_path), local_files_only=True, trust_remote_code=False, device="cpu",
            model_kwargs={"use_safetensors": True},
        )
        budget = model.max_seq_length - model.tokenizer.num_special_tokens_to_add(pair=False)
        if budget < 1:
            raise ValueError("invalid token budget")

        def split(piece):
            if len(model.tokenizer.encode(piece, add_special_tokens=False, verbose=False)) <= budget:
                yield piece
            elif len(piece) > 1:
                middle = len(piece) // 2
                yield from split(piece[:middle])
                yield from split(piece[middle:])
            else:
                raise ValueError("model token budget is too small")

        vectors = []
        for text in texts:
            if stop.is_set():
                return None
            pieces = [part for line in text.splitlines() for part in split(line) if part.strip()]
            encoded = model.encode(pieces, batch_size=16, normalize_embeddings=True, show_progress_bar=False)
            vectors.append(np.asarray(encoded).mean(axis=0))
        return normalize(np.asarray(vectors))
    except (OSError, RuntimeError, TypeError, ValueError) as error:
        raise CatalogError("无法读取本地语义模型，请检查模型文件和 Python 依赖。") from error


def build_proposal(records, stop, *, model_path=None):
    from sklearn.feature_extraction.text import TfidfVectorizer

    if len(records) > MAX_DOCUMENTS:
        raise CatalogError(f"本次发现分组最多分析 {MAX_DOCUMENTS} 份资料，请选择较小的目录。")
    entries = []
    rows = {}
    for record in records:
        if stop.is_set():
            return None
        used = samples(record) if record.available else ()
        body = "\n".join(part[3] for part in used)
        if not any(terms(body)):
            rows[record.id] = Analysis(record.id, record.digest,
                                       detail=record.detail or "没有可用于发现分组的正文。")
            continue
        coverage = "COMPLETE" if (record.status == "EXTRACTED" and
                                  len(used) == len(record.segments) and
                                  all(piece == segment.text for _, segment, _, piece in used)) else "PARTIAL"
        entries.append((record, used, body, coverage))
        rows[record.id] = Analysis(
            record.id, record.digest, coverage=coverage,
            covered=len({index for index, *_ in used}), total=len(record.segments),
            detail="未发现足够相似的文档，请审核并选择类别。",
        )

    groups = ()
    if len(entries) >= 2 and not stop.is_set():
        texts = [entry[2] for entry in entries]
        if model_path is None:
            matrix = TfidfVectorizer(analyzer=terms, max_features=16_000, sublinear_tf=True).fit_transform(texts)
        else:
            matrix = local_embeddings(texts, model_path, stop)
        if matrix is not None:
            groups = find_groups(matrix)
    if stop.is_set():
        return None

    document_terms = [set(naming_terms(entry[2])) for entry in entries] if groups else []
    corpus_counts = Counter(term for document in document_terms for term in document)
    used_names = set()
    for number, members in enumerate(groups, 1):
        if stop.is_set():
            return None
        keywords = group_keywords([document_terms[index] for index in members], corpus_counts)
        base_name = " · ".join(keywords[:2])[:64] or f"相似资料 {number}"
        name = base_name
        suffix = 2
        while name in used_names:
            name = f"{base_name}（{suffix}）"
            suffix += 1
        used_names.add(name)
        for index in members:
            record, parts, _, coverage = entries[index]
            rows[record.id] = Analysis(
                record.id, record.digest, course=name, topic="、".join(keywords),
                evidence=(representative_evidence(parts, keywords),), coverage=coverage,
                covered=len({n for n, *_ in parts}), total=len(record.segments),
                review=False, detail="按组内共享正文特征生成。可在确认前改名、合并或调整归属。",
            )

    pending = sum(row.review for row in rows.values())
    return Proposal(
        uuid4().hex, 1, tuple(rows.values()),
        f"本地发现（{'语义向量' if model_path is not None and len(entries) >= 2 else '关键词'}）"
        f" · {len(groups)} 个建议分组，{pending} 份待确认，共 {len(rows)} 份资料。",
    )


def discover_folder(library, store, folder: Path, stop, progress, *,
                    recursive=True, exclusions=(), model_path=None):
    if stop.is_set():
        return None
    folder = absolute(folder)
    existing = next((source for source in library.sources() if path_key(source.path) == path_key(folder)), None)
    if existing is None:
        try:
            source = Source.directory(folder, recursive=recursive, exclusions=exclusions)
        except OSError as error:
            raise CatalogError("所选目录不可访问或无法验证。") from error
        if stop.is_set():
            return None
        library.set_source(source)
    elif existing.kind != "directory" or not existing.is_current():
        raise CatalogError("所选目录的原授权已失效，请在文件库重新导入。")
    records = library.refresh(stop, progress, only=folder)
    if stop.is_set():
        return None
    if not records:
        raise CatalogError("这个目录没有可加入审核的资料。请检查子目录和排除项设置。")
    proposal = build_proposal(records, stop, model_path=model_path)
    if proposal is not None and not stop.is_set():
        store.create(proposal, check_current=True)
        return proposal
    return None
