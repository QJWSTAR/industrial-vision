# 形貌预测 MATLAB 工业算法接入报告

## 1. 任务目标

将 MATLAB 形貌预测算法接入现有 CSAM 修复软件，使 MATLAB 成为形貌预测的唯一计算引擎，Python 负责通信、可视化与 GUI。

用户点击"生成修复路径"后，后台自动执行：

```
GUI → ZeroMQ → Bridge → MatlabAdapter
                              ↓
                    run_path_planning (航点)
                              ↓
                    run_profile_prediction (形貌预测)
                              ↓
                    返回 mesh / layer_profiles / particle_distribution
                    / uniformity / estimated_mass / estimated_time / warnings
                              ↓
                    RepairResult (Protobuf) → GUI 原生显示
```

约束：
- 不修改 GUI（`main_window.py`、`repair_visualizer.py`、`workers.py` 等均未改动）
- 不修改通信协议（`repair_protocol.proto` 未改动）
- 保持 Bridge / ZeroMQ / Protobuf 全部兼容
- 不导出 PNG、不导出视频
- 全部内存返回

## 2. 依赖分析

### 2.1 profilePredict 调用链

```
main.m
  ├── read_STLfile.m          → 读取 STL → N×9 三角形矩阵
  ├── recursiveSubdivide.m    → 递归细分长边三角形
  ├── improveShortEdges.m     → 短边合并优化
  ├── particleFitting.m       → CFD 数据拟合 → 粒子位置/速度/临界速度
  ├── spotInterp.m            → 喷斑路径插值
  └── [循环] 每个喷斑
        ├── rayMove.m                 → 射线平移旋转
        ├── buildOctree.m             → 八叉树空间加速
        ├── batchOctreeFilter.m       → 射线-AABB 粗筛
        ├── ray_triangle_intersection.m → Moller-Trumbore 精确求交
        ├── classifyRemovedTriangles.m  → 连通分量聚类 + 边界提取
        └── profilePredict.m           → 沉积高度预测 + Delaunay 重建
```

### 2.2 各文件职责

| 文件 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `read_STLfile.m` | STL 路径 | N×9 矩阵 | stlread 封装 |
| `recursiveSubdivide.m` | 三角形 + 最大边长 | 细分后三角形 | 递归对分最长边 |
| `improveShortEdges.m` | 三角形 + 阈值 | 优化后三角形 | 短边中点合并，去退化 |
| `particleFitting.m` | Excel + SoD | 射线参数 | CFD 数据 → 高斯拟合 → 射线簇 |
| `spotInterp.m` | 航点 + 速度 | 插值喷斑 | 等距采样 + 速度补偿映射 |
| `rayMove.m` | 喷斑 + 射线 | 移动后射线 | Rodrigues 旋转 |
| `buildOctree.m` | 三角形 + 深度 | 八叉树节点 | 递归 8 叉空间划分 |
| `batchOctreeFilter.m` | 八叉树 + 射线 | 候选三角形 | 射线-AABB slab 测试 |
| `ray_triangle_intersection.m` | 射线 + 候选 | 交点 | Moller-Trumbore 算法 |
| `classifyRemovedTriangles.m` | 交点 + 法向 | 簇 + 边界 | 图连通分量 + 边界边检测 |
| `profilePredict.m` | 全部上下文 | 新三角形 | 沉积高度 + 投影 + Delaunay |

## 3. 架构保持不变

以下组件未做任何修改：

| 组件 | 说明 |
|------|------|
| GUI | `main_window.py`、`repair_visualizer.py`、`workers.py`、`defect_selector.py` |
| 通信协议 | `repair_protocol.proto` |
| Bridge | `BridgeServer` ZeroMQ REP 端 |
| ZeroMQ | `tcp://127.0.0.1:5555` |
| Protobuf | `RepairRequest` / `RepairResult` 消息格式 |
| 通信配置 | `BridgeConfig` |

## 4. 新增 / 修改文件清单

### 4.1 新增文件

#### `路径规划/run_profile_prediction.m`（核心 MATLAB 入口）

**作用**：CSAM 形貌预测统一入口，串联完整管线，全部内存返回。

**函数签名**：

```matlab
function result = run_profile_prediction(stl_path, excel_path, params)
```

**管线**：

```
read_STLfile → 读取基体 STL
     ↓
recursiveSubdivide → 三角形细分
     ↓
improveShortEdges → 短边优化
     ↓
particleFitting → CFD 粒子拟合
     ↓
run_path_planning → 内部调用，获取喷涂航点
     ↓
spotInterp → 喷斑插值
     ↓
[rayMove → buildOctree → batchOctreeFilter
 → ray_triangle_intersection → classifyRemovedTriangles
 → profilePredict] 逐点循环
     ↓
compute_layer_profiles → 逐层轮廓
compute_uniformity → 均匀性评分
compute_deposition_volume → 填充体积
     ↓
返回结构体
```

**输入**：
- `stl_path`：STL 文件绝对路径（char）
- `excel_path`：CFD Excel 文件路径（char，可为空自动查找）
- `params`：工艺参数 struct，支持 24 个字段，缺失自动填充默认值

**输出**（struct，全部内存数组）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `mesh` | N×9 double | 最终沉积表面三角形 |
| `substrate_triangles` | N×9 double | 原始基体三角形 |
| `layer_profiles` | L×4 double | 逐层轮廓 [idx, max_h, avg_h, dep_eff] |
| `particle_distribution` | struct | 颗粒分布 (px/py/vx/vy/vz/vcr/diameter/temperature/dep_efficiency) |
| `uniformity` | 1×1 double | 均匀性评分 [0, 1] |
| `estimated_mass_g` | 1×1 double | 估算材料用量 |
| `estimated_time_s` | 1×1 double | 预估修复耗时 |
| `predicted_volume_mm3` | 1×1 double | 预测填充体积 |
| `warnings` | 1×N cell | 警告信息 |
| `compute_time_s` | 1×1 double | 计算耗时 |
| `waypoint_count` | 1×1 double | 航点数 |

**约束遵守**：
- 无 `clear` / `close all` / `figure` / `save` / `load`
- 无 `waitbar`（已移除）
- 无 `createfigures` / `createvideo` 调用（已移除）
- 全部内存返回
- 可执行行无 CJK 字符（CJK 仅在注释）

### 4.2 修改文件

#### `repair_app/bridge/adapters/matlab_engine_proxy.py`

新增内容：

1. **`call_profile_prediction(xyz, meta)` 方法**
   - 将点云写为临时 STL
   - 构造 MATLAB params struct（复用 `_meta_to_matlab_struct` + 形貌预测特有参数）
   - 调用 `eng.run_profile_prediction(stl_path, excel_path, params, nargout=1)`
   - 解析返回的 struct 为 Python dict

2. **`_meta_to_profile_params(meta)` 方法**
   - 将 Python meta dict 映射为 MATLAB params struct
   - 支持路径规划参数 + 形貌预测特有参数（SoD、八叉树深度等）

3. **`_parse_profile_result(raw)` 静态方法**
   - 处理 `matlab.double` → `numpy.ndarray` 转换
   - 处理嵌套 struct（`particle_distribution`）
   - 将 N×9 mesh 转为二进制 STL bytes

4. **`_triangles_to_binary_stl(triangles)` 模块函数**
   - N×9 三角形矩阵 → 二进制 STL bytes
   - 符合二进制 STL 规范（80 字节头 + 4 字节面数 + 每面 50 字节）

#### `repair_app/bridge/adapters/matlab_adapter.py`

新增内容：

1. **`handle_repair` 方法扩展**
   - 路径规划完成后，优先调用 `_try_profile_prediction`
   - 成功：使用 MATLAB 计算的 `mesh_data`、`layer_profiles`、`particle_dist`、`uniformity_score`、`estimated_mass_g`、`estimated_time_s`
   - 失败：降级到 Python 启发式（原有行为不变）

2. **`_try_profile_prediction(xyz, meta)` 方法**
   - 检查 `CSAM_ALGORITHM_ENGINE` 环境变量
   - `python` 模式跳过，返回 None
   - `auto` / `matlab` 模式尝试调用 MATLAB
   - 异常时 auto 降级，matlab 报警但仍降级

3. **`_build_viz_from_profile(raw, meta)` 静态方法**
   - 将 MATLAB 返回的 dict 转换为 RepairResult 可视化字段
   - `layer_profiles`: N×4 矩阵 → `List[LayerProfile]`
   - `particle_distribution`: dict → `ParticleDistribution`
   - `mesh_data`: 二进制 STL bytes

## 5. 数据流

### 5.1 完整链路

```
[GUI] 用户点击"生成修复路径"
  ↓ RepairRequest (Protobuf over ZMQ)
[Bridge] MatlabAdapter.handle_repair
  ↓ Serializer.parse_point_cloud → xyz + meta
  ↓ _invoke_algorithm → waypoints (路径规划)
  ↓ _try_profile_prediction → MATLAB 形貌预测
       ↓ _write_xyz_as_stl → 临时 STL
       ↓ eng.run_profile_prediction(stl_path, excel_path, params)
       ↓ MATLAB 内部:
       │   read_STLfile → recursiveSubdivide → improveShortEdges
       │   → particleFitting → run_path_planning → spotInterp
       │   → [rayMove → buildOctree → ... → profilePredict] 循环
       │   → 返回 struct
       ↓ _parse_profile_result → Python dict
       ↓ _build_viz_from_profile → 可视化字段
  ↓ Serializer.build_repair_result (含 mesh_data / layer_profiles / particle_dist)
[GUI] _on_zmq_path_result → 原生显示
  ↓ waypoints → 路径渲染
  ↓ layer_profiles → 逐层指标面板
  ↓ particle_dist → 颗粒分布面板
  ↓ uniformity_score → 均匀性指标
  ↓ estimated_mass_g / estimated_time_s → 用量/耗时面板
```

### 5.2 数据契约

#### MATLAB → Python（struct → dict）

```python
{
    "mesh": np.ndarray,              # (N, 9) float32
    "substrate_triangles": np.ndarray,  # (N, 9) float32
    "layer_profiles": np.ndarray,    # (L, 4) float32 [idx, max_h, avg_h, dep_eff]
    "particle_distribution": {
        "px": np.ndarray, "py": np.ndarray,
        "vx": np.ndarray, "vy": np.ndarray, "vz": np.ndarray,
        "vcr": np.ndarray,            # (M,) float32, 1=沉积 0=弹开
        "dep_efficiency": float,
        "diameter": np.ndarray,       # (M,) float32, um
        "temperature": np.ndarray,    # (M,) float32, K
    },
    "uniformity": float,              # [0, 1]
    "estimated_mass_g": float,
    "estimated_time_s": float,
    "predicted_volume_mm3": float,
    "compute_time_s": float,
    "waypoint_count": int,
    "warnings": list[str],
    "mesh_stl_bytes": bytes,          # 二进制 STL
}
```

#### Python → Protobuf（RepairResult 字段映射）

| MATLAB 字段 | RepairResult 字段 | 说明 |
|-------------|-------------------|------|
| `mesh_stl_bytes` | `mesh_data` + `mesh_format="stl_binary"` | 沉积表面网格 |
| `layer_profiles` | `layer_profiles` (repeated LayerProfile) | 逐层轮廓 |
| `particle_distribution` | `particle_dist` (ParticleDistribution) | 颗粒分布 |
| `uniformity` | `uniformity_score` | 均匀性评分 |
| `estimated_mass_g` | `estimated_mass_g` | 材料用量 |
| `estimated_time_s` | `estimated_time_s` | 修复耗时 |
| `predicted_volume_mm3` | `predicted_volume_mm3` | 填充体积 |

## 6. 降级策略

| `CSAM_ALGORITHM_ENGINE` | MATLAB 可用 | 路径规划 | 形貌预测 | 可视化字段来源 |
|--------------------------|-------------|---------|---------|---------------|
| `auto`（默认） | 是 | MATLAB | MATLAB | MATLAB 真实计算 |
| `auto` | 是 | MATLAB | 失败 | Python 启发式（降级） |
| `auto` | 否 | Python | 跳过 | Python 启发式 |
| `matlab` | 是 | MATLAB | MATLAB | MATLAB 真实计算 |
| `matlab` | 否 | 报错 | — | 不降级 |
| `python` | — | Python | 跳过 | Python 启发式 |

## 7. 测试验证

### 7.1 Python 代码导入验证（通过）

```python
>>> from repair_app.bridge.adapters.matlab_adapter import MatlabAdapter
>>> from repair_app.bridge.adapters.matlab_engine_proxy import (
...     MatlabEngineProxy, _triangles_to_binary_stl
... )
>>> import numpy as np
>>> tris = np.array([[0,0,0,1,0,0,0,1,0]], dtype=np.float32)
>>> stl = _triangles_to_binary_stl(tris)
>>> len(stl)  # 80(头) + 4(面数) + 50(单面) = 134
134
```

### 7.2 现有测试回归（通过）

```
repair_app/bridge/tests/test_bridge.py: 47 passed
repair_app/tests/: 264 passed, 47 warnings
```

所有现有测试通过，无回归。

### 7.3 MATLAB 算法管线（生产环境验证路径）

在 MATLAB R2025b 中验证：

```matlab
% 启动 matlab_bridge_server 后
params = struct('standoff_distance_mm', 30, 'num_layers', 3);
result = run_profile_prediction('substrate.stl', 'substrate-surface.xlsx', params);
disp(result.waypoint_count);    % 航点数
disp(size(result.mesh));        % 沉积表面三角形
disp(result.uniformity);        % 均匀性评分
disp(result.estimated_mass_g);  % 材料用量
```

### 7.4 端到端集成（生产环境）

1. 启动 `matlab_bridge_server.m`（共享引擎 + 加载算法路径）
2. 启动 GUI（`run_app.py`）
3. 用户加载点云 → 点击"生成修复路径"
4. `MatlabAdapter.handle_repair`：
   - 调用 `run_path_planning` → 航点
   - 调用 `run_profile_prediction` → 形貌预测结果
5. GUI 原生显示：路径、逐层轮廓、颗粒分布、均匀性、用量/耗时

## 8. 与路径规划接入的对比

| 维度 | 路径规划接入 | 形貌预测接入 |
|------|-------------|-------------|
| MATLAB 入口 | `run_path_planning.m` | `run_profile_prediction.m` |
| 输入 | STL + params | STL + Excel + params |
| 输出 | pointlist + feed_rates + layer_indices | struct（mesh + profiles + particles + metrics） |
| Python 代理方法 | `__call__(xyz, meta)` | `call_profile_prediction(xyz, meta)` |
| 适配器集成 | `_invoke_algorithm` | `_try_profile_prediction` |
| 填充的 Protobuf 字段 | waypoints | mesh_data + layer_profiles + particle_dist + uniformity + mass + time |
| 降级目标 | Python `path_planner` | Python 启发式派生 |
| GUI 修改 | 无 | 无 |
| 协议修改 | 无 | 无 |

## 9. 已知限制

### 9.1 TRAE Sandbox 限制

与路径规划接入相同，TRAE IDE 沙箱环境拦截 `mwEndpointRegistry` 文件访问，导致 `matlab.engine` 的 feval 调用失败。生产环境无此限制。

### 9.2 CFD Excel 文件依赖

`particleFitting` 依赖 `substrate-surface.xlsx`（CFD 仿真结果）。若文件不存在：
- `run_profile_prediction` 返回空颗粒分布 + 警告
- 沉积循环跳过（无射线数据）
- 仍返回基体网格 + 路径规划结果

### 9.3 性能

逐喷斑循环中的 `buildOctree` 在每个步进重建。对于大量喷斑（>500），总耗时可能较长。未来优化方向：
- 增量更新八叉树（仅重建受影响区域）
- 预计算射线-AABB 碰撞（GPU 加速）

## 10. 后续工作

1. **生产环境 e2e 验证**：在非 sandbox 环境运行完整链路
2. **mesh_data 渲染**：GUI 当前未消费 `mesh_data` 字段；未来可在 `repair_visualizer.py` 中添加二进制 STL 解析与渲染（需 GUI 修改，本阶段不做）
3. **参数标定**：根据实际工件验证 `subdivide_max_edge`、`octree_max_depth` 等参数的工业适用性
4. **增量形貌预测**：支持 ProgressUpdate 中间态推送，实现逐层实时显示
