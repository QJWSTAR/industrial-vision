"""
look_up.py — CFD 查找表查询模块
Stage 3.3 v2.1：多维插值查询颗粒分布数据

用法：
    from repair_app.utils.look_up import ParticleLookup
    lu = ParticleLookup("cfd_data/")
    dist = lu.query(nozzle="round_30mm", standoff_mm=30, angle_deg=90,
                    position=(0, 0, 0))

    # dist 包含: velocity_mean, temperature_mean, diameter_mean, density
"""

from __future__ import annotations
import os
import glob
import threading
from typing import Optional
import numpy as np

# 仅加载数值数组键，跳过可能存在的 metadata object array
_NUMERIC_KEYS = (
    "grid_x", "grid_y", "grid_z",
    "density_3d", "velocity_mean_3d",
    "temperature_mean_3d", "diameter_mean_3d",
)


def _load_numeric_npz(path: str) -> dict[str, np.ndarray]:
    """安全加载 npz 文件，仅提取数值数组，跳过 object array。

    兼容新旧格式：新格式不含 metadata，旧格式含 metadata object array
    但通过按键加载避免触发 allow_pickle 错误。
    """
    with np.load(path, allow_pickle=False) as npz:
        return {k: npz[k] for k in _NUMERIC_KEYS if k in npz}


class ParticleLookup:
    """颗粒分布查找表。

    数据格式：cfd_data/nozzle_{name}_{standoff}mm.npz
    每文件含：grid_x, grid_y, grid_z, density_3d,
             velocity_mean_3d, temperature_mean_3d, diameter_mean_3d
    """

    def __init__(self, data_dir: str = "cfd_data") -> None:
        self._data_dir = data_dir
        self._cache: dict[str, dict] = {}
        self._cache_lock = threading.Lock()
        self._index: dict[tuple[str, int], str] = {}
        self._build_index()

    def _build_index(self) -> None:
        if not os.path.isdir(self._data_dir):
            return
        for f in glob.glob(os.path.join(self._data_dir, "nozzle_*.npz")):
            basename = os.path.basename(f).replace(".npz", "")
            parts = basename.split("_", 1)  # ["nozzle", "round_30mm"]
            if len(parts) < 2:
                continue
            rest = parts[1]  # "round_30mm"
            # 找最后的 _XXmm
            for suffix in ["mm"]:
                idx = rest.rfind("_")
                if idx < 0:
                    continue
                maybe = rest[idx + 1:]
                if maybe.endswith(suffix):
                    standoff_str = maybe.replace(suffix, "")
                    try:
                        standoff = int(float(standoff_str))
                    except ValueError:
                        continue
                    nozzle = rest[:idx]
                    self._index[(nozzle, standoff)] = f
                    break

    def query(
        self,
        nozzle: str = "round_30mm",
        standoff_mm: float = 30.0,
        angle_deg: float = 90.0,
        position: tuple[float, float, float] = (0.0, 0.0, 0.0),
    ) -> dict[str, float]:
        """查询某空间位置的颗粒分布参数。

        angle_deg: 喷涂角度 (目前简化处理)
        position: (x, y, z) 查询位置
        """
        # 输入验证：nozzle 作为文件名组成部分，需防止路径遍历
        if not nozzle or ".." in nozzle or "/" in nozzle or "\\" in nozzle:
            return {
                "density": 0.0,
                "velocity_mean": 0.0,
                "temperature_mean": 0.0,
                "diameter_mean": 0.0,
            }
        standoff_key = int(round(standoff_mm))
        key = (nozzle, standoff_key)

        with self._cache_lock:
            if key in self._cache:
                data = self._cache[key]
            elif key in self._index:
                data = _load_numeric_npz(self._index[key])
                self._cache[key] = data
            else:
                # 返回零值
                return {
                    "density": 0.0,
                    "velocity_mean": 0.0,
                    "temperature_mean": 0.0,
                    "diameter_mean": 0.0,
                }

        # 三线性插值
        px, py, pz = position
        gx = data["grid_x"]
        gy = data["grid_y"]
        gz = data["grid_z"]

        ix = np.searchsorted(gx, px) - 1
        iy = np.searchsorted(gy, py) - 1
        iz = np.searchsorted(gz, pz) - 1

        ix = max(0, min(ix, len(gx) - 2))
        iy = max(0, min(iy, len(gy) - 2))
        iz = max(0, min(iz, len(gz) - 2))

        def _interp(arr3d):
            # 取周围 3x3x3 邻域的均值（简单抗锯齿）
            x0, x1 = max(0, ix-1), min(arr3d.shape[0], ix+2)
            y0, y1 = max(0, iy-1), min(arr3d.shape[1], iy+2)
            z0, z1 = max(0, iz-1), min(arr3d.shape[2], iz+2)
            patch = arr3d[x0:x1, y0:y1, z0:z1]
            return float(np.mean(patch))

        return {
            "density": _interp(data["density_3d"]),
            "velocity_mean": _interp(data["velocity_mean_3d"]),
            "temperature_mean": _interp(data["temperature_mean_3d"]),
            "diameter_mean": _interp(data["diameter_mean_3d"]),
        }

    def get_jet_profile(
        self,
        nozzle: str = "round_30mm",
        standoff_mm: float = 30.0,
        n_samples: int = 200,
    ) -> dict[str, np.ndarray]:
        """获取整个射流截面的颗粒分布（用于可视化）。"""
        standoff_key = int(round(standoff_mm))
        key = (nozzle, standoff_key)

        if key in self._cache:
            data = self._cache[key]
        elif key in self._index:
            data = _load_numeric_npz(self._index[key])
            self._cache[key] = data
        else:
            return {"x": np.array([]), "y": np.array([]), "velocity": np.array([])}

        gx = data["grid_x"]
        gy = data["grid_y"]
        gz = data["grid_z"]
        v3d = data["velocity_mean_3d"]

        # 取 z 方向中心截面
        z_mid = len(gz) // 2
        v_slice = v3d[:, :, z_mid]

        return {
            "x": gx.copy(),
            "y": gy.copy(),
            "velocity": v_slice.astype(np.float32),
        }
