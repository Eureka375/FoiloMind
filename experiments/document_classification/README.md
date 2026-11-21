# 批量文档分类 · 第一阶段独立原型

实际工程位于 `D:\Study\人机交互\FoiloMind_Git`（2026-11-21 核查）；`D:\Projects\FoiloMind_Git` 当时不存在。本目录与正式 Tkinter 客户端、SQLite 资料库和正式依赖文件隔离，没有迁移或重建工程。检查工作区、父目录和仓库文件清单未发现适用的 AGENTS.md。开发前已有未提交的 README、前端与文档改动，均不纳入本实验提交。

## 已实现的流程

选择一个目录 → 排除指定路径及链接/Windows 重解析点 → 只读提取 → 按正文差异和稀疏程度抽样 → 本地聚类 → 新目录保存建议与性能记录。原文件不会移动、改名或写入；不会打开正文中的链接或附件，不调用云端 API。新增 OCR 属于本次授权的实验范围，不改变正式首版不含 OCR 的边界。

- TXT/MD：严格 UTF-8，失败后尝试 GB18030，并提示人工核对。正文按 1600 字符分块。
- DOCX：正文段落及表格，保留主文档顺序；不支持旧 `.doc`，也不承诺文本框、页眉、脚注或图片提取。DOCX/TXT/MD 当前仍完整解析再抽样，抽样节省的是后续向量计算。
- PDF：PyMuPDF 快速提取文字层；先抽首、中、尾三页，内容差异大或文字不足则扩大为最多九页的均匀抽样。不会把抽样覆盖当作全文理解。
- OCR：默认关闭。`--ocr auto` 仅对被抽到且文字少于 24 字符的 PDF 页调用本地 OCR，150 DPI。需本地语言包；不足、失败或缺少环境明确记录。文字足够但局部含图片的页面可能漏识别。
- TF-IDF：英文词＋中文双字特征，最多 12000 维；KMeans 固定随机种子 42，10 次初始化。
- Embedding：本地 multilingual MiniLM，CPU 推理；按实际 tokenizer 上限分块，归一化向量平均后再次归一化；余弦距离＋average linkage 层次聚类。分组数通过 `--clusters` 指定，不自动推断课程名。分组关键词只是审核线索。

## 环境与首次运行

在仓库根目录执行以下 PowerShell 命令。独立虚拟环境首次安装需要网络；推理不需要网络。正式客户端继续使用根目录 `.venv`。

```powershell
python -m venv experiments/document_classification/.venv
experiments/document_classification/.venv/Scripts/python.exe -m pip install -r experiments/document_classification/requirements.txt
```

本机为减少重复安装，实验环境采用 `--system-site-packages` 复用了已有 PyTorch、PyMuPDF 和 sklearn；新增的模型依赖仍安装在实验 `.venv`，没有修改正式环境。其他机器推荐上面的完整独立安装。若 PyPI 连接失败，可给 pip 指定 `--index-url https://pypi.tuna.tsinghua.edu.cn/simple`，保持 HTTPS 证书检查。

先生成可丢弃的三主题四格式合成样本，再运行基线：

```powershell
experiments/document_classification/.venv/Scripts/python.exe experiments/document_classification/make_demo.py experiments/document_classification/runs/my-demo
experiments/document_classification/.venv/Scripts/python.exe experiments/document_classification/classify.py experiments/document_classification/runs/my-demo --output experiments/document_classification/runs/my-baseline --clusters 3
```

直接分析用户选择的资料目录（替换源路径；输出必须是源目录之外尚不存在的新目录）：

```powershell
experiments/document_classification/.venv/Scripts/python.exe experiments/document_classification/classify.py "D:/资料/待分类" --output experiments/document_classification/runs/review-001 --clusters 5 --exclude "私人资料" --exclude "归档/不分析"
```

`--exclude` 为相对源目录的文件或目录路径，可重复。不读取被排除项，不自动解释 `.aiignore`；如原目录使用该文件，请把所需排除规则显式传入。本原型不跟随链接和重解析点；运行期间请保持目录稳定，不用于正在被其他进程改写或恶意替换的目录。

## 本地模型和 OCR 的准备

模型准备命令只下载公开模型，不读取文档。固定版本约 470 MB 权重，另有 tokenizer；模型与语言包均被 Git 忽略。分类要求传入本地模型目录，启用 `local_files_only` 和离线环境标志，不静默改用在线模型。

```powershell
experiments/document_classification/.venv/Scripts/python.exe experiments/document_classification/prepare_model.py experiments/document_classification/models/multilingual-minilm --revision e8f8c211226b894fcb81acc59f3b34ba3efd5f42
# 官方下载连接失败时，显式选择镜像直接下载：
experiments/document_classification/.venv/Scripts/python.exe experiments/document_classification/prepare_model.py experiments/document_classification/models/multilingual-minilm --revision e8f8c211226b894fcb81acc59f3b34ba3efd5f42 --direct-mirror
experiments/document_classification/.venv/Scripts/python.exe experiments/document_classification/classify.py experiments/document_classification/runs/my-demo --output experiments/document_classification/runs/my-comparison --method both --model experiments/document_classification/models/multilingual-minilm --clusters 3
```

可选 OCR：

```powershell
experiments/document_classification/.venv/Scripts/python.exe experiments/document_classification/prepare_ocr.py experiments/document_classification/tessdata
experiments/document_classification/.venv/Scripts/python.exe experiments/document_classification/classify.py experiments/document_classification/runs/my-demo --output experiments/document_classification/runs/my-ocr --clusters 3 --ocr auto --tessdata experiments/document_classification/tessdata
```

语言包来自官方 tessdata_fast 的固定提交，包含 `chi_sim+eng`。Windows OCR 原生库可能无法读取含中文字符的语言包路径，程序会尝试转成相对路径；建议从仓库根目录使用上述命令。如仍失败，使用 ASCII 路径的语言包目录。可用 `--ocr-language eng` 只识别英文。

## 输出与审核

新输出目录包含 `suggestions.md` 和 `report.json`。JSON 保存逐文件状态、SHA-256、提取时间、抽样页/块、覆盖比例、OCR 页号、错误、最多 160 字符证据片段，以及各算法分组与关键词。报告可能包含文件名和短正文，应保存在用户允许的位置；可直接删除整个结果目录清理派生结果。

时间记录包括总运行和各方法的墙钟/进程 CPU 秒数；内存为进程 RSS 每 20ms 采样的观测峰值，短时尖峰可能遗漏，也不等于该方法独占增量。总运行计时不含 Python 启动和 psutil 导入。首次运行包含其他库/模型加载，不能把冷启动与热启动混比。分类线程上限采用 4；未测 GPU 和大规模吞吐。

退出码 0 表示所选算法执行成功，单文件失败仍记录在报告；2 表示参数/路径错误或任一算法失败。`--method both` 中模型缺失时仍保留 TF-IDF 成果，并将 Embedding 明确标记为 error。空目录会生成空建议。超出文件数量限制则终止并提示缩小范围，不隐瞒截断。

## 验证与阶段边界

```powershell
experiments/document_classification/.venv/Scripts/python.exe -B -m unittest discover -s experiments/document_classification/tests -v
.venv/Scripts/python.exe -B -m unittest discover -s tests -v
```

默认最多 500 文件，可调至 2000；单文件 32 MiB，DOCX 解压后 64 MiB，最多抽 9 单元，可调至 30。层次聚类具有平方级规模成本，当前限额不代表 2000 份已验收。没有解析器硬超时、子进程隔离或取消控制；不作为不可信恶意文件处理服务。

这是无监督分组实验，尚未接入正式客户端、持久化、真实资料人工评价或自动命名。抽样会遗漏局部主题；纯数字/符号文本标记为 no_features；跨主题文档仍只分到一组。后续应先用真实脱敏留出集比较分组质量、人工修改量和 CPU/内存，再决定缓存、自动类别数或客户端接入。

实现依据：[SentenceTransformer 离线模型接口](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html)、[sklearn 层次聚类](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.AgglomerativeClustering.html)、[PyMuPDF OCR](https://pymupdf.readthedocs.io/en/latest/page.html)。实测记录见本目录 [VALIDATION.md](VALIDATION.md)。

完整可重复的性能对照（创建合成输入、运行两种算法、核对原件哈希并输出 ARI 与资源记录）：

```powershell
experiments/document_classification/.venv/Scripts/python.exe -B experiments/document_classification/benchmark_demo.py experiments/document_classification/runs/compare-001 --model experiments/document_classification/models/multilingual-minilm --tessdata experiments/document_classification/tessdata
```
