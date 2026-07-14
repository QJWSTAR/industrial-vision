# MATLAB 集成架构设计

> 目标：**MATLAB 成为唯一算法引擎**。Python 仅负责 GUI、通信、可视化、导出、日志、Bridge。
> 硬约束：**不修改 GUI / 不修改通信协议 / 不修改 protobuf**。
> 配套文档：[MATLAB_CALL_GRAPH.md](MATLAB_CALL_GRAPH.md)、[BRIDGE_ARCHITECTURE.md](BRIDGE_ARCHITECTURE.md)、[COMMUNICATION.md](COMMUNICATION.md)
> 生成时间：2026-07-14

---

## 1. 设计原则

| 原则 | 说明 |
|------|------|
| **算法唯一性** | 所有数值计算（路径规划、形貌预测、切片、A*、射线追踪、网格重建）必须由 MATLAB `.m` 文件执行。Python 不再做任何算法计算。 |
| **职责隔离** | Python 负责：协议解析、数据搬运、可视化派生、日志、Bridge 容错。MATLAB 负责：算法本体。 |
| **零侵入协议** | RepairRequest / RepairResult / Waypoint / ParticleDistribution / LayerProfile 等 protobuf 消息结构不变。 |
| **零侵入 GUI** | GUI 看到的仍是 `RepairResult`，字段、类型、回调路径完全一致。 |
| **可替换接缝** | 通过 `MatlabAdapter._algorithm_fn` 注入 MATLAB 调用实现，业务层无感知。 |
| **工程可降级** | 若 MATLAB 引擎不可用（ licence / 工具箱缺失 / 启动失败），按配置回退到 Python 原型并打 WARNING，不阻断生产。 |

---

## 2. 现状基线（为什么 MATLAB 没在做计算）

### 2.1 当前生产路径

```
GUI ─► CoordinationService ─► LegacyZmqClient ─► BridgeClient
     ─► ZeroMQ(5555) ─► matlab_bridge_server.m
     ─► pyenv → Python MatlabAdapter.serve()
     ─► _default_algorithm()
     ─► repair_app.core.path_planner.plan_path_from_cloud()   ← 纯 Python
```

### 2.2 根因

| 现象 | 根因 |
|------|------|
| 22 个 `.m` 算法文件全部未执行 | `matlab_bridge_server.m` 仅用 `pyenv` 调用 Python，`py.` 命名空间方向是 MATLAB→Python，**无法反向从 Python 调 MATLAB**。 |
| Python 算法覆盖率仅 25% / 10% | `path_planner.py` / `morphology_predictor.py` 是简化原型，缺失 A*、射线追踪、八叉树、Delaunay 重建等关键能力。 |
| MATLAB 是进程宿主而非计算引擎 | 进程由 MATLAB 启动，但计算委托回 Python。 |

### 2.3 关键技术约束：`pyenv` 的方向性

```
pyenv 方向：  MATLAB ──py.xxx()──► Python 函数     （当前已用）
反向调用：    Python ──matlab.engine──► MATLAB 函数  （本方案采用）
```

`matlab.engine` 是 MathWorks 官方提供的 Python→MATLAB 调用库，支持：
- 启动共享 MATLAB 会话（`matlab.engine.start_matlab()`）
- 调用任意 `.m` 函数（`eng.func_name(arg1, arg2, ...)`）
- NumPy ↔ MATLAB 数组自动转换
- 后台异步执行（`background=True` + `Future.result()`）

**本方案核心：用 `matlab.engine` 在 Python 侧反向调用 MATLAB 算法。**

---

## 3. 目标架构

### 3.1 整体数据流

```
┌──────────────────────────────────────────────────────────────────────────┐
│                              Python 侧（不变）                            │
│                                                                          │
│  GUI ─► CoordinationService ─► BridgeClient ─► ZeroMQ(5555)             │
│                                                                          │
│       ┌──────────────────────────────────────────────────────────┐       │
│       │ MatlabAdapter.handle_repair(request)                     │       │
│       │   1. Serializer.parse_point_cloud → (xyz, normals, meta) │       │
│       │   2. self._invoke_algorithm(xyz, meta)                   │       │
│       │      └─► _algorithm_fn(xyz, meta)   ← ★ 注入点           │       │
│       │   3. 派生可视化字段（layer_profiles / particle_dist）    │       │
│       │   4. Serializer.build_repair_result(waypoints)           │       │
│       └──────────────────────────────────────────────────────────┘       │
└──────────────────────────────────────────────────────────────────────────┘
                                   │
                                   │  _algorithm_fn 注入 MATLAB 实现
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        MATLAB 算法引擎（新增）                            │
│                                                                          │
│  MatlabEngineProxy（Python 单例）                                        │
│   ├─ matlab.engine.start_matlab() → eng                                 │
│   ├─ addpath('形貌预测', '路径规划')                                     │
│   ├─ toolbox_check()                                                    │
│   └─ run_repair_pipeline(xyz, meta) → waypoints(M,8)                    │
│                                                                          │
│  MATLAB 内部管线（eng 调用 .m 函数）：                                   │
│   ┌────────────────────────────────────────────────────────────┐         │
│   │ A. 点云 → STL → triangles（数据适配层）                    │         │
│   │ B. 路径规划管线（read_stl_file → model_process →          │         │
│   │    layer_slice → generate_path → point_interpretaion）     │         │
│   │ C. 形貌预测管线（可选，递归细分 → 粒子拟合 → 射线追踪 →    │         │
│   │    classifyRemovedTriangles → profilePredict）            │         │
│   │ D. 输出适配层（pointlist → (M,8) waypoints ndarray）       │         │
│   └────────────────────────────────────────────────────────────┘         │
└──────────────────────────────────────────────────────────────────────────┘
```

### 3.2 组件清单

| 组件 | 位置 | 职责 | 是否新建 |
|------|------|------|---------|
| `MatlabAdapter` | `repair_app/bridge/adapters/matlab_adapter.py` | 接收 RepairRequest，调用 `_algorithm_fn`，构建 RepairResult | 已有，仅修改 `_algorithm_fn` 注入 |
| `MatlabEngineProxy` | `repair_app/bridge/adapters/matlab_engine_proxy.py` | `matlab.engine` 单例封装：启动、addpath、健康检查、调用转发 | **新建** |
| `matlab_repair_pipeline.m` | 项目根 `matlab_algos/` | MATLAB 侧入口函数：接收点云/参数，串接全部算法，返回 pointlist | **新建** |
| `pointcloud_to_stl.m` | `matlab_algos/` | 点云 → STL 文件（scatteredInterpolant + 三角化） | **新建** |
| `waypoints_to_ndarray.m` | `matlab_algos/` | MATLAB pointlist → Python 可读的数值数组 | **新建** |
| `check_toolboxes.m` | `matlab_algos/` | 启动时检查 Mapping/Curve Fitting/Statistics 工具箱 | **新建** |
| `matlab_bridge_server.m` | 项目根 | 仍为进程宿主，但改为先 `start_matlab` 共享会话再启动 Python Bridge | 修改 |
| Protobuf / Serializer / GUI | — | 完全不动 | 不动 |

---

## 4. 数据交换接口设计（MATLAB ↔ Python）

### 4.1 接缝契约（不变）

`MatlabAdapter._algorithm_fn` 是唯一接缝，签名固定为：

```python
def algorithm_fn(xyz: np.ndarray, meta: dict) -> np.ndarray:
    """
    输入：
        xyz : (N, 3) float32 — 基体点云坐标
        meta: dict — 全部 v2.1 工艺参数（见下表）
    输出：
        waypoints : (M, 8) float32 — 列定义见下表
    """
```

**输入 `meta` 字段（来自 `parse_point_cloud`，已存在，不可变）：**

| 键 | 类型 | 含义 | MATLAB 对应参数 |
|----|------|------|----------------|
| `scan_id` | str | 扫描 ID | — |
| `point_count` | int | 点数 | — |
| `material` | str | 材料枚举名 | 影响密度查询 |
| `num_layers` | int | 层数 | `layer_slice` 循环次数 |
| `layer_height_mm` | float | 层厚 | `layer_height` |
| `scanning_angle_deg` | float | 扫描角 | `scanning_angle` |
| `scanning_step_mm` | float | 扫描步距 | `scanning_step` |
| `edge_step_size_mm` | float | 边缘步距 | `edge_step_size` |
| `tilt_angle_deg` | float | 倾角 | `tilt_angle` |
| `buffer_additive_mm` | float | 增材内缩 | `buffer_additive` |
| `buffer_repairing_mm` | float | 修复内缩 | `buffer_repairing` |
| `particle_velocity_ms` | float | 粒子速度 | `particleFitting` 输入 |
| `critical_velocity_ms` | float | 临界速度 | `particleFitting` 输入 |
| `nozzle_diameter_mm` | float | 喷嘴直径 | `particleFitting` 输入 |
| `standoff_distance_mm` | float | 靶距 | `particleFitting` SoD |
| `particle_size_um` | float | 粒径 | `particleFitting` 输入 |
| `track_overlap_ratio` | float | 搭接率 | 影响道宽 |
| `traversing_speed_mms` | float | 扫掠速度 | `velocitylist` |
| `link_path_free_dist_mm` | float | 自由连接距离 | `linkPath_freeDistance` |
| `obstacle_resolution_mm` | float | 占据图分辨率 | `resolution` |

**输出 `waypoints` 列定义（来自 `build_repair_result`，已存在，不可变）：**

| 列 | 字段 | 类型 | 含义 |
|----|------|------|------|
| 0 | x | float32 | 航点 X 坐标 (mm) |
| 1 | y | float32 | 航点 Y 坐标 (mm) |
| 2 | z | float32 | 航点 Z 坐标 (mm) |
| 3 | nx | float32 | 喷嘴法向 X |
| 4 | ny | float32 | 喷嘴法向 Y |
| 5 | nz | float32 | 喷嘴法向 Z |
| 6 | feed_rate | float32 | 进给速度 (mm/s) |
| 7 | layer_index | int32 | 层号（从 0 起） |

### 4.2 数据格式转换

MATLAB 算法管线的原生输入是 **STL 文件**（`read_stl_file` / `read_STLfile`），不是点云。需要新增"点云→STL"适配层。

#### 4.2.1 Python 侧预处理（轻量，非算法）

```python
# 在 MatlabEngineProxy 内部，调用 MATLAB 前
def _prepare_matlab_input(self, xyz: np.ndarray, meta: dict) -> dict:
    """将点云+meta 转换为 MATLAB 管线所需输入。"""
    work_dir = tempfile.mkdtemp(prefix="csam_matlab_")
    stl_path = os.path.join(work_dir, "substrate.stl")
    # 写 ASCII STL（轻量 I/O，不算算法）
    _write_xyz_as_stl(xyz, stl_path)
    return {
        "stl_path": stl_path,
        "work_dir": work_dir,
        "params": _meta_to_matlab_params(meta),
    }
```

#### 4.2.2 MATLAB 侧入口函数

**`matlab_algos/matlab_repair_pipeline.m`**：

```matlab
function [pointlist_ndarray, layer_indices, meta_out] = matlab_repair_pipeline(stl_path, params)
% MATLAB_REPAIR_PIPELINE  CSAM 修复算法统一入口（供 matlab.engine 调用）
%
% 输入：
%   stl_path : char，STL 文件绝对路径
%   params   : struct，包含全部工艺参数（由 Python 侧构造）
%
% 输出：
%   pointlist_ndarray : M×6 double，[x, y, z, nx, ny, nz]
%   layer_indices     : M×1 double，层号
%   meta_out          : struct，附加信息（耗时、警告、工具箱状态）

    t0 = tic;
    meta_out = struct();

    % ---- 工具箱检查 ----
    [tb_ok, tb_missing] = check_toolboxes();
    meta_out.toolbox_ok = tb_ok;
    meta_out.toolbox_missing = tb_missing;
    if ~tb_ok
        warning('MATLAB:ToolboxMissing', '缺失工具箱: %s', strjoin(tb_missing, ', '));
    end

    % ---- 1. 路径规划管线（形貌预测/ 目录） ----
    triangles = read_stl_file(stl_path);   % N×12
    [all_tris, add_cluster, rep_clusters, x_min, x_max, y_min, y_max] = ...
        model_process(triangles, 1.0, 1e-8, params.base_plane);

    [add_layerlist, rep_layerlist] = ...
        layer_slice(add_cluster, rep_clusters, params.layer_height, params.base_plane);

    [pointlist, velocitylist, zonelist] = ...
        generate_path(add_layerlist, rep_layerlist, ...
            params.buffer_additive, params.buffer_repairing, ...
            params.scanning_angle, params.scanning_step, ...
            params.edge_step_size, params.tilt_angle, ...
            x_min, x_max, y_min, y_max, ...
            params.link_path_free_dist, params.resolution);

    % ---- 2. 法向计算（pointlist 第 4-6 列已含 nx,ny,nz） ----
    % generate_path 的输出 pointlist 已经是 N×6: [x,y,z,nx,ny,nz]
    % 若需 ABB 姿态转换，可在此调用 point_interpretaion（可选）

    % ---- 3. 层号推导 ----
    % pointlist 的 Z 值与 layerlist 的 z_slices 对应
    layer_indices = derive_layer_indices(pointlist, rep_layerlist, add_layerlist, params.base_plane);

    % ---- 4. 速度数值化 ----
    % velocitylist 是 cell 数组（{'v500','v300',...}），转数值
    feed_rates = velocity_to_numeric(velocitylist, params.traversing_speed);

    % ---- 5. 形貌预测（可选，由 params.enable_morphology 控制） ----
    if params.enable_morphology
        try
            [oldTri, newTri] = run_morphology_pipeline(triangles, pointlist, params);
            meta_out.morphology_updated = true;
            meta_out.new_triangle_count = size(newTri, 1);
        catch me
            meta_out.morphology_updated = false;
            meta_out.morphology_error = me.message;
        end
    end

    pointlist_ndarray = [pointlist, feed_rates];
    meta_out.compute_time_s = toc(t0);
    meta_out.waypoint_count = size(pointlist_ndarray, 1);
end
```

#### 4.2.3 输出回传与 ndarray 装配

`matlab.engine` 调用返回的 `pointlist_ndarray` 是 `matlab.double`（M×7 矩阵）。Python 侧转换：

```python
def _postprocess_matlab_output(self, ml_result) -> np.ndarray:
    """MATLAB 输出 → (M, 8) waypoints ndarray。"""
    pointlist = np.array(ml_result['pointlist_ndarray'], dtype=np.float32)  # (M, 7)
    layer_indices = np.array(ml_result['layer_indices'], dtype=np.int32).reshape(-1, 1)
    # 拼成 (M, 8): x,y,z,nx,ny,nz,feed_rate,layer_index
    waypoints = np.hstack([pointlist, layer_indices.astype(np.float32)])
    return waypoints
```

### 4.3 类型映射表

| Python 类型 | MATLAB 类型 | 转换方向 | 备注 |
|------------|------------|---------|------|
| `np.ndarray (N,3) float32` | `matlab.double (N,3)` | Py→ML | `matlab.engine` 自动转 |
| `str` | `char` | Py→ML | 自动转 |
| `dict` | `struct` | Py→ML | 需在 Python 侧用 `mlpkg` 或手动构造 |
| `matlab.double (M,7)` | `np.ndarray (M,7) float64` | ML→Py | `np.array(ml_obj)` |
| `matlab.logical` | `np.bool_` | ML→Py | — |
| `struct` | `dict` | ML→Py | 字段名映射 |

---

## 5. 核心组件设计

### 5.1 `MatlabEngineProxy`（Python 侧单例）

**文件**：`repair_app/bridge/adapters/matlab_engine_proxy.py`

**职责**：
1. 启动并持有 `matlab.engine` 共享会话（懒加载，首次调用时启动）
2. 配置 MATLAB 路径（`addpath` 形貌预测/路径规划/matlab_algos）
3. 工具箱健康检查
4. 转发算法调用，处理超时/异常
5. 提供 `__call__` 接口，符合 `_algorithm_fn` 签名

**接口草案**：

```python
class MatlabEngineProxy:
    """matlab.engine 单例封装，符合 _algorithm_fn 签名。"""

    _instance: Optional["MatlabEngineProxy"] = None
    _eng = None  # matlab.engine.MatlabEngine

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, matlab_root: str, algo_dirs: list[str],
                 startup_timeout_s: int = 60, call_timeout_s: int = 30):
        self._matlab_root = matlab_root
        self._algo_dirs = algo_dirs
        self._startup_timeout = startup_timeout_s
        self._call_timeout = call_timeout_s
        self._started = False
        self._lock = threading.Lock()

    def _ensure_started(self) -> None:
        """懒启动 MATLAB 引擎并配置路径。"""
        if self._started:
            return
        with self._lock:
            if self._started:
                return
            import matlab.engine
            self._eng = matlab.engine.start_matlab(background=False)
            for d in self._algo_dirs:
                self._eng.addpath(d, nargout=0)
            # 工具箱检查
            tb_ok = self._eng.check_toolboxes(nargout=1)
            if not tb_ok:
                logger.warning("MATLAB 工具箱不全，部分算法可能降级")
            self._started = True
            logger.info("MATLAB 引擎就绪")

    def __call__(self, xyz: np.ndarray, meta: dict) -> np.ndarray:
        """符合 _algorithm_fn 签名：xyz + meta → waypoints(M,8)。"""
        self._ensure_started()
        params = _meta_to_matlab_struct(meta)
        stl_path = _write_xyz_as_stl(xyz)
        try:
            future = self._eng.matlab_repair_pipeline(
                stl_path, params, background=True, nargout=3
            )
            result = future.result(timeout=self._call_timeout)
            return self._assemble_waypoints(result)
        except matlab.engine.TimeoutError:
            raise MatlabAlgorithmError(f"MATLAB 调用超时 ({self._call_timeout}s)")
        except Exception as exc:
            raise MatlabAlgorithmError(f"MATLAB 执行失败: {exc}") from exc

    def shutdown(self) -> None:
        if self._eng is not None:
            self._eng.quit()
            self._eng = None
            self._started = False
```

### 5.2 `matlab_bridge_server.m` 改造

**当前**：仅 `pyenv` → `py.importlib.import_module` → `adapter.serve()`。

**改造后**：在启动 Python 适配器前，**预启动一个共享 MATLAB 会话**，供 Python 侧 `matlab.engine.connect_matlab()` 复用，避免重复启动。

```matlab
%% matlab_bridge_server.m（改造后）
function matlab_bridge_server()
    % 1. 配置 Python 环境（不变）
    venvPython = fullfile(pwd, 'venv', 'Scripts', 'python.exe');
    pyenv('Version', venvPython);

    % 2. ★ 新增：启动共享 MATLAB 会话
    %    使 Python 侧可通过 matlab.engine.connect_matlab('matlab_bridge') 复用
    matlab.engine.shareEngine('matlab_bridge');
    fprintf('[bridge] MATLAB 共享会话 "matlab_bridge" 已就绪\n');

    % 3. addpath 算法目录（不变）
    addpath(fullfile(pwd, '形貌预测'));
    addpath(fullfile(pwd, '路径规划'));
    addpath(fullfile(pwd, 'matlab_algos'));

    % 4. 工具箱预检
    check_toolboxes();

    % 5. 启动 Python Bridge（不变）
    py.importlib.import_module('repair_app.bridge.adapters.matlab_adapter');
    adapter = py.repair_app.bridge.adapters.matlab_adapter.create_matlab_adapter();
    adapter.serve();
end
```

### 5.3 `MatlabAdapter` 注入改造

**当前**（`matlab_adapter.py` L57）：

```python
self._algorithm_fn = algorithm_fn or self._default_algorithm
```

**改造后**：根据配置选择算法实现，**不动 `handle_repair` 任何逻辑**。

```python
def __init__(self, address=None, config=None, algorithm_fn=None):
    super().__init__(address, config)
    if algorithm_fn is not None:
        self._algorithm_fn = algorithm_fn
    else:
        self._algorithm_fn = self._select_algorithm_by_config()

def _select_algorithm_by_config(self):
    """根据配置选择算法实现：MATLAB 优先，降级 Python。"""
    cfg = self._config
    engine_mode = getattr(cfg, 'matlab_engine_mode', 'auto')  # auto|matlab|python

    if engine_mode == 'python':
        return self._default_algorithm

    if engine_mode in ('matlab', 'auto'):
        try:
            from .matlab_engine_proxy import MatlabEngineProxy
            proxy = MatlabEngineProxy(
                matlab_root=cfg.matlab_root,
                algo_dirs=cfg.matlab_algo_dirs,
                call_timeout_s=getattr(cfg, 'matlab_call_timeout_s', 30),
            )
            # auto 模式：尝试连接，失败则降级
            proxy._ensure_started()
            logger.info("算法引擎：MATLAB（matlab.engine）")
            return proxy
        except Exception as exc:
            if engine_mode == 'matlab':
                raise MatlabAlgorithmError(f"MATLAB 引擎不可用: {exc}") from exc
            logger.warning("MATLAB 引擎不可用，降级到 Python 原型: %s", exc)
            return self._default_algorithm

    return self._default_algorithm
```

### 5.4 配置扩展（`BridgeConfig`）

新增字段（**不破坏现有配置**，全部带默认值）：

```python
@dataclass
class BridgeConfig:
    # ... 现有字段不变 ...

    # ★ 新增：MATLAB 引擎配置
    matlab_engine_mode: str = "auto"          # auto | matlab | python
    matlab_root: str = ""                      # MATLAB 安装根目录（留空则自动探测）
    matlab_algo_dirs: list[str] = field(default_factory=list)  # 算法 .m 所在目录
    matlab_call_timeout_s: int = 30            # 单次算法调用超时
    matlab_startup_timeout_s: int = 60         # 引擎启动超时
    matlab_shared_session_name: str = "matlab_bridge"  # 共享会话名
    matlab_enable_morphology: bool = False     # 是否启用形貌预测管线
```

---

## 6. MATLAB 管线映射（Python meta → MATLAB 调用）

### 6.1 路径规划管线（必选）

| 步骤 | MATLAB 函数 | 输入 | 输出 | Python meta 映射 |
|------|------------|------|------|-----------------|
| 1 | `read_stl_file(stl_path)` | STL 路径 | triangles (N×12) | stl_path 由适配层生成 |
| 2 | `model_process(triangles, 1.0, 1e-8, base_plane)` | triangles + 4 参数 | all_tris, add_cluster, rep_clusters, xmin,xmax,ymin,ymax | `base_plane` ← 固定 5.0 或 `meta['base_plane_mm']` |
| 3 | `layer_slice(add_cluster, rep_clusters, layer_height, base_plane)` | 上一步输出 + 2 参数 | add_layerlist, rep_layerlist | `layer_height` ← `meta['layer_height_mm']` |
| 4 | `generate_path(...)` | 14 参数 | pointlist (M×6), velocitylist, zonelist | 见下表 |
| 5 | `derive_layer_indices(pointlist, rep_layerlist, add_layerlist)` | pointlist + layerlist | layer_indices (M×1) | 新增工具函数 |
| 6 | `velocity_to_numeric(velocitylist, traversing_speed)` | cell 数组 | feed_rates (M×1) | `traversing_speed` ← `meta['traversing_speed_mms']` |

**`generate_path` 14 参数映射**：

| MATLAB 参数 | Python meta 键 | 默认值 |
|------------|----------------|-------|
| `additive_layerlist` | 步骤 3 输出 | — |
| `repairing_layerlist` | 步骤 3 输出 | — |
| `buffer_additive` | `meta['buffer_additive_mm']` | 2.0 |
| `buffer_repairing` | `meta['buffer_repairing_mm']` | 0.0 |
| `scanning_angle` | `meta['scanning_angle_deg']` | -45.0 |
| `scanning_step` | `meta['scanning_step_mm']` | 2.0 |
| `edge_step_size` | `meta['edge_step_size_mm']` | 2.0 |
| `tilt_angle` | `meta['tilt_angle_deg']` | 60.0 |
| `x_min, x_max, y_min, y_max` | 步骤 2 输出 | — |
| `linkPath_freeDistance` | `meta['link_path_free_dist_mm']` | 20.0 |
| `resolution` | `meta['obstacle_resolution_mm']` | 2.0 |

### 6.2 形貌预测管线（可选，默认关闭）

仅当 `matlab_enable_morphology=True` 时执行。输入依赖路径规划输出的 `pointlist`，输出更新后的三角网格（供 GUI 可选可视化）。

```
read_STLfile(stl_path)
  → recursiveSubdivide(triangles, maxEdgeLength)
  → improveShortEdges(triangles, boundary_vertices, length_threshold)
  → particleFitting(excelFile, SoD)        ← 需 CFD 数据文件
  → spotInterp(ReferencePoint, pointlist, velocitylist, spot_step_size)
  → 循环（逐喷斑）:
      rayMove → buildOctree → batchOctreeFilter
      → ray_triangle_intersection
      → classifyRemovedTriangles
      → profilePredict
      → createfigures（可选）
  → createvideo（可选）
```

**依赖额外数据**：`particleFitting` 需要 CFD Excel 文件（`excelFile`）。集成时需在 `meta` 中增加 `cfd_data_path` 字段，或从配置文件读取。

### 6.3 完整调用图（集成后）

```
Python MatlabAdapter.handle_repair(RepairRequest)
  │
  ├─ Serializer.parse_point_cloud → (xyz, normals, meta)
  │
  ├─ MatlabEngineProxy.__call__(xyz, meta)
  │    │
  │    ├─ _write_xyz_as_stl(xyz) → stl_path      [Python 轻量 I/O]
  │    │
  │    └─ eng.matlab_repair_pipeline(stl_path, params)
  │         │
  │         ├─ check_toolboxes()
  │         │
  │         ├─ read_stl_file(stl_path)                    ★ 路径规划起点
  │         │     ↓
  │         ├─ model_process(triangles, ...)
  │         │     ↓
  │         ├─ layer_slice(add_cluster, rep_clusters, ...)
  │         │     ↓
  │         ├─ generate_path(...)  ──► aStarSearch (子调用)
  │         │     ↓ pointlist (M×6), velocitylist, zonelist
  │         │
  │         ├─ [可选] 形貌预测管线
  │         │     ├─ recursiveSubdivide
  │         │     ├─ improveShortEdges
  │         │     ├─ particleFitting
  │         │     ├─ spotInterp
  │         │     └─ 循环: rayMove → buildOctree → batchOctreeFilter
  │         │              → ray_triangle_intersection
  │         │              → classifyRemovedTriangles
  │         │              → profilePredict
  │         │
  │         ├─ derive_layer_indices(pointlist, layerlist)
  │         ├─ velocity_to_numeric(velocitylist, traversing_speed)
  │         │
  │         └─ return (pointlist(M×7), layer_indices(M×1), meta_out)
  │
  ├─ _assemble_waypoints → (M, 8) ndarray
  │
  ├─ 派生可视化字段（layer_profiles / particle_dist / uniformity）
  │
  └─ Serializer.build_repair_result(waypoints, ...) → RepairResult
```

---

## 7. 工具箱依赖处理

### 7.1 依赖清单

| 工具箱 | 使用函数 | 使用文件 | 必需性 |
|-------|---------|---------|-------|
| Mapping Toolbox | `polyshape`, `polyxpoly`, `polybuffer`, `regions`, `sortregions`, `ishole`, `isinterior` | `generate_path.m`, `profilePredict.m` | **必需** |
| Curve Fitting Toolbox | `fittype`, `fit` | `particleFitting.m` | 形貌预测必需，路径规划不需要 |
| Statistics & ML Toolbox | `histcounts2` | `particleFitting.m` | 形貌预测必需，路径规划不需要 |

### 7.2 `check_toolboxes.m`

```matlab
function [ok, missing] = check_toolboxes()
% CHECK_TOOLBOXES  检查 CSAM 算法所需工具箱
    required = {'map_toolbox', 'curve_fitting_toolbox', 'statistics_toolbox'};
    names = {'Mapping Toolbox', 'Curve Fitting Toolbox', 'Statistics & ML Toolbox'};
    installed = matlab.addons.installedAddons();
    ok = true;
    missing = {};
    for i = 1:length(required)
        if ~any(strcmp(installed.Identifier, required{i}))
            ok = false;
            missing{end+1} = names{i};
        end
    end
    if ok
        fprintf('[toolboxes] 全部就绪: %s\n', strjoin(names, ', '));
    else
        fprintf('[toolboxes] 缺失: %s\n', strjoin(missing, ', '));
    end
end
```

### 7.3 降级策略

| 缺失工具箱 | 影响 | 降级行为 |
|-----------|------|---------|
| Mapping Toolbox | 路径规划无法运行 | `matlab_engine_mode=auto` 时整体降级到 Python 原型 |
| Curve Fitting / Statistics | 形貌预测无法运行 | 路径规划仍可用，`matlab_enable_morphology` 自动置 false |

---

## 8. 错误处理与容错

### 8.1 异常分类

| 异常类型 | 触发场景 | Python 侧翻译 | GUI 感知 |
|---------|---------|--------------|---------|
| `matlab.engine.TimeoutError` | 算法调用超时 | `MatlabAlgorithmError("MATLAB 调用超时")` → `ERR_ALGORITHM_FAIL` | 错误弹窗 |
| `MatlabExecutionError` | MATLAB 内部异常（工具箱缺失、数值错误） | 同上 | 错误弹窗 |
| `EngineError`（启动失败） | licence/版本不兼容 | 启动阶段捕获，降级到 Python | WARNING 日志，GUI 无感 |
| `FileNotFoundError` | STL 临时文件写失败 | `ERR_INVALID_INPUT` | 错误弹窗 |

### 8.2 重试与降级链

```
MATLAB 引擎调用
  ├─ 成功 → 返回 waypoints
  ├─ 超时 → 重试 1 次（指数退避 2s）
  │         ├─ 成功 → 返回
  │         └─ 失败 → 降级 Python 原型 + WARNING 日志
  └─ 异常 → 降级 Python 原型 + WARNING 日志（仅 auto 模式）
            或 抛错（matlab 强制模式）
```

### 8.3 资源清理

- `MatlabEngineProxy` 注册 `atexit` 钩子，进程退出时调用 `eng.quit()`
- 临时 STL 文件在 `_postprocess_matlab_output` 后立即 `os.remove`
- 长时间未调用（>10min）时引擎保持，不主动关闭（避免重启开销）

---

## 9. 性能考量

### 9.1 调用开销

| 环节 | 预估耗时 | 备注 |
|------|---------|------|
| Python→MATLAB 参数转换 | <5ms | NumPy 自动转换 |
| STL 临时文件写入 | 10-50ms | 取决于点云规模 |
| MATLAB 引擎首次启动 | 15-30s | 仅一次，后续复用 |
| `read_stl_file` | 50-200ms | 取决于 STL 复杂度 |
| `model_process` + `layer_slice` | 100-500ms | — |
| `generate_path`（含 A*） | 500-3000ms | 取决于切片层数与 A* 网格 |
| 形貌预测单次循环 | 200-800ms | 每喷斑一次 |
| 输出回传 | <10ms | — |

### 9.2 优化建议

1. **共享会话复用**：`matlab.engine.connect_matlab('matlab_bridge')` 避免每次重启
2. **STL 缓存**：相同 `scan_id` 的点云缓存 STL 文件，避免重复生成
3. **进度回调**：长任务通过 `eng.evalin` 写共享变量，Python 轮询上报 `ProgressUpdate`
4. **批量调用**：连续多个 RepairRequest 复用同一引擎实例（`MatlabEngineProxy` 单例保证）

---

## 10. 集成实施清单

### 10.1 新建文件清单

| 文件 | 路径 | 行数预估 | 说明 |
|------|------|---------|------|
| `matlab_engine_proxy.py` | `repair_app/bridge/adapters/` | ~150 | matlab.engine 单例封装 |
| `matlab_repair_pipeline.m` | `matlab_algos/` | ~120 | MATLAB 侧统一入口 |
| `check_toolboxes.m` | `matlab_algos/` | ~30 | 工具箱检查 |
| `derive_layer_indices.m` | `matlab_algos/` | ~40 | 由 pointlist Z 推导层号 |
| `velocity_to_numeric.m` | `matlab_algos/` | ~25 | cell 速度数组转数值 |
| `pointcloud_to_stl.m`（可选） | `matlab_algos/` | ~50 | 点云→STL（也可纯 Python 实现） |

### 10.2 修改文件清单

| 文件 | 修改范围 | 风险 |
|------|---------|------|
| `matlab_adapter.py` | `__init__` 注入逻辑（~20 行） | 低，`handle_repair` 不动 |
| `matlab_bridge_server.m` | 增加 `shareEngine` + `addpath`（~10 行） | 低 |
| `config.py`（BridgeConfig） | 新增 6 个字段（带默认值） | 低，向后兼容 |

### 10.3 不修改文件清单（硬约束）

| 文件 | 原因 |
|------|------|
| 所有 GUI 文件（`repair_app/gui/`） | 硬约束 |
| `repair_protocol.proto` | 硬约束 |
| `repair_serialization.py` | 协议层不变 |
| `serializer.py` | 协议层不变 |
| `zmq_server.py` | 通信层不变 |
| `path_planner.py` / `morphology_predictor.py` | 保留作为降级回退，不删除 |

### 10.4 验收标准

| 验收项 | 方法 |
|-------|------|
| MATLAB 引擎成功启动 | `MatlabEngineProxy._ensure_started()` 无异常 |
| 路径规划由 MATLAB 执行 | 日志出现"算法引擎：MATLAB"，`meta_out.compute_time_s > 0` |
| A* 连接路径生效 | `pointlist` 中存在非扫描线方向的连接段 |
| 倾角法向生效 | `pointlist[:, 3:6]` 不再全是 `[0,0,1]` |
| GUI 无感知切换 | GUI 端到端测试通过，无代码改动 |
| 降级机制有效 | 断开 MATLAB licence 后，auto 模式自动回退 Python |
| 超时处理有效 | 模拟 MATLAB 卡死，30s 后超时返回错误 |
| 311 项测试全通过 | `pytest repair_app/tests/ bridge/tests/` |

---

## 11. 风险与对策

| 风险 | 等级 | 对策 |
|------|-----|------|
| `matlab.engine` Python 包未安装 | 中 | 在 `requirements.txt` 增加 `matlabengine`（仅 Windows） |
| MATLAB R2025b licence 不可用 | 高 | auto 模式降级；生产环境建议浮动 licence |
| 工具箱缺失导致算法失败 | 中 | `check_toolboxes.m` 预检 + 降级 |
| 点云→STL 转换精度损失 | 中 | 使用 `scatteredInterpolant` + `delaunay` 三角化，验证误差 <0.01mm |
| MATLAB 单线程瓶颈 | 低 | 当前单 RepairRequest 串行；未来可多引擎实例并行 |
| 引擎启动慢（15-30s） | 中 | `matlab_bridge_server.m` 预启动共享会话 |
| 临时文件残留 | 低 | `atexit` + `try/finally` 清理 |

---

## 12. 与现有文档的关系

| 文档 | 关系 |
|------|------|
| [MATLAB_CALL_GRAPH.md](MATLAB_CALL_GRAPH.md) | 互补：本文档引用其调用图，本架构实现其调用链 |
| [MATLAB_INTEGRATION.md](MATLAB_INTEGRATION.md) | 该文档描述 v1.0 的 `pyenv` 单向集成；本文档为其升级方案（增加 `matlab.engine` 反向调用） |
| [BRIDGE_ARCHITECTURE.md](BRIDGE_ARCHITECTURE.md) | 不冲突：Bridge 通信架构不变，仅 `_algorithm_fn` 实现替换 |
| [COMMUNICATION.md](COMMUNICATION.md) | 不冲突：协议层完全不变 |
| [MATLAB_DEPLOYMENT_GUIDE.md](MATLAB_DEPLOYMENT_GUIDE.md) | 部署流程需更新：增加 `matlabengine` Python 包安装步骤 |

---

## 13. 总结

本架构的核心创新点：

1. **识别 `pyenv` 的方向性陷阱**：当前 `py.` 是 MATLAB→Python，无法反向调用。改用 `matlab.engine` 实现 Python→MATLAB。
2. **零侵入协议**：通过 `MatlabAdapter._algorithm_fn` 接缝注入，GUI/protobuf/serializer 全部不动。
3. **MATLAB 算法唯一性**：22 个 `.m` 算法文件全部被 `matlab_repair_pipeline.m` 串接执行，Python 不再做任何算法计算。
4. **工程可降级**：auto 模式在 MATLAB 不可用时自动回退 Python 原型，保证生产连续性。
5. **共享会话复用**：`matlab_bridge_server.m` 预启动共享 MATLAB 会话，Python 侧 `connect_matlab` 复用，避免重复启动开销。

**实施优先级**：
1. 先实现路径规划管线（`read_stl_file` → `generate_path`），覆盖核心功能
2. 验证 A* 连接路径与倾角法向正确性
3. 再启用形貌预测管线（需 CFD 数据）
4. 最后做性能优化与压力测试
