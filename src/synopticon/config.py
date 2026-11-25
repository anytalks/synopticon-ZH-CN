"""Layered configuration: defaults -> TOML file -> SYNOPTICON_* env vars (env wins).

The config file path is taken from SYNOPTICON_CONFIG, defaulting to
./config.toml then /data/config.toml. Credentials are recommended env-only:
SYNOPTICON_NAS__ACCOUNT / SYNOPTICON_NAS__PASSWORD.

Field help text is rendered verbatim in the web Settings UI and reads top-down
from plain language into detail: `description` opens with what the setting does
in ordinary terms and then gives practical guidance, while the internals go in
`json_schema_extra={"details": ...}`, which the GUI renders as a collapsed,
de-emphasized block under the description.
"""

from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

Space = Literal["personal", "shared"]
ProposalKind = Literal[
    "assign", "low_confidence", "reassign", "merge", "merge_named", "new_person"
]


class NasConfig(BaseModel):
    url: str = Field(
        default="",
        title="群晖 NAS 地址",
        description=(
            "群晖 DSM / 群晖照片 API 的基础访问地址"
            "（例如 https://nas.local:5001 或 http://192.168.1.10:5000）。"
        ),
    )
    # Base URL for Synology Photos web-UI deep links in the review UI. The API
    # host/port (`url`) is often not where the web UI lives, so allow an
    # override; falls back to `url` when unset.
    web_url: str = Field(
        default="",
        title="群晖照片网页端地址",
        description=(
            "可选。用于在人脸审核界面生成直达群晖照片网页端的跳转链接。"
            "如果网页端域名或端口与上方 API 地址不同，可在此单独指定；留空则沿用上方群晖 NAS 地址。"
        ),
    )
    verify_tls: bool = Field(
        default=True,
        title="验证 TLS 证书",
        description=(
            "通过 HTTPS 连接群晖 NAS 时是否校验证书有效性。"
            "若 NAS 使用自签名证书且未被本机信任，可取消勾选。"
        ),
    )
    account: str = Field(
        default="",
        title="群晖账号",
        description=(
            "用于登录群晖照片的 DSM 账号名称。"
            "为安全起见，建议优先通过环境变量 SYNOPTICON_NAS__ACCOUNT 提供。"
        ),
    )
    password: SecretStr = Field(
        default=SecretStr(""),
        title="群晖密码",
        description=(
            "上述群晖账号的登录密码。"
            "建议优先通过环境变量 SYNOPTICON_NAS__PASSWORD 提供，避免明文保存在 config.toml 中。"
        ),
    )
    otp_code: str | None = Field(
        default=None,
        title="动态验证码（OTP）",
        description=(
            "仅当群晖账号开启了两步验证且尚未保存可信设备令牌时，需填入当前的 6 位动态验证码。"
            "登录成功后 Synopticon 会缓存设备令牌，后续运行无需重复填写。"
        ),
    )
    device_name: str = Field(
        default="synopticon",
        title="设备名称",
        description=(
            "注册为群晖 DSM 可信设备时显示的名称，用于在开启两步验证的账号上免重复输入动态验证码。"
        ),
    )
    spaces: list[Space] = Field(
        default_factory=lambda: ["personal"],
        title="同步空间",
        description=(
            "需要同步和处理的群晖照片空间：personal 表示个人空间，shared 表示共享空间。"
        ),
    )
    requests_per_second: float = Field(
        default=4.0,
        title="每秒读取请求上限",
        description=(
            "向群晖 NAS 发起读取类 API 请求（同步图库、拉取照片等）的速率上限，默认 4.0 次/秒。"
            "数值过高可能增加 NAS 负载。"
        ),
    )
    write_requests_per_second: float = Field(
        default=1.0,
        title="每秒写入请求上限",
        description=(
            "向群晖 NAS 发起写入类 API 请求（写回修正、合并人物等）的速率上限，默认 1.0 次/秒，"
            "以防写回过快触发群晖限流。"
        ),
    )
    timeout_s: float = Field(
        default=60.0,
        title="请求超时（秒）",
        description=(
            "单次群晖 API 请求（含原图下载）的最长等待时间，默认 60 秒。"
            "如遇大文件下载或 NAS 响应较慢导致超时，可适当调大。"
        ),
    )


class StorageConfig(BaseModel):
    # Repo-root-relative defaults for bare-metal runs; the Docker image
    # overrides both via env to its /data and /models volume mounts.
    data_dir: Path = Field(
        default=Path("./data"),
        title="数据目录",
        description=(
            "Synopticon 存放本地数据库、人脸裁切图、报告与缓存文件的根目录。"
            "Docker 部署时通常会通过环境变量覆盖为 /data 挂载卷。"
        ),
    )
    models_dir: Path = Field(
        default=Path("./models"),
        title="模型目录",
        description=(
            "存放人脸检测与特征提取模型文件的目录。"
            "Docker 部署时通常会通过环境变量覆盖为 /models 挂载卷。"
        ),
    )
    keep_originals: bool = Field(
        default=False,
        title="长期保留原图缓存",
        description=(
            "是否永久保留从群晖下载到本地的原图文件。"
            "关闭时（默认），缓存达到下方容量上限后会自动按最近最少使用（LRU）策略清理旧文件。"
        ),
    )
    originals_cache_gb: float = Field(
        default=50.0,
        title="原图缓存上限（GB）",
        description=(
            "本地原图缓存的最大磁盘占用（默认 50 GB）。"
            "仅在未开启「长期保留原图缓存」时生效；超出上限后会自动清理最久未访问的原图。"
        ),
    )

    @property
    def db_path(self) -> Path:
        return self.data_dir / "synopticon.db"

    @property
    def originals_dir(self) -> Path:
        return self.data_dir / "originals"

    @property
    def crops_dir(self) -> Path:
        return self.data_dir / "crops"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "report"


class DatabaseConfig(BaseModel):
    backend: Literal["sqlite", "postgres"] = Field(
        default="sqlite",
        title="数据库引擎",
        description=(
            "Synopticon 存放自身数据的位置，包括照片索引、检测到的人脸以及你的人脸审核决定（绝不会直接改动群晖照片的内置数据库）。\n\n"
            "'sqlite'（默认）以单个文件保存在数据目录下，无需配置、无需额外部署服务也免维护，除非有明确需求，否则推荐直接使用它。\n"
            "'postgres' 会改用现有的 PostgreSQL 服务器（通过下方连接配置接入）。"
            "适合你本来就运行着 PostgreSQL、希望将数据库与照片缓存分盘存放，或想沿用现有数据库备份工具的场景。\n\n"
            "切换数据库引擎不会自动迁移已有数据：如需将现有图库迁移过去，请运行 `synopticon db-migrate`。"
        ),
        json_schema_extra={
            "details": (
                "使用 PostgreSQL 需要安装可选依赖 'postgres'"
                "（uv sync --extra postgres），其中包含 psycopg 3 及其连接池。\n\n"
                "表结构与 SQL 逻辑共用一套源码：db/schema.sql 及各迁移脚本均以 SQLite 方言编写，"
                "在迁移时按目标引擎自动转换（db/dialect.py）。"
                "版本跟踪在 SQLite 上使用 PRAGMA user_version，在 PostgreSQL 上使用 synopticon_schema_version 表，"
                "并通过会话级咨询锁防止 Web 服务与后台任务子进程同时启动时并发执行迁移。\n\n"
                "不支持 MySQL / MariaDB：其 upsert 语法与同步路径普遍使用的 ON CONFLICT 写法不同，"
                "且 TEXT 列在其中无法直接作为主键。"
            )
        },
    )
    host: str = Field(
        default="localhost",
        title="主机地址",
        description="PostgreSQL 服务器的主机名或 IP 地址。",
    )
    port: int = Field(
        default=5432,
        title="端口",
        description="PostgreSQL 服务器监听的端口号，默认为 5432。",
    )
    user: str = Field(
        default="synopticon",
        title="用户名",
        description="用于连接 PostgreSQL 的角色（用户）名，该角色需拥有目标数据库的所有权。",
    )
    password: SecretStr = Field(
        default=SecretStr(""),
        title="密码",
        description="上述 PostgreSQL 角色的密码。如果数据库服务器配置了免密信任连接（trust），可留空。",
    )
    database: str = Field(
        default="synopticon",
        title="数据库名称",
        description=(
            "要使用的数据库名。该数据库必须预先创建好——Synopticon 会在其中自动建表，但不会自动创建数据库本身。"
        ),
    )
    sslmode: str = Field(
        default="prefer",
        title="SSL 模式",
        description=(
            "控制对加密连接的严格程度。'prefer'（默认）在服务器支持时自动加密，"
            "'require' 强制要求加密否则拒绝连接，'disable' 永不加密。"
        ),
        json_schema_extra={
            "details": (
                "原样透传给 libpq 作为 sslmode 参数；完整可选值为 "
                "disable、allow、prefer、require、verify-ca、verify-full。"
            )
        },
    )
    pool_size: int = Field(
        default=5,
        title="连接池大小",
        description=(
            "Synopticon 同时保持打开的 PostgreSQL 连接数。默认值即可满足单实例 Web 服务；"
            "仅在高负载操作感觉界面排队卡顿时再适当调大。"
        ),
        json_schema_extra={
            "details": (
                "Web 服务按请求获取连接，如果没有连接池，概览页的每次轮询都要额外经历一次 TCP 握手与认证。"
                "每个进程按 DSN 维护一个连接池；后台任务子进程会各自建立自己的连接池。"
            )
        },
    )
    url: SecretStr = Field(
        default=SecretStr(""),
        title="连接字符串（URL）",
        description=(
            "可选。填写完整的 postgresql:// 连接字符串，将会覆盖上方所有单独的连接字段。"
            "托管数据库服务通常会直接提供这一整串地址供粘贴使用。"
        ),
        json_schema_extra={
            "details": (
                "原样透传给 libpq，因此 libpq 支持的任意参数均可直接写在里面"
                "（如 sslmode、connect_timeout、options 等）。由于连接字符串通常内嵌密码，会作为敏感字段隐藏处理。"
            )
        },
    )


class InferenceConfig(BaseModel):
    device: Literal["auto", "cpu", "cuda"] = Field(
        default="auto",
        title="推理设备",
        description=(
            "决定人脸模型运行在 CPU 还是 NVIDIA GPU 上。GPU 速度快得多；CPU 则在任何机器上都能运行。\n\n"
            "'auto'（默认）在检测到可用 GPU 时优先使用 GPU，否则静默回退到 CPU。\n"
            "'cuda' 明确要求使用 GPU，但如果环境不可用，仍会输出警告并回退到 CPU。\n"
            "'cpu' 始终不使用 GPU，兼容性最好。"
        ),
        json_schema_extra={
            "details": (
                "为所有检测与特征提取模型选择 ONNX Runtime 的执行提供程序（Execution Provider）。"
                "可在人脸检测与提取任务的启动日志（'running on GPU/CPU'）或通过 `synopticon hwinfo` 确认实际生效的设备——"
                "如果设为 'cuda' 却仍显示 CPU，说明 CUDA 初始化失败，最常见的原因是安装了仅支持 CPU 的 onnxruntime 包。"
            )
        },
    )
    device_id: int = Field(
        default=0,
        title="CUDA 设备编号",
        description=(
            "当机器装有多块 GPU 时，指定要使用哪一块。0 表示第一块 GPU；单卡或纯 CPU 机器保持默认即可。\n\n"
            "编号与 nvidia-smi 保持一致，在 CPU 模式下此项会被忽略。内置不支持单次任务多卡并行——"
            "单次运行只使用一块 GPU；如果确实需要多卡并行，可分别启动多个 Synopticon 实例并递增此编号。"
        ),
        json_schema_extra={
            "details": (
                "推理会话绑定的 CUDA 设备序号。编号越界会导致 CUDA 初始化失败并静默回退至 CPU，"
                "请在运行人脸检测或基准测试时通过 nvidia-smi 确认目标 GPU 确实产生了负载。"
            )
        },
    )
    batch_size: int = Field(
        default=16,
        title="特征提取批大小",
        description=(
            "每次同时交给识别模型处理的人脸头像数量。批大小越大，GPU 利用率越高，但占用的显存/内存也越多。\n\n"
            "常见范围 8–64，默认 16：显存充裕的 GPU 可调高至 32–64；CPU 或小显存 GPU 建议保持在 8–16；"
            "如果在特征提取（embed）阶段遇到显存/内存不足（OOM）报错，请调低此值。"
        ),
        json_schema_extra={
            "details": (
                "仅作用于特征提取（embedding）阶段——人脸检测器始终按单张照片处理。"
                "单张照片的有效批大小不会超过该照片中检测到的人脸数，因此调大此值主要对多人大合照有加速效果。"
                "可使用 `synopticon benchmark` 实测 'embed' 阶段的耗时变化。"
            )
        },
    )
    intra_op_threads: int | None = Field(
        default=None,
        title="ONNX Runtime 算子内线程数",
        description=(
            "人脸模型最多可使用的 CPU 线程数。这是纯 CPU 运行时最核心的速度调节项；留空（默认）会自动使用所有物理核心。\n\n"
            "如需为机器上的其他服务预留算力，或同时运行多个提取进程避免互相抢占核心，可手动指定较小的值（如 2–4）。"
            "超过物理核心数通常不会带来额外提速。"
        ),
        json_schema_extra={
            "details": (
                "对应 ONNX Runtime 的 intra-op 线程数（单个算子内部的并行度）。"
                "留空时默认取物理核心数——刻意排除了超线程，因为计算密集型算子通常无法从中受益；"
                "显式指定数值也能避免与 BLAS / OpenMP 线程池发生过度订阅。"
                "可通过 `synopticon benchmark` 对比不同数值下各阶段耗时进行调优。"
            )
        },
    )
    job_threads: int | None = Field(
        default=None,
        title="后台任务 BLAS/OpenMP 线程数",
        description=(
            "从网页端启动的后台任务最多可使用的 CPU 线程数。留空（默认）表示「总核心数减 1」，专门留出一个核心确保网页界面流畅响应。\n\n"
            "如果运行后台任务时网页变得卡顿缓慢，调整此项即可见效。设为 0 表示完全不干预环境变量；"
            "若外部环境已预先导出相关线程变量，则始终以已导出的值为准。"
        ),
        json_schema_extra={
            "details": (
                "会以 OMP_NUM_THREADS 及各 BLAS / OpenMP / numexpr 同义环境变量的形式注入到任务子进程中。"
                "人脸聚类阶段会通过 BLAS 执行大型矩阵乘法，默认情况下会为每个核心拉起忙等自旋线程，从而饿死单进程的 uvicorn Web 服务——"
                "典型症状是其他无关页面请求全部卡住数十秒后在同一瞬间一起返回。"
                "此项不控制 ONNX Runtime 自身的线程池（请另见 intra_op_threads）。"
            )
        },
    )
    job_nice: int = Field(
        default=10,
        ge=0,
        le=19,
        title="后台任务 CPU 优先级（Nice 值）",
        description=(
            "控制网页端启动的后台任务在争抢 CPU 时的退让程度。数值越大，任务越倾向于让出 CPU 给其他进程。\n\n"
            "范围 0–19；默认 10 可以让网页交互请求在争抢时优先响应，同时几乎不会拖慢后台任务本身"
            "（优先级仅在同时竞争 CPU 时生效）。设为 0 表示与 Web 服务同等优先级运行。"
        ),
        json_schema_extra={
            "details": "任务子进程创建后应用的系统调度 niceness 值。"
        },
    )


class DetectionConfig(BaseModel):
    scales: list[float] = Field(
        default_factory=lambda: [1.0, 2.0],
        title="SCRFD 多尺度缩放倍数",
        description=(
            "每张照片在放大后重新扫描的倍数列表，用来找回画面中较小或较远的人脸。\n\n"
            "[1.0] 仅按原尺寸扫描一次，速度最快，但容易漏掉小脸；[1.0, 2.0]（默认）会额外按 2 倍尺寸再扫一遍以找回小脸。"
            "如果小脸经常漏检，可追加更大的倍数；如果大图处理过慢或内存暴涨，可去掉 2.0。"
        ),
        json_schema_extra={
            "details": (
                "仅作用于 SCRFD 检测器的图像金字塔缩放倍数（不影响 YOLO）——整张图像会按列表中的每个倍数缩放后重新推理。"
                "每增加一个尺度都是一次完整前向推理，2.0 倍大约需要 4 倍的像素量、计算量与内存；过大倍数会受 max_long_side 上限限制。"
            )
        },
    )
    scrfd_score: float = Field(
        default=0.45,
        title="SCRFD 检测置信度阈值",
        description=(
            "主检测器需要有多大把握才会把一个区域判定为人脸。调低可找回更多人像，但也会混入更多非人脸误检。\n\n"
            "范围 0–1，常见 0.2–0.5；默认 0.45 偏向高精度。如需找回侧脸、遮挡脸或模糊人脸，可适当调低（代价是误检增多影响聚类）；"
            "如果复杂纹理背景经常被误识别成人脸，请调高此值。"
        ),
        json_schema_extra={
            "details": (
                "主检测器 SCRFD 的置信度阈值，只有它输出的检测框保留面部关键点。"
                "修改后需重新运行人脸检测与提取（extract）阶段才能评估效果。"
            )
        },
    )
    yolo_score: float = Field(
        default=0.45,
        title="YOLO 检测置信度阈值",
        description=(
            "辅助检测器的置信度门槛，专门用来补漏主检测器漏掉的人脸。\n\n"
            "范围 0–1，常见 0.25–0.5；默认 0.45，与 scrfd_score 保持一致，确保补充检出的人脸同样可靠。"
            "调低可让它补充更多新检出的人脸（同时伴随更多误检）；如果它引入了不少杂框，则调高。未安装 YOLO 模型时此项无效。"
        ),
        json_schema_extra={
            "details": (
                "偏向高召回的辅助检测器 YOLOv8-face 的置信度阈值，其未与 SCRFD 重合的框会作为额外人脸加入。"
                "调参时应重点观察那部分「仅由 YOLO 检出」的增量人脸。修改后需重新运行 extract 阶段验证效果。"
            )
        },
    )
    nms_iou: float = Field(
        default=0.45,
        title="单检测器内部 NMS IoU 阈值",
        description=(
            "同一个检测器输出的两个框重叠达到多少时视为同一张脸，用于清理叠在同一张脸上的重复框。\n\n"
            "常见范围 0.3–0.6，默认 0.45。如果同一张脸上出现多个重叠框（多尺度扫描时较常见），请调低；"
            "如果两张紧挨着的脸（如贴脸合影）被合并成了一个框，请调高。"
        ),
        json_schema_extra={
            "details": (
                "单个检测器内部非极大值抑制（NMS）的交并比（IoU）阈值，用于对同一检测器自身的多尺度检测框去重。"
                "此项不是 SCRFD 与 YOLO 的跨模型融合阈值——跨模型融合请见 cross_iou。"
            )
        },
    )
    cross_iou: float = Field(
        default=0.50,
        title="SCRFD ↔ YOLO 融合 IoU 阈值",
        description=(
            "主检测器与辅助检测器各自框出的区域重叠达到多少时，才判定为同一张脸而非两张不同的脸。\n\n"
            "常见范围 0.3–0.6，默认 0.50。如果融合后同一张脸重复出现两次（两个检测器各出一次），请调低；"
            "如果相邻的两张不同人脸被合并成了一张，请调高。未安装 YOLO 模型时此项无效。"
        ),
        json_schema_extra={
            "details": (
                "用于融合 SCRFD 与 YOLO 检测结果的交并比（IoU）阈值。高于此值时视作同一张脸，优先保留带有关键点的 SCRFD 框；"
                "低于此值时将 YOLO 框作为新发现的人脸补充保留。"
            )
        },
    )
    min_face_px: int = Field(
        default=20,
        title="最小人脸尺寸（像素）",
        description=(
            "值得保留的最小人脸像素尺寸，小于该尺寸的检测结果会被直接丢弃。\n\n"
            "常见范围 16–40，默认 20。如果大量模糊垃圾小脸拖累了聚类质量，请调高；"
            "仅在确实需要识别远景背景人物时才考虑调低。"
        ),
        json_schema_extra={
            "details": (
                "按原图像素中检测框的较短边计算。过小的人脸裁切图提取出的特征噪声大，容易污染聚类分组。"
                "建议与 scales 联合调优，避免多尺度找回的小脸又被此过滤器筛掉。"
            )
        },
    )
    max_long_side: int = Field(
        default=6000,
        title="放大后最大长边（像素）",
        description=(
            "限制查找人脸时允许把照片放大的最大尺寸，防止超高像素原图放大后撑爆内存。\n\n"
            "常见范围 4000–8000（取决于可用内存），默认 6000。若高像素照片处理极慢或触发内存溢出，请调低；"
            "如果 scales 里配了 2.0 及以上，但大图中的小脸依然没被找回，可能是这个上限把放大倍数压回去了，可适当调高。"
        ),
        json_schema_extra={
            "details": (
                "限制 SCRFD 图像金字塔放大后的长边像素，用于封顶多尺度内存开销：实际放大倍数会被压缩以保证 long_side × factor 不超过此值。"
                "此项仅限制放大，绝不会缩小本身尺寸就已经很大的原图。仅作用于 SCRFD。"
            )
        },
    )
    yolo_upscale_below_px: int = Field(
        default=1600,
        title="YOLO 自动放大阈值（像素）",
        description=(
            "当照片尺寸小于此阈值时，辅助检测器会自动按 2 倍分辨率再扫描一次，避免漏掉小图中的小脸。\n\n"
            "常见范围 1000–2500，默认 1600。如果中等分辨率照片（约 640–1600px）中的小脸容易漏检，请调高；"
            "如果 YOLO 耗时占比过高且不太在意小脸召回率，请调低。"
        ),
        json_schema_extra={
            "details": (
                "按照片长边像素判定。由于 YOLO 输入固定 letterbox 缩放到 640px，较小图片若不先放大容易浪费有效分辨率。"
                "仅作用于 YOLO，与 SCRFD 的 scales 相互独立。"
            )
        },
    )


class RestorationConfig(BaseModel):
    enabled: bool = Field(
        default=False,
        title="启用人脸画质修复",
        description=(
            "开启可选的画质修复步骤，在识别前尝试对过小或低清晰度的人脸头像进行清晰化处理。\n\n"
            "默认关闭（关闭时零开销）。修复结果绝不会参与人脸聚类：它仅额外生成一份 'restored' 特征向量，"
            "并在修复前后长相偏差过大时打上质检标记，用于辅助复核。除非你明确配置好了该用途，否则保持关闭即可。"
        ),
        json_schema_extra={
            "details": (
                "需要安装 [restore] 可选依赖（它会锁定旧版 torch/torchvision，目前与 GPU 依赖不兼容，仅支持 CPU 推理）"
                "以及内置的 CodeFormer 模型；缺少这些依赖会在启动或处理第一张人脸裁切图时报错。"
                "开启后会填充 'restored' 特征变体，并在偏差超标时生成 restore_disagreement 审核标记。"
            )
        },
    )
    trigger_px: int = Field(
        default=80,
        title="触发修复的人脸尺寸上限（像素）",
        description=(
            "尺寸小于此值的人脸，无论本身画质如何都会触发修复。\n\n"
            "默认 80，实用范围 40–160。调高会把中等尺寸的人脸也纳入修复（耗时增加，且对原本清晰的人脸有过度脑补改脸的风险）；"
            "调低则只针对真正极小的人脸头像进行修复。"
        ),
        json_schema_extra={
            "details": (
                "按检测框较短边计算，并与下方的画质百分位门槛取并集（OR），因此尺寸触发区间大致为 [detection.min_face_px, trigger_px)。"
                "可结合 faces.restored=1 与边框尺寸观察实际被修复的裁切图范围。"
            )
        },
    )
    quality_percentile: float = Field(
        default=15.0,
        title="画质修复百分位阈值",
        description=(
            "除了过小的人脸外，每批人脸中画质最差的那一部分也会被修复——此项即设置该比例（百分比）。\n\n"
            "默认 15.0，范围 0–100。调高可扩大修复覆盖面（同时增加算力开销和模型脑补失真风险）；"
            "调低则只修复最糊的极少数人脸；设为 0 基本等同于关闭此条件，仅保留尺寸触发。"
        ),
        json_schema_extra={
            "details": (
                "画质以 MagFace 特征向量的模长（norm）衡量，且按批次取相对分位而非绝对阈值——即使整批人脸都挺清晰，"
                "仍会有固定比例进入修复。由于批次构成会影响分位点，请在具有代表性的批次上评估效果。"
            )
        },
    )
    fidelity: float = Field(
        default=0.7,
        title="修复保真度权重",
        description=(
            "控制画质修复在多大程度上忠实于原始五官。数值越高越贴近原貌但增强幅度较小；"
            "数值越低画面越精致，但可能不知不觉把人脸修成另一个人。\n\n"
            "范围 0–1；默认 0.7 偏向保真，这正适合人脸识别流程。这是防止过度修复的核心旋钮——"
            "如果调低后导致大量人脸触发 disagreement_cos 告警，说明模型正在凭空捏造五官特征，请回调高一些。"
        ),
        json_schema_extra={
            "details": "对应 CodeFormer 的保真度权重 w。由于修复后的特征绝不会输入聚类，可放心做 A/B 对比测试。"
        },
    )
    disagreement_cos: float = Field(
        default=0.30,
        title="修复偏差余弦告警阈值",
        description=(
            "修复后的人脸与原图差异达到多少时，交给人工复核。\n\n"
            "默认 0.30，实用范围约 0.1–0.6。调低可更早捕获细微的身份漂移（但审核队列会变大）；"
            "调高则只标记明显换了张脸的严重偏差。"
        ),
        json_schema_extra={
            "details": (
                "按「1 − 余弦相似度（修复前后特征之间）」计算，因此 0.30 约等于余弦相似度 0.70（理论最大值 2.0）。"
                "该参数直接充当「修复是否把人修歪了」的检测器——请与 fidelity 协同调优，并关注 restore_disagreement 队列数量。"
            )
        },
    )


class ClusteringConfig(BaseModel):
    knn_k: int = Field(
        default=64,
        title="kNN 近邻数量",
        description=(
            "在做人脸聚类分组时，每张人脸最多与多少张最相似的候选人脸进行比对。\n\n"
            "常见范围 20–128，默认 64。设得过低会导致出现在数百张照片中的高频人物被拆成碎片（再调阈值也救不回来）；"
            "设得过高则会引入错误人物候选，并使计算开销呈平方级增长。建议逐步调高，直到 `eval` 中的召回率（bcubed_recall）不再提升为止。"
        ),
        json_schema_extra={
            "details": (
                "构建余弦相似度 kNN 图时为每张人脸检索的最近邻个数——它决定的是图的连通度上限，而不是单个分组的人数上限。"
                "与 edge_threshold 不同，修改此项（或 fusion_weights）会使近邻图缓存失效并触发完整重算。"
            )
        },
    )
    edge_threshold: float = Field(
        default=0.50,
        title="相似度连边阈值",
        description=(
            "两张人脸至少要有多像，才会被归为同一个人。这是整套人脸聚类分组中最关键的一个参数。\n\n"
            "范围 0–1，常用甜点区约 0.40–0.60，默认 0.50。过低会让微弱的误连像连锁反应一样把不同人串成超大混合分组；"
            "过高则会因角度、年龄、光线差异把同一个人拆成很多零散分组。没有任何有效连边的人脸会各自形成单张分组。"
        ),
        json_schema_extra={
            "details": (
                "Chinese Whispers 所运行的相似度图保留连边的余弦相似度下限；HDBSCAN 会忽略此参数。"
                "它是调优成本最低的参数，因为改动它不会让 kNN 图缓存失效——可用 `recluster --set` 或 `eval grid-search` 扫描，"
                "观察 bcubed 精确率与召回率的权衡曲线。"
            )
        },
    )
    algorithm: Literal["chinese_whispers", "hdbscan"] = Field(
        default="chinese_whispers",
        title="聚类分组算法",
        description=(
            "将人脸自动归类成人物所采用的算法。\n\n"
            "'chinese_whispers'（默认）会为每张人脸分配一个分组，主要通过 edge_threshold 调节——速度快且无需额外依赖。"
            "'hdbscan' 则会把稀疏区域的孤立人脸直接判为噪声：分组纯度（精确率）更高，但召回率更低、孤立人脸更多，主要通过 min_cluster_size 调节。"
        ),
        json_schema_extra={
            "details": (
                "chinese_whispers 是在阈值裁剪后的相似度图上执行迭代标签传播。"
                "hdbscan 属于密度聚类，需要安装可选的 hdbscan 依赖，且会忽略 edge_threshold 与 cw_iterations。"
                "可通过 `eval grid-search` 在同一留出集上对比两者——近邻图缓存可直接复用，A/B 测试成本极低。"
            )
        },
    )
    cw_iterations: int = Field(
        default=30,
        title="Chinese Whispers 迭代轮数",
        description=(
            "默认聚类算法在停止前对全部人脸执行标签传播的遍历轮数。\n\n"
            "常见范围 10–50，默认 30 已经留有充足余量。轮数过少会导致本该合并的人物没合并到位；"
            "轮数过多只会多花一点时间，绝不会引起过度合并。HDBSCAN 算法会忽略此项。"
        ),
        json_schema_extra={
            "details": (
                "固定的标签传播扫描次数，无提前停止机制——每次必然跑满指定轮数。图的拓扑结构完全由 edge_threshold 决定，不受此项影响。"
                "可用 `recluster --set clustering.cw_iterations=N` 验证：若 30 到 40 轮之间分组结果仍有变动则调高；若 15 轮以上结果就完全一致则可调低。"
            )
        },
    )
    min_cluster_size: int = Field(
        default=2,
        title="HDBSCAN 最小分组人脸数",
        description=(
            "使用 HDBSCAN 算法时，至少需要几张人脸才能成立为一个分组。在默认的 chinese_whispers 算法下此项无效。\n\n"
            "默认 2（最小值），可获得最高召回率。调高至 3–5 可得到更纯净的分组，代价是只出现过两三张照片的真实人物会被归为噪声。"
            "如果你想控制「发现新人物」建议所需的最小人脸数，请调整 crossref.new_person_min_faces。"
        ),
        json_schema_extra={
            "details": (
                "规模小于该值的连通分量会被剪枝标记为噪声，同时该值也作为 min_samples 使用，因此数值越大被标为噪声的人脸越多。"
                "小于 2 的整数会自动向上截断为 2。"
            )
        },
    )
    seed: int = Field(
        default=42,
        title="Chinese Whispers 随机种子",
        description=(
            "用于让多次重复运行得出完全一致结果的固定数值。这不是质量调节项——保持默认即可。\n\n"
            "固定种子（默认 42）能保证审核队列可复现、网格搜索结果可对比。仅在排查聚类稳定性时才需要更换它："
            "如果换一个种子分组结果就大幅震荡，说明相似度图连边过密，应该调高 edge_threshold，而不是去碰运气找一个「好种子」。"
        ),
        json_schema_extra={
            "details": (
                "控制 Chinese Whispers 每轮迭代访问节点的随机顺序；HDBSCAN 不使用此项。"
                "不同种子间方差过大通常意味着相似度图正处在渗流临界点附近。"
            )
        },
    )
    fusion_weights: dict[str, float] = Field(
        default_factory=dict,
        title="各识别模型融合权重",
        description=(
            "判定两张人脸是否相似时，各个特征提取模型所占的权重。留空（默认）表示所有模型权重相等。\n\n"
            "以模型名称为键（如 arcface、adaface、magface）；未列出的模型默认权重为 1.0，只有相对比例起作用。"
            "如果某个模型在你的照片库上噪声较大，可将其权重调近 0 加以抑制——但把权重过度集中在单一模型上会失去多模型集成的优势。"
        ),
        json_schema_extra={
            "details": (
                "融合前会对各模型的特征向量块分别做 L2 归一化，因此每个模型对最终相似度的贡献占比与「权重平方（weight²）」成正比。"
                "修改任意权重都会使近邻图缓存失效。调参请结合 `recluster --set` 与 `eval holdout`（观察 bcubed_f1），"
                "并确保键名与数据库 embeddings 表中的模型名完全一致。"
            )
        },
    )


class CrossrefConfig(BaseModel):
    majority: float = Field(
        default=0.60,
        title="多数票比例",
        description=(
            "一个人脸分组里，已有群晖人物标签的人脸需要有多高比例指向同一个人，Synopticon 才会认定整个分组就是该人物。\n\n"
            "常见范围约 0.50–0.80；默认 0.60 在 min_labeled=3 时可容忍 1 张贴错标签的人脸。"
            "如果出现把人脸错配给他人的「归属认领」建议，请调高；如果标注良好、内部一致的分组完全不出建议，请调低。过低也会增加误合并风险。"
        ),
        json_schema_extra={
            "details": (
                "分母仅统计该分组中已关联到群晖可见人物列表（listed persons）的人脸；群晖隐藏/未列出人物不参与此处投票"
                "（但仍参与 merge_vote_fraction）。需与 min_labeled 配合生效。"
                "该映射结果直接把关归属认领（assign）、基于分组的改判人物（reassign）以及跨分组合并。"
            )
        },
    )
    min_labeled: int = Field(
        default=3,
        title="最少已有标签人脸数",
        description=(
            "一个人脸分组中，至少要有多少张人脸已在群晖照片里标好人物，Synopticon 才采信其多数票结论。\n\n"
            "合理范围 2–6，默认 3。设为 1 时，单张已标人脸就会决定整组归属，非常脆弱。"
            "如果分组经常因一两张标错的人脸而被整组映射错人，请调高；如果你的图库标注非常稀疏、真实分组很难凑够 3 张已标人脸，可向 2 调低。"
        ),
        json_schema_extra={
            "details": (
                "仅计入已关联到群晖可见人物列表的标签。低于此数量时，分组不映射到任何人物——不会生成归属认领，也不会触发跨分组合并。"
                "同时它也是改判人物（reassign）的留一法支持度下限，以及某人物成为「最近邻人物」匹配目标所需的最低已标人脸数。"
            )
        },
    )
    min_cohesion: float = Field(
        default=0.38,
        ge=-1.0,
        le=1.0,
        title="最小分组内聚度",
        description=(
            "一个人脸分组内部的人脸平均至少要有多相似，Synopticon 才会相信这组脸确实属于同一个人。\n\n"
            "实用范围 0.30–0.42，默认 0.38。它能防止一大堆模糊或半遮挡人脸凑成的「大杂烩分组」因为里面混了几张已标人脸而被整组误贴上名字。"
            "如果某个人物突然冒出成百上千条离谱建议，请调高；如果某个照片极多的人物分组突然不再产出任何建议，请调低。设为 -1 可关闭此检查。"
        ),
        json_schema_extra={
            "details": (
                "计算方式为分组内所有融合特征向量的两两平均余弦相似度，范围 [-1, 1]，存储于 clusters.cohesion。"
                "在 majority 和 min_labeled 之上叠加校验；未达标分组不映射任何人物，其中的未标人脸会转交「最近邻人物」步骤单独挽救。"
                "它与 edge_threshold 处于同一特征空间，调整 fusion_weights 后请一并复核此项。"
                "真实人物的大型分组内聚度通常最低：拥有数百张人脸的人物大约在 0.41 左右。"
            )
        },
    )
    assign_sim: float = Field(
        default=0.55,
        title="归属认领相似度门槛",
        description=(
            "匹配把握度达到多少时，才作为高把握的「归属认领」直接提出，否则降级为「低置信度复核」。\n\n"
            "实用范围 0.40–0.70，默认 0.55。无论高于还是低于此值都会进入人工审核——它只决定人脸进入哪个审核队列，"
            "同时也是人脸审核界面展示的置信度分值。如果 assign（归属认领）队列混入了错误人脸，请调高；"
            "如果大量正确人脸被压在 low_confidence（低置信度复核）里，请调低。"
        ),
        json_schema_extra={
            "details": (
                "未标人脸与所属分组内所有已标人脸的平均余弦相似度，范围 [-1, 1]。"
                "同时也充当改判人物（reassign）建议的最低过滤线，低于此值的改判主张会被当作噪声丢弃。"
            )
        },
    )
    new_person_min_faces: int = Field(
        default=5,
        title="发现新人物最少人脸数",
        description=(
            "一个完全未知的人物至少需要积累多少张人脸，Synopticon 才会建议为 Ta 创建新人物。\n\n"
            "默认 5，合理范围 3–15。如果「发现新人物」队列里塞满了无效人脸（模糊脸、残缺脸或只路过一次的陌生人），请调高；"
            "如果经常出镜但照片不多的新面孔被漏掉了，请调低。此项与按不同照片数统计的 new_person_min_photos 配合生效。"
        ),
        json_schema_extra={
            "details": (
                "作用于完全无群晖标签（零匹配）分组的规模下限，而非相似度阈值——用于筛除零散的疑似伪分组。"
                "该队列的纯净度很大程度上取决于上游聚类的内聚质量。"
            )
        },
    )
    new_person_min_photos: int = Field(
        default=8,
        title="发现新人物最少照片数",
        description=(
            "一个完全未知的人物至少需要出现在多少张不同的照片里，Synopticon 才会建议为 Ta 创建新人物。\n\n"
            "默认 8，合理范围 2–15。连拍一组几乎一样的照片很容易让偶遇路人凑够人脸数，但实际上只是同一个瞬间，因此用此项额外要求跨照片出现。"
            "如果只出现在少数几张照片里的熟人被漏掉，可适当调低。"
        ),
        json_schema_extra={
            "details": (
                "统计分组内人脸所属的不同 (space, photo_id) 数量，并与 new_person_min_faces 同时生效——分组必须同时满足两项门槛。设为 1 可禁用此限制。"
            )
        },
    )
    merge_vote_fraction: float = Field(
        default=0.30,
        title="同组多标签合并投票比例",
        description=(
            "当同一个人脸分组里混有两个不同的群晖人物标签时，每个人物至少要占组内多少比例，Synopticon 才会判断群晖把同一个人拆成了两个并建议合并。\n\n"
            "范围约 0.20–0.50；默认 0.30（刻意低于 0.5，这样单个分组也能同时提名超过两个并列主导的人物）。"
            "调高可减少合并建议、提升把握度；调低能抓出更多被群晖拆散的人物，但可能因个别贴错标签的人脸触发误合并。"
        ),
        json_schema_extra={
            "details": (
                "第一种合并触发机制（分组内触发）。调优时请关注 merge（合并未命名分组）与 merge_named（合并已命名人物）队列中的误合并情况。"
            )
        },
    )
    merge_centroid_sim: float = Field(
        default=0.60,
        title="跨分组合并质心相似度",
        description=(
            "两个独立的人脸分组平均下来至少要有多像，Synopticon 才会建议把它们对应的两个群晖人物合并为同一个人。\n\n"
            "实用范围 0.50–0.75；默认 0.60（低于单脸对单脸的阈值，因为平均脸的特征区分度略低）。"
            "调高则只合并几乎一模一样的分组；如果同一个人明显散落在多个分组里却从未生成合并建议，请调低。"
        ),
        json_schema_extra={
            "details": (
                "第二种合并触发机制（跨分组触发）——当两个映射到*不同*人物的分组，其平均特征质心的余弦相似度高于此值（范围 [-1, 1]）时触发。"
                "请与 merge_vote_fraction 联合调优，以综合误合并率为准绳。两类合并建议在真正写回群晖前，都仍需要显式开启写回开关确认。"
            )
        },
    )
    nearest_person_sim: float = Field(
        default=0.55,
        title="最近邻人物相似度门槛",
        description=(
            "当某张人脸无法依靠所属分组确定身份时，它单凭自身与某位人物已标人脸的相似程度达到多少，Synopticon 才会直接推荐归属给该人物。\n\n"
            "实用范围 0.50–0.65，默认 0.55。它能挽救被聚类落单的人脸（常见于小图或单人照），"
            "也能纠正被群晖贴错人名——或塞进群晖从未展示出来的隐藏未命名人物里——的人脸。"
            "调低可找回更多人脸；如果推荐经常出错，请调高。设为 1.0 可关闭此功能。"
        ),
        json_schema_extra={
            "details": (
                "分值为该人脸与同一空间内某人物最接近的 5 张群晖已标人脸的平均余弦相似度（不含自身，范围 [-1, 1]），且仅限 SCRFD 确认的人脸参与。"
                "所属分组未映射任何人物的未标人脸，会进入 low_confidence（低置信度复核）队列；"
                "已标人脸若最佳匹配不是当前群晖人物（且其分组未映射到当前群晖人物），则会进入 reassign（改判人物）队列"
                "（写回时通过拆分移动，需显式开启 --apply-reassigns）。两类建议数据均附带 nearest_person.margin 与 runner_up_person_id 字段。"
            )
        },
    )
    nearest_person_margin: float = Field(
        default=0.08,
        title="最近邻人物领先优势差",
        description=(
            "最佳匹配人物必须比第二接近的候选人物高出多少相似度，才允许提出上述建议。\n\n"
            "实用范围 0.05–0.15，默认 0.08。专门用来避免长得像的人（如兄弟姐妹、双胞胎）混进审核队列。"
            "如果建议经常把某两个人搞混，请调高；想要挽救更多落单人脸，请调低。"
        ),
        json_schema_extra={
            "details": (
                "最佳候选人与第二候选人之间在最近邻人物得分（见 nearest_person_sim）上的余弦差值。"
                "如果当前空间中只有一个候选人物，则不存在第二名，仅凭相似度即可通过。"
            )
        },
    )
    proposal_kinds: list[ProposalKind] = Field(
        default_factory=lambda: [
            "assign", "low_confidence", "reassign", "merge", "merge_named", "new_person"
        ],
        title="启用的识别建议类型",
        description=(
            "指定「人脸聚类分组」后要把哪些类型的识别建议加入审核队列。取消勾选不关心的类型后，系统将不再生成此类建议。\n\n"
            "assign（归属认领）：将未标人脸标为已知人物；low_confidence（低置信度复核）：同上但把握度较低；"
            "reassign（改判人物）：修正群晖标错人物的人脸；merge（合并未命名分组）：合并至少一方未命名的两个人物；"
            "merge_named（合并已命名人物）：合并两个均已命名的人物；new_person（发现新人物）：为反复出现的陌生面孔建议新建人物。"
            "取消勾选不会删除审核队列中已有的历史建议。"
        ),
        json_schema_extra={
            "details": (
                "仅在入库持久化阶段过滤：交叉比对计算本身仍会完整运行，因此 predicted_person 及其他类型不受影响。"
                "被屏蔽的建议不会记录在任何地方，重新勾选该类型并在下次运行「人脸聚类分组」时便会重新生成。"
            )
        },
    )


class SecurityConfig(BaseModel):
    """Web 界面的登录与访问防护：控制允许谁访问、防止密码暴力破解以及记录登录审计日志。"""

    # -- who the client is -------------------------------------------------- #
    trusted_proxies: list[str] = Field(
        default_factory=list,
        title="受信任的反向代理",
        description=(
            "部署在 Synopticon 前方的反向代理服务器地址或网段（如 '192.168.1.2'、'172.18.0.0/16'）。"
            "除非你确实使用了反向代理，否则请保持为空——留空才是最安全的默认配置。\n\n"
            "Synopticon 根据请求来源 IP 识别每一位访客。在反向代理后方，直接来源 IP 会变成代理自身，"
            "因此必须告知哪些代理有权传递真实访客 IP。将代理加入此处后，它也能正确报告连接使用了 HTTPS，从而让登录 Cookie 启用 Secure 安全标记。\n\n"
            "在填写之前，务必先确保反向代理会「覆盖」而非原样透传访客的请求头。以 nginx 为例，关键配置只有一行："
            "proxy_set_header X-Forwarded-For $remote_addr; —— 否则任意访客都可以伪造任意 IP，"
            "直接绕过 IP 白名单和按地址生效的登录限流。Caddy 和 Traefik 默认已经做了正确处理。\n\n"
            "只填写完全受你控制的代理：列表中的任何地址都可以声称自己是任意访客。"
        ),
        json_schema_extra={
            "details": (
                "使用 ipaddress.ip_network(strict=False) 解析；单个 IP 等同于 /32 或 /128。"
                "由 clientip.ProxyHeaders ASGI 中间件生效：仅当直连对端命中此列表时，才从右向左越过受信任节点解析逗号分隔的 "
                "X-Forwarded-For / X-Forwarded-Proto 请求头，将解析出的单一客户端地址写入 scope['synopticon.client']，而不修改原 scope['client']。"
                "uvicorn 自身的 proxy_headers 已被显式设为 False（它默认开启并信任回环地址，此前甚至曾以 forwarded_allow_ips='*' 运行，"
                "导致相信任何来源的请求头）。\n\n"
                "具体风险在于：一旦某个对端被列入信任，它发来的请求头中最右侧的条目就会被采信。"
                "nginx 默认会将客户端原请求头转发给上游，因此只有 `location { proxy_pass ... }` 而没写 proxy_set_header 时，"
                "访客自己伪造的 X-Forwarded-For 会被原封不动送到 Synopticon，致使 IP 白名单判定、两级登录限流的计数键以及会话绑定的网络校验全部被攻击者控制。"
                "务必配置代理「覆盖」该请求头（proxy_set_header X-Forwarded-For $remote_addr），切勿原样传递访客值（$http_x_forwarded_for）。"
                "使用追加写法（$proxy_add_x_forwarded_for）在本中间件的从右向左解析下也是安全的，因为客户端前置伪造的值不会成为最右侧的非受信任条目。"
                "Synopticon 无法（也不会尝试）区分正确覆盖与伪造头：两者看起来都是单条记录。"
                "如果代理根本没有转发客户端地址，所有访客都会被识别成代理自身 IP 并共享同一个限流额度，此时启动时会输出警告，且会在「系统设置 → 账号与权限」中提示。\n\n"
                "请仅列出代理本身的地址：解析时会跳过本列表中的所有地址，如果填了包含真实访客的宽泛网段，网段内的访客就能伪造其左侧条目。"
                "把回环地址加入列表却不配置请求头覆盖，比什么都不填更危险。此列表绝不会豁免任何登录限流——登录限流没有任何例外。"
                "仅在服务启动时读取；修改后需重启生效。"
            )
        },
    )

    # -- network allowlist -------------------------------------------------- #
    allow_from: list[str] = Field(
        default_factory=list,
        title="允许访问的 IP 白名单",
        description=(
            "限制哪些 IP 地址或网段可以访问 Web 界面。留空（默认）表示允许所有地址访问。\n\n"
            "填入具体地址或网段（如 '192.168.1.50'、'192.168.1.0/24'、'2001:db8::/32'）后，"
            "名单之外的所有请求都会被直接拒绝，连登录页都看不到。\n\n"
            "无论此处如何配置，本机回环地址（localhost）始终放行，确保你永远可以通过服务器本地终端或 SSH 隧道进入，不会被锁在外面。"
        ),
        json_schema_extra={
            "details": (
                "对每一个请求生效——包括页面、API、人脸裁切图和前端资源包——而不仅仅限于登录页，"
                "因此即便会话 Cookie 或访问密钥泄露，在白名单外的地址也无法使用。唯一例外是 GET /api/health，以保证容器健康检查正常工作。"
                "在反向代理后方，白名单的可靠性完全取决于 trusted_proxies：未受信任的代理，或未转发客户端地址的本机代理，"
                "会让所有请求都看似来自代理本身；而列入信任却未覆盖 X-Forwarded-For 的代理则会让访客随意伪装 IP。"
                "处于前两种情况时，Synopticon 会直接拒绝保存白名单，以免造成看似生效的假象；第三种情况则会在启动时警告。"
                "启用前请先到「系统设置 → 账号与权限」核对「当前浏览器」识别出的地址。"
                "仅在启动时读取，修改后需重启生效；若不慎锁死，可在命令行执行 `synopticon web-access --clear` 并重启以恢复访问。"
            )
        },
    )
    allow_private_networks: bool = Field(
        default=True,
        title="始终允许局域网访问",
        description=(
            "即使配置了上方的 IP 白名单，也始终放行家庭和办公局域网段——包括 10.x、172.16–31.x、192.168.x 及其 IPv6 内网地址。\n\n"
            "默认开启，防止你在开启白名单屏蔽公网时不小心把自己的内网设备也锁在门外。"
            "仅当你打算连局域网内部也要做精细限制时才关闭它，且关闭前请务必先在上方白名单中填好允许的具体地址。"
        ),
        json_schema_extra={
            "details": (
                "涵盖 10.0.0.0/8、172.16.0.0/12、192.168.0.0/16、100.64.0.0/10（运营商级 NAT）、169.254.0.0/16、fc00::/7 与 fe80::/10。"
                "本机回环地址无条件放行，不受此开关控制。开启此项且上方白名单全为局域网地址时，白名单实际上不会拦截局域网内的任何设备，"
                "「系统设置 → 账号与权限」也会明确提示。此项仅影响 IP 白名单，不影响登录限流——登录限流不对任何地址豁免。"
            )
        },
    )

    # -- login throttling --------------------------------------------------- #
    max_failures_per_address: int = Field(
        default=20, ge=0, le=1000,
        title="单地址登录失败次数上限",
        description=(
            "同一个来源地址在下方统计窗口内最多允许登录失败多少次，超限后将被暂时拦截。"
            "这能有效阻止攻击者批量枚举用户名：猜错 20 个用户名与猜错 20 次密码消耗同等额度。\n\n"
            "此处的「地址」按整个家庭网络出口归并：IPv4 按 /24 网段、IPv6 按 /64 前缀统计（因为单个 IPv6 访客可轮换数千个地址）。"
            "一旦成功完成登录，会精准退还该次此前消耗的失败次数，所以正常频繁登录绝不会误触发拦截。\n\n"
            "该限制对所有地址一视同仁，包括服务器本机以及前方的反向代理，没有任何豁免："
            "在常见的「本机运行 Synopticon + 前置反代」架构中，一旦豁免「服务器自身」，就等于豁免了公网上的每一个访客。\n\n"
            "如果多人共用同一出口（如办公室，或尚未加入受信任列表的反向代理），他们会共享同一份额度，请酌情调高或正确配置受信任反向代理。"
            "设为 0 可关闭按地址封禁，仅保留针对「单地址 + 单用户名」的渐进延迟减速。"
        ),
        json_schema_extra={
            "details": (
                "采用基于 deque(maxlen=N) 的滑动时间窗口记录尝试时间戳，按 clientip.ip_prefix 归并，每个地址仅占 N 条 (float, key) 记录。"
                "计数达到 N 即触发封禁；设为 0 关闭该层级。统计涵盖所有用户名及所有认证步骤（密码、验证码、创建账号、二次确认）中的失败与结果未知尝试。"
                "登录成功后仅精确退还该 (address, username) 组合自上次成功以来计入的条目——每条窗口记录均带有归属键，绝不会错误退还他人的失败计数。"
                "任何地址、任何场景都不会跳过检查，代码中不存在绕过路径：throttle.verdict 不接受信任参数，仅读取 ResolvedClient 的 ip 字段。"
            )
        },
    )
    address_window_minutes: int = Field(
        default=5, ge=1, le=1440, title="失败统计窗口（分钟）",
        description="上方「单地址登录失败次数上限」所统计的时间窗口长度。",
    )
    address_block_minutes: int = Field(
        default=5, ge=1, le=1440, title="地址封禁时长（分钟）",
        description="触发失败次数上限后，该地址被拒绝登录尝试的持续时间。",
        json_schema_extra={
            "details": (
                "限流器会在「自身衰减间隔」与「封禁时长 + 统计窗口」两者取较长值之后才清理空闲地址记录，"
                "因此攻击者无法通过暂时停手来提前缩短长封禁时间。正因这一设计，此字段的上限无需受衰减间隔约束。"
            )
        },
    )

    # -- sign-in log -------------------------------------------------------- #
    sign_in_log: bool = Field(
        default=True,
        title="记录登录日志",
        description=(
            "记录每一次登录尝试——包括时间、输入的用户名、来源地址以及是否成功，可在「系统设置 → 账号与权限」中查看。"
            "关闭后仅停止记录新日志，不会删除已有记录。"
        ),
        json_schema_extra={
            "details": (
                "日志写入数据库表 web_auth_log。启动时一次性读取至 authlog.configure()，每次 record_attempt 写入前都会检查该状态，因此关闭需重启后生效。"
                "关闭同时也会停用每小时一次的日志清理任务，确保已有历史记录被原样保留而不会被后台悄悄过期删除。"
                "密码、会话 Cookie 和访问密钥绝不会以任何形式写入日志，且系统不会读取该日志来做安全判定。"
                "日志写入采用尽力而为策略：遇到数据库写入异常会静默忽略而不中断登录请求，因此在高并发写入争用时偶发漏记属正常现象。"
            )
        },
    )
    sign_in_log_days: int = Field(
        default=90, ge=0, le=3650, title="日志保留天数",
        description="每条登录日志的保留时长。设为 0 表示不按天数过期，仅在超出下方最大条数上限时淘汰旧记录。",
    )
    sign_in_log_max_entries: int = Field(
        default=5000, ge=0, le=1000000, title="日志最大保留条数",
        description=(
            "定期执行的登录日志条数上限，防止服务长期运行数年后日志无限膨胀。"
            "达到上限后，新记录写入时会逐步淘汰最旧的记录。设为 0 表示不限制条数。"
        ),
        json_schema_extra={
            "details": (
                "保留天数与最大条数在启动时通过 authlog.configure() 生效，由 Web 进程的调度线程在启动时及每小时执行一次联合清理，"
                "另外每满 1000 次写入也会兜底触发一次（先按天数清理，再按条数截断）。"
                "由于清理为周期性执行，两次清理之间表内行数可能短暂超过此值——它是目标上限而非硬性截断。5000 条记录大约占用 1 MB 空间。"
            )
        },
    )
    log_failed_api_keys: bool = Field(
        default=True,
        title="记录被拒的访问密钥",
        description=(
            "同时在登录日志中记录使用未知或已吊销访问密钥的失败请求。成功的密钥调用不会记录"
            "（密钥列表本身已展示每把密钥的最后使用时间），以免每隔几秒轮询一次的自动化脚本把日志刷屏。"
        ),
        json_schema_extra={
            "details": (
                "在 app.py 的 Bearer 认证失败分支写入前判断，关闭后完全不写日志。"
                "每个来源地址前缀每分钟最多记录一条拒绝日志，防止使用过期密钥的死循环客户端刷爆日志表。触发登录限流的请求也共用此节流门限。"
            )
        },
    )

    # -- two-step sign-in --------------------------------------------------- #
    totp_issuer: str = Field(
        default="Synopticon", title="验证器显示名称",
        description="在手机身份验证器 App 中显示在动态验证码旁边的服务名称。",
        json_schema_extra={
            "details": (
                "由 POST /api/auth/totp/start（路由 11）传给 totp.provisioning_uri，写入 otpauth:// 链接作为 issuer 和标签前缀。"
                "事后修改不会让已有验证器失效，但已添加的旧条目仍会保留修改前的名称。"
            )
        },
    )
    totp_skew_steps: int = Field(
        default=1, ge=0, le=3, title="时钟容差步数",
        description="允许当前时间前后各多少个 30 秒时间片内的动态验证码依然有效。",
        json_schema_extra={
            "details": (
                "设为 1 表示一个验证码在其时间片前后约 90 秒内均有效，足以容忍手机与服务器之间常见的时间偏移。"
                "调大会延长验证码被截获后的可利用窗口；设为 0 则要求两端时钟精准到秒级一致，在未配置 NTP 的 NAS 上通常容易导致无法登录。"
                "此外，同一时间片内已被使用过的验证码会被拒绝防重放——除非服务器自身时钟向后大幅跳变超过两小时（视为校时修正而非重放攻击）。"
            )
        },
    )
    login_challenge_ttl: int = Field(
        default=300, ge=60, le=900, title="两步验证限时（秒）",
        description="通过密码验证后，留给你输入两步验证码的最长有效时间。",
    )
    login_code_attempts: int = Field(
        default=5, ge=1, le=20, title="单次登录验证码尝试上限",
        description="输入多少次错误验证码后，必须退回密码步骤重新开始登录。",
        json_schema_extra={
            "details": (
                "记录在待验证的登录会话行上，独立于按地址生效的登录限流，且为精确计数：设为 5 表示允许提交 5 次校验，第 6 次起强制重新输入密码。"
                "这是防范 6 位动态码暴力猜测的硬性防线：没有它，单靠 1 秒延迟在有效窗口内仍可能被猜出过多组合。用尽次数后会立即销毁该待验证记录。"
            )
        },
    )
    recovery_code_count: int = Field(
        default=10, ge=5, le=20, title="备用恢复码数量",
        description="开启两步验证时一次性生成的单次有效备用恢复码个数。",
        json_schema_extra={
            "details": (
                "由路由 12 传给 twofactor.confirm_totp_enrolment 再交由 generate_recovery_codes 生成。"
                "开启时一次性生成 64 位随机串并以哈希形式存储——明文仅展示一次，丢失后只能重新生成替换而无法找回。"
                "任何需要输入验证码的场景（包括关闭两步验证）都可以直接输入任意一枚未用过的备用恢复码。"
            )
        },
    )

    @field_validator("allow_from", "trusted_proxies")
    @classmethod
    def _valid_networks(cls, v: list[str]) -> list[str]:
        for entry in v:
            try:
                ipaddress.ip_network(entry.strip(), strict=False)
            except ValueError as exc:
                raise ValueError(f"{entry!r} is not an IP address or CIDR range") from exc
        return [e.strip() for e in v]


class McpConfig(BaseModel):
    """供 AI 助手连接并协助调优、排查 Synopticon 问题的接口配置。"""

    enabled: bool = Field(
        default=False,
        title="允许 AI 助手连接",
        description=(
            "开启 /mcp 接口，允许 AI 助手（如 Claude Code 或任意 MCP 客户端）查看你的配置、调优参数、"
            "运行处理步骤，以及诊断漏检或错分的人脸。默认关闭。\n\n"
            "未持有你在「系统设置 → 账号与权限」中亲手签发的访问令牌时，任何客户端都无法连接，且每枚令牌仅具备你授予的权限。"
            "向群晖 NAS 写回修改属于单独的可选授权，而需要手动输入确认短语的高危操作永远不会向 AI 助手开放。修改后需重启生效。"
        ),
        json_schema_extra={
            "details": (
                "在 Web 进程 /mcp 路径上提供基于 POST 的无状态 Streamable HTTP JSON-RPC 服务。关闭时所有请求在认证前即直接返回 404。"
                "MCP 令牌存放于 web_mcp_tokens 表，仅能用于 /mcp 而无法访问 /api/*；反之 REST API 密钥和浏览器会话 Cookie 也不能用于 /mcp。"
                "IP 白名单同样对此接口生效。该开关仅在启动时读取，且绝不允许通过 MCP 接口自身修改。"
            )
        },
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SYNOPTICON_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    nas: NasConfig = Field(default_factory=NasConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    inference: InferenceConfig = Field(default_factory=InferenceConfig)
    detection: DetectionConfig = Field(default_factory=DetectionConfig)
    restoration: RestorationConfig = Field(default_factory=RestorationConfig)
    clustering: ClusteringConfig = Field(default_factory=ClusteringConfig)
    crossref: CrossrefConfig = Field(default_factory=CrossrefConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Earlier sources win: init > env > .env file > toml.
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=_config_file()),
        )


def _config_file() -> Path | None:
    explicit = os.environ.get("SYNOPTICON_CONFIG")
    if explicit:
        return Path(explicit)
    for candidate in (
        Path("config.toml"),
        Path("data/config.toml"),  # the compose-mounted location, bare-metal view
        Path("/data/config.toml"),  # same location, in-container view
    ):
        if candidate.is_file():
            return candidate
    return None


def load_settings(**overrides) -> Settings:
    return Settings(**overrides)
