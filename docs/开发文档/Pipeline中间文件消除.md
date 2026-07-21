# Pipeline 中间文件消除报告

> 日期：2026-07-14 | 版本：1.0.0
> 目标：消除所有人工中间文件，数据统一通过内存或 Bridge 传递

---

## 一、删除的文件

### 1.1 遗留中间数据文件（5 个）

| 文件 | 位置 | 删除原因 |
|------|------|----------|
| `pointlist.npz` | `morphology_prediction/` | 旧版路径规划落盘的航点数据，已被内存传递替代 |
| `velocitylist.json` | `morphology_prediction/` | 旧版路径规划落盘的速度列表，已被内存传递替代 |
| `pointlist.npz` | `形貌预测/` | 算法目录中的残留副本 |
| `velocitylist.json` | `形貌预测/` | 算法目录中的残留副本 |
| `pointlist.npz` | `dist/morphology_prediction/` | 打包构建残留 |

### 1.2 删除的流程

| 流程 | 旧版行为 | 新版行为 |
|------|----------|----------|
| 路径规划 → 落盘 `pointlist.npz` | 写入项目目录 `morphology_prediction/` | 写入系统临时目录 `%TEMP%/csam_cache_*/`，退出自动清理 |
| 路径规划 → 落盘 `velocitylist.json` | 写入项目目录 | 同上 |
| 形貌预测 → 从项目目录加载 | `load_waypoints()` 读项目目录 | 优先用内存数据；内存丢失时从缓存目录恢复 |
| MATLABPipeline 内部传递 | 旧版分两步调用，中间落盘 | 一次调用，`pointlist` 内存传递给 `run_profile_prediction` |

---

## 二、新的数据流

### 2.1 生产路径（MATLABPipeline — 内存传递）

```
GUI 点击"生成修复路径"
        │
        ▼
MatlabAdapter.handle_repair()
        │
        ▼
MATLABPipeline.run(xyz, meta)
        │
        ▼
MatlabEngineProxy.call_full_pipeline(xyz, meta)
        │
        ├─ _write_xyz_as_stl(xyz)
        │   └─ 写入 %TEMP%/csam_cloud_*.stl（临时，finally 自动删除）
        │
        ├─ 阶段 1: eng.run_path_planning(stl_path, params)
        │   └─ 返回 pointlist, feed_rates, layer_indices
        │       ↓ 内存传递（不落盘）
        │
        ├─ 阶段 2: eng.run_profile_prediction(stl_path, excel, params, pointlist, velocitylist)
        │   └─ 使用阶段 1 的 pointlist，跳过内部重复计算
        │   └─ 返回 result struct
        │
        └─ finally: os.remove(stl_path)  ← 自动清理临时 STL
        │
        ▼
返回 dict {waypoints, mesh, layer_profiles, ...}
        │
        ▼ (ZMQ 响应)
GUI 收到完整结果 → 直接渲染（无需任何文件 I/O）
```

**全程零人工文件。** 临时 STL 在 `finally` 中自动删除。

### 2.2 降级路径（Python 启发式 — 内存 + 缓存）

```
MATLAB 不可用
        │
        ▼
MatlabAdapter._default_algorithm(xyz, meta)
        │
        ▼
Python 启发式路径规划 → waypoints（内存）
        │
        ├─ if 用户勾选"保存中间文件":
        │   └─ FileRepository.save_waypoints()
        │       └─ 写入 %TEMP%/csam_cache_*/pointlist.npz
        │          写入 %TEMP%/csam_cache_*/velocitylist.json
        │          （atexit 注册：软件退出自动清理）
        │
        └─ else:
            └─ 仅保留在内存中
        │
        ▼
GUI 形貌预测步骤
        │
        ├─ 优先: 使用内存中的 waypoints
        └─ 降级: 内存丢失时从 %TEMP%/csam_cache_*/ 加载
```

### 2.3 缓存目录生命周期

```
软件启动
  │
  ├─ FileRepository.__init__()
  │   └─ _get_cache_dir()
  │       └─ tempfile.mkdtemp(prefix="csam_cache_")
  │           → 创建 %TEMP%/csam_cache_XXXXXX/
  │       └─ atexit.register(_cleanup_cache_dir)
  │           → 注册退出回调
  │
  ├─ 运行期间
  │   └─ pointlist.npz / velocitylist.json 写入缓存目录
  │   └─ 临时 STL 写入 %TEMP%/csam_cloud_*.stl（用完即删）
  │
  └─ 软件退出
      └─ atexit 触发 _cleanup_cache_dir()
          └─ shutil.rmtree(%TEMP%/csam_cache_XXXXXX/)
              → 缓存目录及内容全部删除
```

---

## 三、修改文件列表

| # | 文件 | 修改内容 |
|---|------|----------|
| 1 | [file_repository.py](file:///d:/work/demo/industrial-vision/repair_app/repository/file_repository.py) | 新增 `_get_cache_dir()` / `_cleanup_cache_dir()`；缓存目录用 `tempfile.mkdtemp` 创建，`atexit` 注册自动清理；`save_waypoints` 写入缓存目录而非项目目录 |
| 2 | [config.py](file:///d:/work/demo/industrial-vision/repair_app/utils/config.py) | `get_pointlist_file()` / `get_velocitylist_file()` 改为返回缓存目录路径 |
| 3 | [main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) | 保存提示改为"缓存航点数据"；加载逻辑改为内存优先、缓存降级；来源标签改为"内存 (MATLAB Pipeline)" |

---

## 四、修改原因

### 4.1 为什么删除 pointlist.npz / velocitylist.json

**问题**：旧版路径规划完成后，将航点数据写入项目目录 `morphology_prediction/` 或 `形貌预测/`。用户需要手动复制这些文件到正确位置才能进行形貌预测。

**解决**：
- 生产路径：`MATLABPipeline.call_full_pipeline` 将 `pointlist` 直接内存传递给 `run_profile_prediction`，无需任何文件
- 降级路径：写入系统临时目录（`%TEMP%/csam_cache_*/`），`atexit` 注册自动清理

### 4.2 为什么用系统临时目录而非项目目录

| 维度 | 项目目录（旧） | 系统临时目录（新） |
|------|----------------|---------------------|
| 污染项目 | 是，产生 .npz/.json 文件 | 否，项目目录保持干净 |
| 需要人工清理 | 是 | 否，atexit 自动清理 |
| Git 误提交 | 可能 | 不可能（在 %TEMP% 下） |
| 跨会话残留 | 是 | 否，每次启动创建新目录 |
| 崩溃后残留 | 是 | 系统定期清理 %TEMP% |

### 4.3 为什么内存优先、缓存降级

```
形貌预测步骤加载航点：
  1. 优先: self._mock_waypoints（内存中已有）
  2. 降级: FileRepository.load_waypoints()（从缓存目录恢复）

原因：
- 正常流程下，路径规划结果已在内存中，无需文件 I/O
- 仅在内存丢失（如 GUI 重启但缓存仍在）时从缓存恢复
- 缓存目录在软件退出时自动清理，不会残留
```

---

## 五、验证结果

| 测试项 | 结果 |
|--------|------|
| FileRepository 导入 | ✅ 通过 |
| 缓存目录在 `%TEMP%` 下 | ✅ 通过 |
| pointlist/velocitylist 路径在缓存目录下 | ✅ 通过 |
| save/load 功能正常 | ✅ 通过 |
| 项目目录无中间文件 | ✅ 通过 |
| `config.get_pointlist_file` 指向缓存目录 | ✅ 通过 |
| `_cleanup_cache_dir` 正确清理 | ✅ 通过 |
| 47 个核心单元测试无回归 | ✅ 通过 |

---

## 六、中间文件消除对照表

| 文件类型 | 旧版 | 新版 | 状态 |
|----------|------|------|------|
| `pointlist.mat` | MATLAB `save()` 写入项目目录 | 已删除（MATLAB 无 `save()` 调用） | ✅ 消除 |
| `velocitylist.mat` | MATLAB `save()` 写入项目目录 | 已删除 | ✅ 消除 |
| `pointlist.npz` | Python `np.savez()` 写入项目目录 | 写入 `%TEMP%/csam_cache_*/`，退出清理 | ✅ 消除 |
| `velocitylist.json` | Python `json.dump()` 写入项目目录 | 写入 `%TEMP%/csam_cache_*/`，退出清理 | ✅ 消除 |
| 临时 STL | `tempfile.mkstemp` 写入 `%TEMP%` | 不变（已符合要求，`finally` 自动删除） | ✅ 保持 |
| 临时 txt/csv | 无（扫描确认 MATLAB 无 `writematrix`/`writetable` 调用） | 无 | ✅ 消除 |

---

## 七、总结

### 消除效果

| 指标 | 旧版 | 新版 |
|------|------|------|
| 人工需复制的文件 | 2 个（pointlist.npz + velocitylist.json） | **0 个** |
| 项目目录污染 | 有（.npz/.json 文件残留） | **无** |
| 中间文件清理 | 手动 | **自动（atexit）** |
| 数据传递方式 | 文件 I/O | **内存传递** |
| MATLAB 重复计算 | 2 次 run_path_planning | **1 次** |

### 最终数据流

```
导入 STL → MATLABPipeline（内存传递）→ GUI 渲染 → 导出
                    ↑
            零人工文件
            零项目目录污染
            零手动清理
```
