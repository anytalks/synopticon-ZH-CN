"""Shared onnxruntime session construction (CPU-first, optional CUDA / CoreML)."""

from __future__ import annotations

import functools
import subprocess
import sys
from pathlib import Path
from typing import Literal

from synopticon.cpu import available_cores, physical_cores  # noqa: F401  (re-exported)


@functools.lru_cache(maxsize=1)
def _apple_silicon_perf_cores() -> int | None:
    """Sum of non-Efficiency physical cores on Apple Silicon (Super + Performance).

    Heterogeneous Apple Silicon chips (e.g. M6 with 2 Super + 4 Performance +
    6 Efficiency cores) suffer barrier stalls when ONNX Runtime's CPU intra-op
    pool spans the slower Efficiency cores: benchmarking on M6 showed 6 threads
    is 1.6x-2.3x faster than 12 threads on SCRFD/YOLO/ResNet100. Returns None
    off macOS or on homogeneous CPUs.
    """
    if sys.platform != "darwin":
        return None
    try:
        n_levels = int(
            subprocess.check_output(["sysctl", "-n", "hw.nperflevels"], text=True, timeout=2).strip()
        )
    except Exception:  # noqa: BLE001
        return None
    if n_levels < 2:
        return None

    perf_total = 0
    saw_efficiency = False
    for lvl in range(n_levels):
        try:
            name = subprocess.check_output(
                ["sysctl", "-n", f"hw.perflevel{lvl}.name"], text=True, timeout=2
            ).strip()
            count = int(
                subprocess.check_output(
                    ["sysctl", "-n", f"hw.perflevel{lvl}.physicalcpu"], text=True, timeout=2
                ).strip()
            )
        except Exception:  # noqa: BLE001
            return None
        if name.lower() == "efficiency":
            saw_efficiency = True
        else:
            perf_total += count

    if saw_efficiency and perf_total > 0:
        return max(1, min(perf_total, available_cores()))
    return None


def default_intra_op_threads() -> int:
    """Default ONNX Runtime intra-op thread count when unconfigured."""
    return _apple_silicon_perf_cores() or physical_cores()


def session_device(session) -> str:
    """Human-readable device label ('GPU'/'CoreML'/'CPU') for an active ORT session.

    Reads the session's *active* providers, so an accelerator session that failed
    to init and fell back to CPU reports 'CPU' — the truth, not the request.
    """
    try:
        providers = session.get_providers()
    except Exception:  # noqa: BLE001 - never fatal; a label is not worth aborting for
        return "CPU"
    if "CUDAExecutionProvider" in providers:
        return "GPU"
    if "CoreMLExecutionProvider" in providers:
        return "CoreML"
    return "CPU"


def _coreml_cache_dir(model_path: Path | str, ort_version: str) -> str | None:
    """Per-model CoreML compiled artifact cache directory (cuts warm init ~2x)."""
    try:
        p = Path(model_path)
        size = p.stat().st_size
        base = (
            Path.home() / "Library" / "Caches" / "synopticon" / "coreml"
            if sys.platform == "darwin"
            else Path.home() / ".cache" / "synopticon" / "coreml"
        )
        cache_dir = base / ort_version / f"{p.stem}_{size}"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return str(cache_dir)
    except OSError:
        return None


_dlls_preloaded = False
_dll_dir_handles: list = []  # os.add_dll_directory drops the dir when its handle is collected


def _add_nvidia_dll_dirs(logger) -> None:
    """Put site-packages/nvidia/*/bin on the Windows DLL search path.

    `preload_dlls()` loads the top-level CUDA/cuDNN DLLs by absolute path but
    leaves the search path alone, and cuDNN 9 resolves its engine sub-libraries
    (`cudnn_engines_*64_9.dll`) by name at first use. Those miss, the first Conv
    fails, and ORT quietly reruns the session on CPU -- after session creation
    already reported CUDA. cuDNN loads them with the legacy search order, so the
    dirs go on PATH as well as through `add_dll_directory`.
    """
    import importlib.util
    import os

    try:
        spec = importlib.util.find_spec("nvidia")
    except (ImportError, ValueError):
        return
    if spec is None:
        return
    for root in spec.submodule_search_locations or ():
        for bin_dir in sorted(Path(root).glob("*/bin")):
            try:
                _dll_dir_handles.append(os.add_dll_directory(str(bin_dir)))
            except OSError as exc:
                logger.warning("could not add %s to the DLL search path (%s)", bin_dir, exc)
                continue
            os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")


def _preload_cuda_dlls(ort, logger) -> None:
    """Make onnxruntime-gpu's pip-installed CUDA/cuDNN wheels loadable.

    The `onnxruntime-gpu[cuda,cudnn]` wheels drop the NVIDIA libs under
    site-packages/nvidia/*/lib (*/bin on Windows), which the loader does not
    search by default -- without this the CUDA provider fails with
    `libcublasLt.so.12: cannot open shared object file` and silently falls back
    to CPU. `preload_dlls()` (ORT >= 1.21) loads them; on Windows the bin dirs
    must also be searchable (see `_add_nvidia_dll_dirs`). Best-effort and run
    once per process.
    """
    import sys

    global _dlls_preloaded
    if _dlls_preloaded:
        return
    _dlls_preloaded = True
    if sys.platform == "win32":
        _add_nvidia_dll_dirs(logger)
    preload = getattr(ort, "preload_dlls", None)
    if preload is None:  # older onnxruntime; rely on the system loader / LD_LIBRARY_PATH
        return
    try:
        preload()
    except Exception as exc:  # noqa: BLE001 - never fatal; CUDA will just fall back to CPU
        logger.warning("onnxruntime.preload_dlls() failed (%s); CUDA libs may not load", exc)


def create_session(
    model_path: Path | str,
    device: Literal["auto", "cpu", "cuda"] = "auto",
    intra_op_threads: int | None = None,
    device_id: int = 0,
    *,
    allow_coreml: bool = False,
):
    """Create an ort.InferenceSession honoring settings.inference.

    CPU is always the fallback. When device is 'cuda'/'auto' and the CUDA
    provider is compiled into the installed onnxruntime, CUDA is tried first
    (pinned to `device_id`); if the CUDA session fails to initialize -- a
    provider that's present but unusable, e.g. missing cuDNN or an out-of-memory
    GPU -- we log a warning and fall back to CPU rather than aborting the run.
    An explicit device='cuda' with no CUDA provider at all also warns.

    On macOS Apple Silicon, when `device == 'auto'` and `allow_coreml=True`
    (opted in by models verified compatible with CoreML MLProgram, i.e. fixed
    1x3x640x640 YOLOv8-face and 112x112 embedders, NOT dynamic-shape SCRFD),
    `CoreMLExecutionProvider` is tried with `ModelFormat=MLProgram` and an
    on-disk compiled-model cache, degrading cleanly to CPU on any failure.
    """
    import logging

    import onnxruntime as ort

    logger = logging.getLogger(__name__)
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = intra_op_threads or default_intra_op_threads()
    # Our detectors pad each image to a multiple of 32, so every distinct photo
    # dimension is a unique input shape. The CPU BFC arena extends on each new
    # shape and never returns memory to the OS, so RSS grows monotonically and
    # eventually a conv fails to allocate its activation buffer (~hundreds of MB)
    # thousands of photos into a run. Disabling the arena frees each allocation
    # after use -- slightly slower, but this is a batch/offline CPU pipeline where
    # runtime is not a constraint. (CUDA gets the equivalent fix via arena opts
    # below.)
    opts.enable_cpu_mem_arena = False
    # Silence per-inference "Expected shape ... does not match actual shape"
    # WARNINGs: our detectors export static output shapes but run on
    # variable-sized (padded) inputs, so VerifyOutputSizes flags every call.
    # The outputs are correct; keep Error/Fatal (3) visible.
    opts.log_severity_level = 3

    available = ort.get_available_providers()
    cuda_available = "CUDAExecutionProvider" in available
    if device in ("auto", "cuda") and cuda_available:
        _preload_cuda_dlls(ort, logger)
        # Disable memory pattern caching on variable-shape CUDA sessions so
        # distinct photo dimensions don't accumulate per-shape arena plans.
        opts.enable_mem_pattern = False
        # Our detectors feed variable-sized (padded to /32) inputs, so every
        # distinct photo dimension is a new input shape. With the CUDA provider's
        # default arena strategy (kNextPowerOfTwo, which never releases memory)
        # plus per-shape cuDNN conv workspaces, GPU memory grows monotonically
        # and OOMs after a few thousand photos. These options bound that growth:
        #   * kSameAsRequested extends the arena by exactly what's asked rather
        #     than doubling, so unique shapes don't compound waste.
        #   * cudnn_conv_use_max_workspace=0 stops each conv reserving max scratch.
        #   * HEURISTIC algo search avoids the default EXHAUSTIVE per-shape search
        #     (slow to warm up and allocates large search buffers per new shape).
        cuda_opts = {
            "device_id": device_id,
            "arena_extend_strategy": "kSameAsRequested",
            "cudnn_conv_use_max_workspace": "0",
            "cudnn_conv_algo_search": "HEURISTIC",
        }
        providers = [
            ("CUDAExecutionProvider", cuda_opts),
            "CPUExecutionProvider",
        ]
        try:
            return ort.InferenceSession(str(model_path), opts, providers=providers)
        except Exception as exc:  # noqa: BLE001 - degrade to CPU on any CUDA init failure
            logger.warning(
                "CUDAExecutionProvider present but session init failed (%s); using CPU", exc
            )
    elif device == "cuda":
        logger.warning(
            "inference.device='cuda' but CUDAExecutionProvider unavailable; using CPU"
        )

    if device == "auto" and allow_coreml and "CoreMLExecutionProvider" in available:
        coreml_opts: dict[str, str] = {
            "ModelFormat": "MLProgram",
            "MLComputeUnits": "ALL",
        }
        cache_dir = _coreml_cache_dir(model_path, getattr(ort, "__version__", "unknown"))
        if cache_dir:
            coreml_opts["ModelCacheDirectory"] = cache_dir
        try:
            return ort.InferenceSession(
                str(model_path),
                opts,
                providers=[("CoreMLExecutionProvider", coreml_opts), "CPUExecutionProvider"],
            )
        except Exception as exc:  # noqa: BLE001 - degrade cleanly to CPU on CoreML init failure
            logger.warning(
                "CoreMLExecutionProvider init failed for %s (%s); using CPU",
                Path(model_path).name,
                exc,
            )

    return ort.InferenceSession(str(model_path), opts, providers=["CPUExecutionProvider"])
