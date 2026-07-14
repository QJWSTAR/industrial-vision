# GUI 可视化升级设计文档

> 任务：将 MATLAB 形貌预测计算结果完全用 Python 原生渲染展示。
> 不使用截图、PNG、MATLAB Figure。保持 Bridge / ZeroMQ / Protobuf 全部兼容。

## 1. 设计目标

| 目标 | 说明 |
|------|------|
| 完全原生渲染 | 所有图形由 Python（matplotlib + PySide6）绘制，不依赖 MATLAB 图形系统 |
| 工业软件风格 | 暗色主题、指标卡片、Tab 多视图、统一色温图 |
| 交互完整 | 缩放、平移、旋转、刷新、导出 PNG（matplotlib NavigationToolbar2QT 内置） |
| 数据驱动 | MATLAB 返回什么数值，Python 就渲染什么，无伪造数据 |
| 不破坏现有架构 | GUI 独立于 MATLAB；通信协议、Bridge、ZeroMQ、Protobuf 不变 |

## 2. MATLAB 输出数据分析

MATLAB `run_profile_prediction()` 经 Protobuf v2.1 返回以下字段（`parse_repair_result` 解析后）：

| 字段 | 类型 | 含义 | 来源 |
|------|------|------|------|
| `mesh_bytes` | bytes | 二进制 STL（80 头 + 4 面数 + N×50 字节） | `profilePredict` 输出三角网格 |
| `mesh_format` | str | `"stl_binary"` | 协议标识 |
| `layer_profiles` | List[dict] | 每层 `{layer_index, max_height_mm, avg_height_mm, dep_efficiency}` | `compute_layer_profiles` |
| `particle_dist` | dict | `{px,py,vx,vy,vz,vcr,diameter,temperature,dep_efficiency,total_particles}` | `particleFitting` |
| `uniformity_score` | float | [0,1] 沉积均匀性 | `compute_uniformity` |
| `estimated_mass_g` | float | 材料用量 (g) | 体积×密度 |
| `estimated_time_s` | float | 预计耗时 (s) | 路径长度/移动速度 |
| `predicted_volume_mm3` | float | 沉积体积 (mm³) | `compute_deposition_volume` |
| `waypoints` | (N,7) | x,y,z,nx,ny,nz,feed_rate | 路径规划 |
| `waypoint_layers` | (N,) | 每个航点的层号 | 路径规划 |

## 3. 渲染方案设计

### 3.1 数据 → 视图映射

```
pointlist (waypoints)
    ↓
路径动画（RepairVisualizer 已有：3D 路径线 + 航点标记 + 逐层动画）

mesh (STL bytes)
    ↓
PyVista? → 否，未安装
matplotlib Poly3DCollection（3D 三角网格，按 Z 着色）

layer_profiles
    ↓
双轴柱状图 + 曲线（左轴：最大/平均高度；右轴：沉积效率）

particle_distribution
    ↓
XY 散点热力图（颜色=速度大小） + 速度分布直方图

uniformity
    ↓
半圆仪表盘（0-100%，颜色分级：红/黄/绿）
```

### 3.2 技术选型决策

| 选项 | 决定 | 原因 |
|------|------|------|
| PyVista / VTK | ❌ 不采用 | 未安装，新增 200MB+ 依赖，违反"GUI 独立"约束 |
| matplotlib 3D | ✅ 采用 | 已是项目依赖，与现有 RepairVisualizer 一致 |
| NavigationToolbar2QT | ✅ 采用 | matplotlib 内置，免费获得缩放/旋转/导出 |
| PySide6 原生控件 | ✅ 采用 | 指标卡片、Tab、按钮 |

## 4. 实现清单

### 4.1 新增文件

**[repair_app/ui/profile_result_panel.py](file:///d:/work/demo/industrial-vision/repair_app/ui/profile_result_panel.py)**

`ProfileResultPanel` 类：MATLAB 形貌预测结果原生可视化面板。

**布局：**
```
┌─────────────────────────────────────────────────────────┐
│  [材料用量] [预计耗时] [沉积体积] [均匀性] [粒子总数] [警告数]  │  ← 指标卡片行
├─────────────────────────────────────────────────────────┤
│ ┌─Tab─┐                                                  │
│ │沉积网格│ 逐层轮廓 │ 粒子分布 │ 均匀性仪表│              │
│ ├─────┴────────────────────────────────────────────────┤ │
│ │ [matplotlib 工具栏：缩放/平移/旋转/刷新/导出 PNG]       │ │
│ │                                                        │ │
│ │           当前 Tab 的 matplotlib 图形                  │ │
│ │                                                        │ │
│ └────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────┤
│  [🔄 刷新所有视图]    状态: 已加载 MATLAB 结果 · 5 层     │
└─────────────────────────────────────────────────────────┘
```

**核心方法：**
- `set_profile_result(result: dict)`：接收完整 MATLAB 结果，触发所有视图重绘
- `decode_binary_stl(data: bytes) -> np.ndarray`：解析二进制 STL 为 (N,9) 顶点矩阵
- `refresh()`：刷新所有视图
- `clear()`：清空

**4 个 Tab 渲染细节：**

| Tab | 渲染方式 | 颜色策略 |
|-----|---------|---------|
| 沉积网格 | `Poly3DCollection`，3D 三角面 | 按 Z 高度着色（蓝→绿→黄→红） |
| 逐层轮廓 | `bar` + `twinx` 双轴 | 蓝色最大高度 / 绿色平均高度 / 橙色效率曲线 |
| 粒子分布 | `scatter` + `hist` | 速度大小热力图（青→黄→红） |
| 均匀性仪表 | `Wedge` 半圆 | ≥85% 绿 / ≥70% 黄 / <70% 红 |

### 4.2 修改文件

**[repair_app/ui/repair_visualizer.py](file:///d:/work/demo/industrial-vision/repair_app/ui/repair_visualizer.py)**
- 新增 `NavigationToolbar2QT` 导入
- 在 `_init_ui` 中为 3D 预览图添加工具栏（缩放、平移、旋转、刷新、导出 PNG）

**[repair_app/ui/main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py)**
- 导入 `ProfileResultPanel`
- `_center()`：新增 `QTabWidget`（中心区 Tab 切换器），把 `RepairVisualizer` 和 `ProfileResultPanel` 作为两个 Tab
- `_on_zmq_path_result()`：MATLAB 结果到达时，转发完整 dict 到 `_profile_panel.set_profile_result()`
- `_finish_path_planning()`：完成对话框提示用户切换到"MATLAB 形貌分析"Tab

## 5. 数据流

```
GUI 用户点击"生成修复路径"
    ↓
MainWindow._on_generate_path()
    ↓ ZMQ REQ
Bridge (ZeroMQ REP)
    ↓
MatlabAdapter.handle_repair()
    ↓
matlab_engine_proxy.call_profile_prediction()
    ↓ MATLAB engine
run_profile_prediction.m
    ↓ profilePredict + 全部依赖
返回结构体 (mesh/layer_profiles/particle_dist/...)
    ↓ _build_viz_from_profile
Protobuf RepairResult (v2.1)
    ↓ ZeroMQ REP
MainWindow._on_zmq_path_result()
    ↓ parse_repair_result
    ├→ _finish_path_planning (航点 → RepairVisualizer 3D 预览)
    └→ _profile_panel.set_profile_result (完整数据 → ProfileResultPanel)
        ↓
    ┌───────────────────────────────────┐
    │  指标卡片：mass/time/vol/unif/...  │
    │  Tab 1: STL → 3D 三角网格          │
    │  Tab 2: layer_profiles → 双轴图    │
    │  Tab 3: particle_dist → 热力图     │
    │  Tab 4: uniformity → 仪表盘        │
    └───────────────────────────────────┘
    ↓ Python 原生 matplotlib 渲染
用户实时查看（可缩放/旋转/导出）
```

## 6. 交互能力

所有 matplotlib 图形自带 `NavigationToolbar2QT` 工具栏：

| 工具 | 功能 |
|------|------|
| 🏠 Home | 恢复初始视图 |
| ◀ ▶ | 前进/后退视图历史 |
| 🔍 Drag | 矩形缩放 |
| ✋ Drag | 平移 |
| ⚙ | 子图参数调整 |
| 💾 | 导出 PNG（用户可选保存位置） |

3D 网格图额外支持鼠标拖拽旋转。

底部"🔄 刷新所有视图"按钮强制重绘所有 Tab。

## 7. 工业软件风格

- **暗色主题**：`#0F172A` 背景，`#1E293B` 网格，`#94A3B8` 文字
- **指标卡片**：圆角边框，数值大字号，按状态变色（绿/黄/红）
- **Tab 样式**：选中态蓝色高亮，悬停态浅色
- **色温图**：沉积高度用蓝→红渐变（冷→热），速度用青→红
- **仪表盘**：半圆 + 刻度 + 评价文字（优秀/良好/一般/较差）

## 8. 兼容性保证

| 项目 | 状态 |
|------|------|
| GUI 独立于 MATLAB | ✅ Python 仅消费数值，不调用 MATLAB 图形 |
| 通信协议不变 | ✅ Protobuf v2.1 字段全部复用 |
| Bridge 不变 | ✅ MatlabAdapter 仅在 handle_repair 内转发 |
| ZeroMQ 不变 | ✅ REP/REQ 拓扑不变 |
| 降级兼容 | ✅ MATLAB 不可用时 ProfileResultPanel 显示"等待数据"，不影响主流程 |
| 现有 3D 预览保留 | ✅ RepairVisualizer 作为第一个 Tab 完整保留 |
| 测试无回归 | ✅ 264 个测试全部通过 |

## 9. 与上一阶段（路径规划接入）对比

| 维度 | 路径规划接入 | 形貌预测可视化升级 |
|------|-------------|-------------------|
| 数据来源 | MATLAB waypoints | MATLAB mesh + layer_profiles + particle_dist + uniformity |
| GUI 改动 | 无（仅填充已有字段） | 新增 Tab + 4 个视图 |
| 可视化方式 | 复用 RepairVisualizer | 新增 ProfileResultPanel 原生渲染 |
| 交互 | 仅逐层动画 | 缩放/旋转/导出 PNG |
| 数据量 | (N,7) 航点 | STL 网格 + 多维粒子分布 |

## 10. 已知限制

1. STL 解码为纯 Python 循环，超大型网格（>10 万面）可能较慢；后续可换 numpy 批量解析
2. 粒子分布仅展示 XY 投影，未做 3D 体素化
3. 仪表盘为静态半圆，未做动画过渡
4. 导出格式仅 PNG（matplotlib 限制）；如需 SVG/PDF 可扩展工具栏

## 11. 后续工作

- [ ] 粒子分布 3D 体素可视化（可选 PyVista 或 VTK 显式安装后）
- [ ] STL 解码改用 `numpy.frombuffer` 批量解析提升性能
- [ ] 仪表盘动画过渡（QPropertyAnimation）
- [ ] 多工况对比视图（叠加多次预测结果）
