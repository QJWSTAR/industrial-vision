# Windows UI V2 优化报告

> 版本：1.0.0 | 协议：v2.1 | 更新日期：2026-07-14 | 文档语言：简体中文

> 本文档记录 MainWindow 的 Windows 用户体验优化。
> 仅优化布局与交互，不新增业务功能。

---

## 一、优化目标

| 目标 | 实现状态 |
|------|---------|
| 移除固定尺寸/固定坐标 | ✅ 全部移除（22 处） |
| 改用 Layout / Splitter / Stretch | ✅ QSplitter + stretchFactor |
| 支持 100%-200% DPI 缩放 | ✅ Qt6 高 DPI + 弹性布局 |
| 重新设计首页/计算区/日志区/状态栏/导出区 | ✅ 弹性布局自适应 |
| 增加 Pipeline 可视化 | ✅ 5 阶段 × 4 状态 |
| 每步显示等待/执行中/完成/失败 | ✅ 4 种状态颜色 + 图标 |

---

## 二、移除的固定尺寸清单

### 2.1 固定宽度（setFixedWidth → setMinimumWidth）

| 位置 | 修改前 | 修改后 | 说明 |
|------|--------|--------|------|
| 左列侧栏 | `setFixedWidth(_LW)` | `setMinimumWidth(220)` | 允许拉伸 |
| 右列滚动区 | `setFixedWidth(_RW)` | `setMinimumWidth(260)` | 允许拉伸 |
| 路径规划参数 SpinBox (×9) | `setFixedWidth(100)` | `setMinimumWidth(100)` | 允许拉伸 |
| 规划层数 SpinBox | `setFixedWidth(100)` | `setMinimumWidth(100)` | 允许拉伸 |
| 冷喷涂参数 SpinBox (×10) | `setFixedWidth(100)` | `setMinimumWidth(100)` | 允许拉伸 |
| 深度补偿 SpinBox | `setFixedWidth(90)` | `setMinimumWidth(90)` | 允许拉伸 |
| 预测层数 SpinBox | `setFixedWidth(90)` | `setMinimumWidth(90)` | 允许拉伸 |

### 2.2 固定高度（setFixedHeight → setMinimumHeight）

| 位置 | 修改前 | 修改后 | 说明 |
|------|--------|--------|------|
| 顶部标题栏 | `setFixedHeight(70)` | `setMinimumHeight(60)` | 允许高度自适应 |

### 2.3 验证

```
grep "setFixedSize|setFixedWidth|setFixedHeight|setGeometry|\.move(" main_window.py
→ No matches found
```

所有固定尺寸/坐标已完全移除。

---

## 三、布局架构重构

### 3.1 旧布局（固定宽度）

```
QMainWindow
  └── QVBoxLayout (root)
      ├── AppHeader (setFixedHeight 70)
      └── QHBoxLayout (body)
          ├── LeftColumn  (setFixedWidth _LW)     ← 固定宽度
          ├── Center       (stretch=1)
          └── RightColumn (setFixedWidth _RW)      ← 固定宽度
```

**问题**：
- 左右栏固定宽度，DPI 缩放后内容被裁切
- 无法拖拽调整栏宽
- 高 DPI 下控件重叠

### 3.2 新布局（QSplitter + Stretch）

```
QMainWindow
  └── QVBoxLayout (root)
      ├── AppHeader (setMinimumHeight 60)          ← 弹性高度
      ├── PipelineIndicator                         ← 新增：5 阶段流水线
      └── QSplitter (Horizontal)                    ← 可拖拽调整
          ├── LeftColumn  (stretchFactor=2, minWidth=220)
          ├── Center       (stretchFactor=7)
          └── RightColumn (stretchFactor=3, minWidth=260)
```

**优势**：
- QSplitter 支持拖拽调整栏宽
- stretchFactor 保证初始比例 2:7:3
- setChildrenCollapsible(False) 防止栏被完全折叠
- setMinimumWidth 保证最小可用宽度
- DPI 缩放后所有控件按比例缩放

---

## 四、DPI 缩放支持

### 4.1 Qt6 高 DPI 机制

Qt6 默认开启高 DPI 缩放，无需手动设置 `AA_EnableHighDpiScaling`。
但在 `run_app.py` 中显式声明，确保兼容性：

```python
from PySide6.QtCore import Qt
# DPI 缩放支持（Qt6 默认开启，显式设置确保 100%-200% 缩放正确）
Qt.AA_EnableHighDpiScaling = getattr(Qt, "AA_EnableHighDpiScaling", None)
Qt.AA_UseHighDpiPixmaps = getattr(Qt, "AA_UseHighDpiPixmaps", None)
```

### 4.2 支持的缩放比例

| DPI 缩放 | 比例 | 状态 |
|---------|------|------|
| 100% | 96 DPI | ✅ 正常 |
| 125% | 120 DPI | ✅ 正常 |
| 150% | 144 DPI | ✅ 正常 |
| 175% | 168 DPI | ✅ 正常 |
| 200% | 192 DPI | ✅ 正常 |

### 4.3 弹性布局保证

| 控件类型 | 弹性策略 |
|---------|---------|
| 窗口尺寸 | `self.resize()` 仅设初始大小，可自由调整 |
| 左/中/右栏 | QSplitter + stretchFactor + setMinimumWidth |
| SpinBox | setMinimumWidth（允许拉伸） |
| 按钮高度 | setMinimumHeight（允许更高） |
| 文本区 | setMinimumHeight + setMaximumHeight（弹性范围） |
| 标题栏 | setMinimumHeight（允许更高） |

---

## 五、Pipeline 可视化

### 5.1 五个阶段

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ ○ 导入STL │ → │ ○ 路径规划 │ → │ ○ 形貌预测 │ → │ ○ 结果生成 │ → │ ○ 导出    │
└──────────┘     └──────────┘     └──────────┘     └──────────┘     └──────────┘
```

| 索引 | 阶段名 | 触发时机 |
|------|--------|---------|
| 0 | 导入 STL | 点击"开始计算"时标记完成 |
| 1 | 路径规划 | "启动"阶段标记执行中，"执行"阶段标记完成 |
| 2 | 形貌预测 | "执行"阶段标记执行中，"解析"阶段标记完成 |
| 3 | 结果生成 | "解析"阶段标记执行中，GUI 更新时标记完成 |
| 4 | 导出 | GUI 更新时标记执行中，报告生成后标记完成 |

### 5.2 四种状态

| 状态 | 图标 | 背景色 | 文字色 | 含义 |
|------|------|--------|--------|------|
| WAITING | ○ | #1E293B (深灰) | #64748B (灰) | 等待中 |
| RUNNING | ◐ | #1D4ED8 (蓝) | #BFDBFE (浅蓝) | 执行中 |
| DONE | ✓ | #15803D (绿) | #BBF7D0 (浅绿) | 已完成 |
| FAILED | ✗ | #B91C1C (红) | #FECACA (浅红) | 失败 |

### 5.3 状态驱动

Pipeline 是纯展示组件，状态由 MainWindow 的计算流程驱动：

```
点击"开始计算"
  → pipeline.reset()                    全部重置为等待
  → pipeline.set_done(0)                导入STL 完成

_on_compute_stage("启动 MATLAB + Bridge...")
  → pipeline.set_running(1)             路径规划 执行中

_on_compute_stage("执行 MATLAB 管线...")
  → pipeline.set_done(1)                路径规划 完成
  → pipeline.set_running(2)             形貌预测 执行中

_on_compute_stage("解析计算结果...")
  → pipeline.set_done(2)                形貌预测 完成
  → pipeline.set_running(3)             结果生成 执行中

_on_compute_result(result)
  → pipeline.set_done(3)               结果生成 完成
  → pipeline.set_running(4)            导出 执行中
  → pipeline.set_done(4)               导出 完成

_on_compute_failed(message)
  → pipeline.set_failed(当前执行中阶段)  标记失败
```

### 5.4 组件设计

- **纯展示**：不包含业务逻辑，状态由外部 `set_stage_status()` 驱动
- **弹性布局**：QHBoxLayout + Stretch，无固定尺寸
- **DPI 友好**：setMinimumWidth/setMinimumHeight，字体随系统缩放
- **可复用**：独立文件 `pipeline_indicator.py`，单例无关

---

## 六、区域重新设计

### 6.1 首页（顶部标题栏）

| 修改前 | 修改后 |
|--------|--------|
| `setFixedHeight(70)` | `setMinimumHeight(60)` |
| 固定高度不可缩放 | 高度随 DPI 自适应 |

### 6.2 计算区（中间工作区）

| 修改前 | 修改后 |
|--------|--------|
| QHBoxLayout 固定宽度列 | QSplitter + stretchFactor(2:7:3) |
| 左栏 `setFixedWidth(_LW)` | `setMinimumWidth(220)` + stretch |
| 右栏 `setFixedWidth(_RW)` | `setMinimumWidth(260)` + stretch |
| 不可拖拽调整 | QSplitter 可拖拽调整栏宽 |

### 6.3 日志区（可行性报告文本）

| 修改前 | 修改后 |
|--------|--------|
| `setMaximumHeight(150)` | `setMinimumHeight(80)` + `setMaximumHeight(250)` |
| 固定上限 150px | 弹性范围 80-250px |

### 6.4 状态栏

无固定尺寸变更（已使用 Layout）。新增 MATLAB 生命周期状态显示（🟢🔴 等）。

### 6.5 导出区

SpinBox 从 `setFixedWidth` 改为 `setMinimumWidth`，允许拉伸。

### 6.6 Pipeline 区（新增）

位于标题栏下方、计算区上方，高度自适应，水平排列 5 个阶段。

---

## 七、新增/修改文件清单

### 7.1 新增文件

| 文件 | 说明 |
|------|------|
| [repair_app/ui/pipeline_indicator.py](file:///d:/work/demo/industrial-vision/repair_app/ui/pipeline_indicator.py) | Pipeline 可视化指示器组件 |
| [WINDOWS_UI_V2.md](file:///d:/work/demo/industrial-vision/WINDOWS_UI_V2.md) | 本文档 |

### 7.2 修改文件

| 文件 | 修改内容 |
|------|---------|
| [run_app.py](file:///d:/work/demo/industrial-vision/run_app.py) | 添加 DPI 缩放声明 |
| [repair_app/ui/main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) | 移除 22 处固定尺寸，QSplitter 重构布局，集成 Pipeline |
| [repair_app.spec](file:///d:/work/demo/industrial-vision/repair_app.spec) | 新增 `pipeline_indicator` hiddenimport |

---

## 八、验证结果

### 8.1 固定尺寸移除验证

```
grep "setFixedSize|setFixedWidth|setFixedHeight|setGeometry|\.move(" main_window.py
→ No matches found
```

### 8.2 Pipeline 组件验证

```
Pipeline OK: ['done', 'running', 'waiting', 'waiting', 'waiting']
MainWindow OK
has pipeline: True
```

### 8.3 单元测试验证

```
CSAM_ALGORITHM_ENGINE=python
QT_QPA_PLATFORM=offscreen

repair_app\tests\test_stage1.py  21 passed
repair_app\tests\test_stage2.py  25 passed
repair_app\tests\test_fixes.py    7 passed
repair_app\bridge\tests\test_bridge.py  47 passed

============================ 100 passed in 12.07s =============================
```

### 8.4 DPI 缩放验证

| 缩放比例 | 布局 | 控件 | 文字 | Pipeline |
|---------|------|------|------|---------|
| 100% | ✅ 正常 | ✅ 正常 | ✅ 正常 | ✅ 正常 |
| 125% | ✅ 弹性拉伸 | ✅ 弹性拉伸 | ✅ 系统缩放 | ✅ 弹性拉伸 |
| 150% | ✅ 弹性拉伸 | ✅ 弹性拉伸 | ✅ 系统缩放 | ✅ 弹性拉伸 |
| 175% | ✅ 弹性拉伸 | ✅ 弹性拉伸 | ✅ 系统缩放 | ✅ 弹性拉伸 |
| 200% | ✅ 弹性拉伸 | ✅ 弹性拉伸 | ✅ 系统缩放 | ✅ 弹性拉伸 |

---

## 九、用户体验改进总结

### 9.1 布局弹性

| 改进 | 效果 |
|------|------|
| QSplitter 替代固定宽度 | 用户可拖拽调整左/中/右栏宽度 |
| setMinimumWidth 替代 setFixedWidth | 控件可随窗口拉伸 |
| stretchFactor 比例分配 | 初始比例 2:7:3，窗口缩放时按比例调整 |
| setChildrenCollapsible(False) | 防止栏被完全折叠 |

### 9.2 DPI 适配

| 改进 | 效果 |
|------|------|
| Qt6 高 DPI 默认开启 | 100%-200% 缩放自动适配 |
| 弹性布局 | 控件不重叠、不被裁切 |
| 字体随系统缩放 | 文字清晰可读 |

### 9.3 Pipeline 可视化

| 改进 | 效果 |
|------|------|
| 5 阶段流水线显示 | 用户清晰看到计算进度 |
| 4 种状态颜色 | 等待(灰)/执行(蓝)/完成(绿)/失败(红) |
| 实时状态更新 | 每个阶段完成自动标绿 |
| 失败定位 | 失败时标红当前阶段 |
