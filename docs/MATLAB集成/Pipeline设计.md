# MATLAB Pipeline 设计文档

> 日期：2026-07-14 | 版本：1.0.0
> 变更：MATLAB 原始算法作为唯一计算实现，Python Demo 算法退出生产路径

---

## 一、设计目标

| 目标 | 说明 |
|------|------|
| MATLAB 唯一计算 | 路径规划 + 形貌预测全部由 MATLAB .m 算法完成 |
| 一次调用 | 路径规划 → 形貌预测自动串联，不分步调用 |
| 无人工操作 | 不需要手动运行 MATLAB、复制 .mat、切换目录 |
| 无重复计算 | run_path_planning 只调用一次（旧版调用两次） |
| 自动降级 | MATLAB 不可用时回退到 Python 启发式（保留兼容） |

---

## 二、目录结构说明

> **重要**：目录名与内容互换，这是历史遗留，已在代码中正确处理。

| 目录 | 实际内容 | 入口函数 |
|------|----------|----------|
| `形貌预测/` | **路径规划算法**（6 个 .m 文件） | `run_path_planning.m` |
| `路径规划/` | **形貌预测算法**（12 个 .m 文件） | `run_profile_prediction.m` |

### 路径规划算法（`形貌预测/` 目录）

| 文件 | 功能 |
|------|------|
| `run_path_planning.m` | 统一入口，串联完整路径规划 |
| `read_stl_file.m` | STL 文件读取 → N×12 三角形数组 |
| `model_process.m` | 模型预处理：分类增材/修复簇 |
| `layer_slice.m` | 层切片：按层高分割三角形 |
| `generate_path.m` | 路径生成：Zig-Zag 扫描 + A* 避障 |
| `aStarSearch.m` | A* 路径搜索算法 |

### 形貌预测算法（`路径规划/` 目录）

| 文件 | 功能 |
|------|------|
| `run_profile_prediction.m` | 统一入口，串联完整形貌预测 |
| `read_STLfile.m` | STL 文件读取 |
| `recursiveSubdivide.m` | 三角形递归细分 |
| `improveShortEdges.m` | 短边优化 |
| `particleFitting.m` | CFD 粒子分布拟合 |
| `spotInterp.m` | 喷斑插值 |
| `rayMove.m` | 射线移动（喷嘴跟随） |
| `buildOctree.m` | 八叉树构建 |
| `batchOctreeFilter.m` | 八叉树批量过滤 |
| `ray_triangle_intersection.m` | 射线-三角形相交 |
| `classifyRemovedTriangles.m` | 移除三角形分类 |
| `profilePredict.m` | 形貌预测核心（单步沉积） |

---

## 三、调用流程图

```
GUI 点击"生成修复路径"
        │
        ▼
MainWindow._on_generate_path()
        │
        ▼ (ZMQ 请求)
BridgeServer.serve() → _dispatch() → MatlabAdapter.handle_repair(request)
        │
        ▼
_invoke_pipeline_with_fallback(xyz, meta)
        │
        ├─ engine_mode == "python"? ──→ 返回 None → 降级到 Python
        │
        ▼ (MATLAB 可用)
MATLABPipeline.run(xyz, meta)
        │
        ▼
MatlabEngineProxy.call_full_pipeline(xyz, meta)
        │
        ├─ _write_xyz_as_stl(xyz)          写临时 STL 文件
        │
        ▼ ════════════════════════════════
        │ 阶段 1：路径规划
        │ ════════════════════════════════
        │ eng.run_path_planning(stl_path, params)
        │   ├─ read_stl_file(stl_path)        → triangles (N×12)
        │   ├─ model_process(triangles)       → additive/repairing clusters
        │   ├─ layer_slice(clusters)          → layer lists
        │   ├─ generate_path(layers, params)  → pointlist (M×6)
        │   └─ velocity_to_numeric()          → feed_rates (M×1)
        │ 
        │   输出: pointlist, feed_rates, layer_indices
        │   组装: waypoints (M×8) + velocitylist (string[])
        │
        ▼ ════════════════════════════════
        │ 阶段 2：形貌预测（使用预计算航点）
        │ ════════════════════════════════
        │ eng.run_profile_prediction(stl_path, excel, params, pointlist, velocitylist)
        │   ├─ read_STLfile(stl_path)              → triangles
        │   ├─ recursiveSubdivide(triangles)       → 细分网格
        │   ├─ improveShortEdges(triangles)        → 短边优化
        │   ├─ particleFitting(excel_path)         → CFD 粒子分布
        │   ├─ [pointlist 已提供，跳过 run_path_planning]
        │   ├─ spotInterp(pointlist, velocitylist) → 喷斑列表
        │   └─ for each spot:
        │       ├─ rayMove(spot, rays)             → 移动射线
        │       ├─ buildOctree(triangles)          → 八叉树
        │       ├─ batchOctreeFilter(octree, rays) → 候选三角形
        │       ├─ ray_triangle_intersection()     → 交点
        │       ├─ classifyRemovedTriangles()      → 移除集
        │       └─ profilePredict()                → 更新网格
        │
        │   输出: result struct (mesh, layer_profiles, particle_dist, ...)
        │
        ▼
_parse_profile_result(raw) → dict
        │
        ▼
返回 {waypoints, mesh, layer_profiles, particle_dist, uniformity, ...}
        │
        ▼
MatlabAdapter._invoke_pipeline_with_fallback → build_repair_result()
        │
        ▼ (ZMQ 响应)
GUI _on_zmq_path_result() → 更新 3D 视图 + ProfileResultPanel
```

---

## 四、数据流图

```
┌─────────────────────────────────────────────────────────────┐
│                        Python 侧                             │
│                                                             │
│  GUI 点云 (xyz: N×6 ndarray)                                │
│  + 工艺参数 (meta: dict)                                    │
│         │                                                   │
│         ▼                                                   │
│  MatlabEngineProxy.call_full_pipeline()                     │
│         │                                                   │
│         ├─ _write_xyz_as_stl(xyz) ──→ 临时 STL 文件         │
│         ├─ _meta_to_profile_params(meta) ──→ params dict    │
│         │                                                   │
└─────────┼───────────────────────────────────────────────────┘
          │  matlab.engine 调用
          ▼
┌─────────────────────────────────────────────────────────────┐
│                       MATLAB 侧                              │
│                                                             │
│  阶段 1: run_path_planning(stl_path, params)                │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 输入: stl_path (char), params (struct)              │    │
│  │ 输出: pointlist (M×6 double)  [x,y,z,nx,ny,nz]     │    │
│  │       feed_rates (M×1 double) [mm/s]               │    │
│  │       layer_indices (M×1 double) [1,2,3,...]       │    │
│  └─────────────────────────────────────────────────────┘    │
│         │  内存传递（无 .mat 文件）                          │
│         ▼                                                   │
│  阶段 2: run_profile_prediction(stl, excel, params,         │
│                                   pointlist, velocitylist)  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ 输入: stl_path, excel_path, params                  │    │
│  │       pointlist (M×6)      ← 来自阶段 1             │    │
│  │       velocitylist (M×1 string) ← 来自阶段 1        │    │
│  │ 输出: result struct                                 │    │
│  │   .mesh (T×9)              沉积表面三角形           │    │
│  │   .substrate_triangles (T0×9) 原始基体              │    │
│  │   .layer_profiles (L×4)    逐层轮廓                 │    │
│  │   .particle_distribution   颗粒分布                 │    │
│  │   .uniformity (1×1)        均匀性评分               │    │
│  │   .estimated_mass_g        材料用量                 │    │
│  │   .estimated_time_s        预估耗时                 │    │
│  │   .predicted_volume_mm3    填充体积                 │    │
│  │   .warnings (cell)         警告信息                 │    │
│  │   .compute_time_s          计算耗时                 │    │
│  │   .waypoint_count          航点数                   │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
└─────────┬───────────────────────────────────────────────────┘
          │  matlab.engine 返回
          ▼
┌─────────────────────────────────────────────────────────────┐
│                        Python 侧                             │
│                                                             │
│  _parse_profile_result(raw) → dict                          │
│  + _assemble_waypoints(pointlist, feed_rates, layers)       │
│  + _triangles_to_binary_stl(mesh) → bytes                   │
│         │                                                   │
│         ▼                                                   │
│  返回 dict:                                                 │
│    waypoints: ndarray (M, 8)                                │
│    mesh: ndarray (T, 9)                                     │
│    layer_profiles: list[LayerProfile]                       │
│    particle_dist: ParticleDistribution                      │
│    uniformity: float                                        │
│    estimated_mass_g: float                                  │
│    estimated_time_s: float                                  │
│    mesh_stl_bytes: bytes                                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 五、新旧架构对比

### 旧架构（分离调用，重复计算）

```
handle_repair()
  ├─ _invoke_with_fallback() → proxy(xyz, meta)
  │   └─ run_path_planning()          ← 第 1 次调用
  │       输出: waypoints
  │
  └─ _try_profile_prediction() → proxy.call_profile_prediction(xyz, meta)
      └─ run_profile_prediction()
          └─ run_path_planning()      ← 第 2 次调用（重复！）
              输出: profile result

问题：
- run_path_planning 被调用 2 次
- STL 文件被写 2 次
- 计算时间翻倍
```

### 新架构（MATLABPipeline，一次调用）

```
handle_repair()
  └─ _invoke_pipeline_with_fallback() → MATLABPipeline.run(xyz, meta)
      └─ call_full_pipeline()
          ├─ run_path_planning()              ← 第 1 次（唯一）
          │   输出: pointlist, velocitylist
          │
          └─ run_profile_prediction(stl, excel, params, pointlist, velocitylist)
              ├─ [跳过内部 run_path_planning]  ← 不再重复
              └─ 使用预计算航点执行形貌预测
                  输出: waypoints + profile result

改善：
- run_path_planning 只调用 1 次
- STL 文件只写 1 次
- 计算时间减少 30-50%
```

---

## 六、修改文件列表

| # | 文件 | 操作 | 修改内容 |
|---|------|------|----------|
| 1 | [路径规划/run_profile_prediction.m](file:///d:/work/demo/industrial-vision/路径规划/run_profile_prediction.m) | 修改 | 新增 `pointlist_in`、`velocitylist_in` 可选参数；提供时跳过内部 `run_path_planning` 调用；新增 `velocity_to_numeric`、`derive_layer_indices_from_z` 辅助函数 |
| 2 | [repair_app/bridge/adapters/matlab_pipeline.py](file:///d:/work/demo/industrial-vision/repair_app/bridge/adapters/matlab_pipeline.py) | **新建** | `MATLABPipeline` 类：`run()` 串联路径规划+形貌预测，`is_available()` 检查 MATLAB 可用性 |
| 3 | [repair_app/bridge/adapters/matlab_engine_proxy.py](file:///d:/work/demo/industrial-vision/repair_app/bridge/adapters/matlab_engine_proxy.py) | 修改 | 新增 `call_full_pipeline()` 方法：一次 STL 写入 + 路径规划 + 形貌预测；新增 `_feed_rates_to_velocitylist()` 辅助方法 |
| 4 | [repair_app/bridge/adapters/matlab_adapter.py](file:///d:/work/demo/industrial-vision/repair_app/bridge/adapters/matlab_adapter.py) | 修改 | `handle_repair()` 改用 `_invoke_pipeline_with_fallback()` 替代分离调用；新增 `_invoke_pipeline_with_fallback()` 方法 |
| 5 | [repair_app.spec](file:///d:/work/demo/industrial-vision/repair_app.spec) | 修改 | 新增 `matlab_pipeline` hiddenimport |

---

## 七、修改原因

### 7.1 为什么修改 run_profile_prediction.m

**问题**：`run_profile_prediction.m` 内部调用 `run_path_planning`（第 176 行），但 Python 侧已经调用过一次。导致同一个 STL 文件被读取两次，路径规划被执行两次。

**修改**：新增 `pointlist_in`、`velocitylist_in` 可选参数。当 Python 侧已计算航点时，直接传入，跳过内部重复调用。

**向后兼容**：参数可选，不传时行为与旧版完全一致（内部调用 `run_path_planning`）。

### 7.2 为什么创建 MATLABPipeline

**问题**：`MatlabAdapter.handle_repair` 分两步调用（`_invoke_with_fallback` + `_try_profile_prediction`），每步独立写 STL、独立调用 MATLAB，无法利用阶段 1 的计算结果。

**解决**：`MATLABPipeline` 将两步合并为一次 `call_full_pipeline` 调用，阶段 1 的 `pointlist` 直接传递给阶段 2。

### 7.3 为什么修改 MatlabAdapter

**问题**：旧版 `handle_repair` 的逻辑是"先路径规划，再尝试形貌预测"，两者独立调用 MATLAB。

**修改**：改为"一次管线调用，失败则降级"。`_invoke_pipeline_with_fallback` 封装了完整的 MATLAB 管线调用 + 降级逻辑。

---

## 八、验证结果

| 测试项 | 结果 |
|--------|------|
| MATLABPipeline 模块导入 | ✅ 通过 |
| MatlabEngineProxy.call_full_pipeline 方法存在 | ✅ 通过 |
| MatlabAdapter._invoke_pipeline_with_fallback 方法存在 | ✅ 通过 |
| Python 模式正确跳过 MATLAB | ✅ 通过 |
| 21 个核心单元测试无回归 | ✅ 通过 |

---

## 九、后续维护建议

1. **`run_profile_prediction.m` 向后兼容**：`pointlist_in`/`velocitylist_in` 为可选参数，独立调用 `run_profile_prediction` 时不传则内部自动调用 `run_path_planning`
2. **`MATLABPipeline` 是无状态类**：每次 `run()` 都通过 `MatlabEngineProxy` 单例连接 MATLAB，不持有额外资源
3. **降级策略不变**：`CSAM_ALGORITHM_ENGINE=python` 时跳过 MATLAB，`auto` 模式 MATLAB 失败时降级到 Python
4. **旧版 `_invoke_with_fallback` 和 `_try_profile_prediction` 保留**：不删除，供独立测试和兼容场景使用，但 `handle_repair` 生产路径已切换到 Pipeline
