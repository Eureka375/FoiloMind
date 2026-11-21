# 第一阶段验证记录 · 2026-11-21

核查目录：`D:\Study\人机交互\FoiloMind_Git`。未执行工程迁移，未修改正式客户端代码或其依赖。初始 HEAD 为 `3ace847`，远程 origin/main 与之相同。

## 基线与 OCR

- 独立实验测试 7 项通过，包括四格式端到端、源文件字节哈希不变、空/单份/相同正文、排除路径规范化、首尾抽样、token 上限及实际扫描 PDF OCR。
- 正式工程原有测试 47 项全部通过（其中包含工作区原有未提交前端测试）；损坏 PDF 样本的 `EOF marker not found` 为既有解析提示，不是测试失败。
- `runs/benchmark-baseline/summary.json`：15 份合成文件，13 份可提取（含扫描 PDF OCR）、1 份故意损坏、1 份空白。全部 15 份运行前后 SHA-256 不变。TF-IDF 三组与合成主题对应，ARI=1.0。总墙钟 2.911 秒、CPU 2.188 秒、观测 RSS 峰值 182.95 MiB。是重复关键词的小样本流程验证，不是真实资料准确率。
- `runs/fixtures-final/report.json`：读取正式 fixture 的指定目录，排除 `资料/仅测试排除`，21 份记录，其中 15 份 ok、4 份明确错误、1 份无正文、1 份不支持。纯扫描 PDF 和混合 PDF 的扫描页成功 OCR。相似目录 `资料/仅测试排除-应纳入` 正常纳入。
- 已验证缺失权重时 `--method both` 仍保存基线结果，将 Embedding 标为 error 并非零退出，没有静默联网或冒充语义结果。

## 模型准备

模型使用 `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` 固定提交 `e8f8c211226b894fcb81acc59f3b34ba3efd5f42`。已验证 SentenceTransformer 3.4.1 / Transformers 4.49.0 在本机导入。官方模型 CDN 多次超时，Hub 镜像元数据也出现不兼容，改为显式 HTTPS 镜像直接下载相同版本。真实语义推理结果在完成权重下载后另行补充；本节不将接口实现当作真实模型验收。

本机复用 Python 3.13.5、PyTorch 2.11.0 CPU、scikit-learn 1.8.0、PyMuPDF 1.27.2.3、python-docx 1.2.0、psutil 7.2.2。OCR 使用 tessdata_fast `87416418657359cb625c412a48b6e1d6d41c29bd`，英文 SHA-256 `7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2`，简体中文 `a5fcb6f0db1e1d6d8522f39db4e848f05984669172e584e8d76b6b3141e1f730`。

## 可复现方式

从仓库根目录运行（输出路径必须尚不存在）：

```powershell
experiments/document_classification/.venv/Scripts/python.exe -B experiments/document_classification/benchmark_demo.py experiments/document_classification/runs/reproduce --tessdata experiments/document_classification/tessdata
```

该命令创建合成输入，运行 CLI，比较全部源文件 SHA-256，计算 ARI，写入 report 与 summary。去掉 `--tessdata` 可验证默认不启用 OCR 的路径；加 `--model experiments/document_classification/models/multilingual-minilm` 可运行双算法对照。

没有测试真实用户大批量数据、分类质量留出集、极端大文档、GPU 或模型并发；不声称达到产品验收。所有 runs、模型、语言包、实验环境均未入 Git。
