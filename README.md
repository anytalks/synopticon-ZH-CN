# Synopticon 简体中文汉化与增强版（synopticon-ZH-CN）

> **转载与出处声明 / Attribution & Upstream**
> - 本仓库为开源项目 **Synopticon** 的简体中文汉化与二次修改版本（Fork）。
> - **原项目地址**：[https://github.com/fdebijl/synopticon](https://github.com/fdebijl/synopticon)
> - **原作者**：Floris de Bijl
> - **基于上游版本**：`v0.27.0`（commit `4452dd95`）
> - **开源协议**：完整保留原项目版权归属与 [LICENSE](LICENSE) 协议条款（原仓库根目录 `LICENSE` 为 MIT，`pyproject.toml` 标注为 `AGPL-3.0-or-later`，使用时请遵循原仓库对应协议要求）。

---

## 本分支主要中文与功能增强

1. **全量简体中文界面与配置汉化**
   - 完整汉化 Vue 3 Web 管理前端（`frontend/src/`、`frontend/index.html`），保留全部后端校验短语与 API 字段契约。
   - 汉化后端全部 10 个设置分区共 77 项配置元数据与说明文本（`src/synopticon/config.py`）。
2. **审核页面「一键全审」功能**
   - 新增后端接口 `POST /api/review/bulk-all` 与 `queries.bulk_approve_all`（`src/synopticon/web/app.py`、`src/synopticon/review/queries.py`）。
   - 审核工具栏新增 **「一键全审 / 一键全审当前类」** 按钮（`frontend/src/components/review/BulkApproveBar.vue`、`frontend/src/views/ReviewView.vue`），支持不限类型与置信度一次通过待审核建议（包括无置信度分值的合并分组与发现新人物条目），附带按类型统计明细的二次确认弹窗；仅在本地数据库标记为「已通过」，写回群晖仍需在「应用写回」页面确认执行。
3. **Apple Silicon（macOS）CoreML + CPU 混合推理加速**
   - 固定输入尺寸的 `yolov8l-face`（`640x640`）与三个 `112x112` 人脸识别模型（ArcFace `glintr100` / AdaFace / MagFace）在 `inference.device = "auto"` 时自动启用 `CoreMLExecutionProvider`（`MLProgram` + 本地编译缓存 `~/Library/Caches/synopticon/coreml/`），识别模型在 CoreML 模式下固定 `batch=1` 推理以消除动态批大小重编译抖动；
   - 动态分辨率主检测器 `scrfd_10g_bnkps` 显式保留在 CPU 上运行以兼容任意照片长宽比，并自动检测 Apple Silicon 性能核数（排除能效核阻塞）作为默认 `intra_op_threads`；
   - 配置 `device = "cpu"` 可随时切回纯 CPU 模式，Windows / Linux CUDA 路径保持完全兼容。
4. **稳定性修复**
   - 修复动态分辨率推理显存/内存池持续增长不收缩的问题（`src/synopticon/pipeline/onnx_session.py`、`src/synopticon/pipeline/detect/scrfd.py`）。
   - 修复 Web 设置页面保存配置后未刷新内存配置导致界面回弹的问题（`src/synopticon/web/configio.py`）。
5. **macOS 便捷启动与防休眠脚本**
   - 新增访达双击启动脚本 [`start-synopticon.command`](start-synopticon.command) 与后台常驻防休眠管理脚本 [`synopticon-bg.sh`](synopticon-bg.sh)（内置 `caffeinate -i` 防止长时挂机提取时系统休眠，支持 `--lan` 开放局域网访问）。

## 中文快速开始（macOS Apple Silicon / Linux / Windows）

前置依赖：Python 3.11–3.12（建议使用 `uv`）、Node.js 22+（用于编译前端）。

```bash
# 1. 克隆仓库并准备目录
git clone https://github.com/anytalks/synopticon-ZH-CN.git
cd synopticon-ZH-CN
mkdir -p data models
cp config.example.toml data/config.toml

# 2. 安装 Python 依赖（macOS / 纯 CPU 环境用 --extra cpu；NVIDIA GPU 环境可换为 --extra gpu）
uv sync --frozen --no-dev --python 3.11 --extra cpu --extra review --extra faiss

# 3. 编译简体中文前端静态资源到 src/synopticon/web/dist/
cd frontend && npm ci && npm run build && cd ..

# 4. 下载模型权重并启动 Web 服务
uv run synopticon models download
uv run synopticon web
# 或在 macOS 上直接使用防休眠后台脚本：
# ./synopticon-bg.sh start         # 仅本机访问 http://127.0.0.1:8686
# ./synopticon-bg.sh start --lan   # 允许局域网设备访问
```

---

## 原项目英文文档 / Original README

![Synopticon logo](assets/Synopticon%20Hero.png)

Synopticon is a toolkit to run alongside Synology Photos, consisting of a set of utilities that run over your library and take on the jobs DSM currently does poorly or not at all. It includes enhanced face recognition, robust face grouping, automatic face reassignment, duplicate photo deletion and much more.

**Enhanced face recognition**  
Synology's built-in face detection frequently misses faces, or links photos to the wrong person. Synopticon runs a cutting-edge face detection pipeline over your library, cross-references the results against what Synology already knows, and writes corrections back through Synology Photos' API. Writebacks only occur after your explicit review.

![](./assets/pretty_screenshots/review.png)

The result is a drastically better hit rate than Synology Photos' baseline face recognition. While Synology Photos often recalls 20% of the faces in a photo, Synopticon hits a ~95% average recall rate.

![](./assets/other/comparison.png)

**QuickMerger**  
Quickly work through unnamed faces in Synology Photos through an ergonomic merge interface, perfect for giving the initial set of faces a name to start working with inside Synopticon.

**Inspect**  
See exactly what Synopticon saw in a single photo: every face it detected, confidence and quality scores, next to the faces Synology found, plus the group each face landed. Clicking faces in the review screen will, conveniently, also take you here.

![](./assets/pretty_screenshots/inspect.png)

**Deduplication**  
finds duplicate photos (byte-identical, or visually near-identical) from content hashes computed over your originals, keeps the highest-quality copy of each group, and deletes the rest through Synology's background-task API.

![](./assets/pretty_screenshots/quickmerge_dedupe.png)

**Scheduled Runs**  
After the initial setup, schedule synchronization with the NAS, face detection and face grouping without having to touch Synopticon. Just come back every now and then to review the groups.

![](./assets/pretty_screenshots/scheduler.png)

## Quickstart

### Install script

```bash
curl -fsSL https://synopticon.nl/install.sh | bash
```

The script checks your system, installs uv if it's missing, clones the repo into `./synopticon`, builds the web GUI and starts it on http://localhost:8686.

### Manual

Install the requirements:
- Python v3.11-3.12 (Linux, macOS or [Windows](docs/running-locally.md#windows))
- Node v22+

1. Clone the repo and setup directory structure
```bash
git clone https://github.com/fdebijl/synopticon && cd synopticon && mkdir -p data models && cp config.example.toml data/config.toml
```

2. Install dependencies and build the web GUI
```bash
uv sync --extra cpu --extra review --extra faiss && cd frontend && npm ci && npm run build && cd ..
```

3. Run the web GUI
```bash
uv run synopticon web
```

4. Point your browser to http://localhost:8686

This spins up the web GUI, which will walk you through the initial setup for Synopticon. This is a great way to play around with all the features of Synopticon, but for long-term deployments you probably want to run it locally using the CLI, or spin up a persistent Docker container. See [Documentation](#documentation) below for how to do just that.

## Documentation

- [Running locally](docs/running-locally.md) — the web GUI and CLI straight from the repo
- [Running with Docker](docs/docker.md) — images, compose, schedules, backups, authentication, reverse proxies
- [CLI reference](docs/cli-reference.md) — every `synopticon` command
- [Configuration](docs/configuration.md) — `config.toml`, the database backend, GPU acceleration, NAS two-factor
- [MCP server](docs/mcp.md) — let an AI agent tune settings and debug detection and grouping
- [Models](docs/models.md) — which weights the pipeline needs and how to export AdaFace/MagFace
- [How it works](docs/how-it-works.md) — the face-recognition pipeline and deduplication
- [Safety model](docs/safety-model.md) — what can write to your NAS, and what gates it
- [Compatibility](docs/compatibility.md) — supported DSM versions
- [Glossary](docs/GLOSSARY.md) — the face-recognition vocabulary

## LLM Disclaimer
Parts of this codebase were created by a large language model, in particular models provided by Anthropic.

## Acknowledgments
- [ScreenPastel](https://screenpastel.vercel.app/) is an amazing tool for prettifying screenshots that I used for the screenshots at the top
  - Adding additional screenshots for a new feature? Use #9650C9 to #662D91 at a 135 degree direction as the gradient with a 40px padding
- [FeedbackFruits](https://feedbackfruits.com/) for generously donating many megatokens to this project.
