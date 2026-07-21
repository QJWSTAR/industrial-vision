# GUI 工业化重构报告（GUI_REVIEW）

> 参考 Siemens NX / Materialise Magics / Geomagic / ANSYS / SolidWorks / Visual Studio / MATLAB
> 目标：让软件更像商业工业软件
> 日期：2026-07-15

---

## 一、参考基准

| 参考软件 | 借鉴点 |
|---------|--------|
| **Siemens NX** | 菜单结构（File/Edit/View/Tools）、工具栏、紧凑信息密度、Dock 面板 |
| **Materialise Magics** | 深色主题、状态栏分区、3D 视图控制、右键菜单 |
| **Geomagic** | 视图视角切换、选区操作、参数面板布局 |
| **ANSYS** | 状态色规范（绿/橙/红）、进度条样式、Busy 指示器 |
| **SolidWorks** | Edit 菜单（Undo/Redo）、CommandManager 工具栏、特征树 |
| **Visual Studio** | Dark Theme 调色板、Tab 样式、ToolTip、Toast 通知 |
| **MATLAB** | 浅色主题支持、菜单栏简洁性、Plot 工具栏 |

---

## 二、重构前的 GUI 问题

| 维度 | 问题 |
|------|------|
| **一致性** | 颜色硬编码散落 4+ 文件（#0B1120 / #1E293B / #2563EB 等），无统一调色板 |
| **字体** | QSS 内 font-size 硬编码，无 QFont 应用，CJK 字体未显式指定 |
| **留白** | padding/margin 硬编码，无间距系统 |
| **按钮** | 仅一种按钮样式，无主按钮/危险按钮区分 |
| **图标** | 无图标资源文件，全靠 emoji（🤖🎯📐⚙️） |
| **Ribbon** | 无 QToolBar，功能入口仅靠菜单 + 左侧步骤按钮 |
| **菜单** | 仅 3 个菜单（文件/工具/帮助），缺 Edit / View 菜单 |
| **状态栏** | 4 个永久部件（版本/License/项目/连接），无 Busy 指示器 |
| **Dock** | 无 QDockWidget，使用 QSplitter 不可拖拽停靠 |
| **Progress** | 单一进度条，无不确定模式动画 |
| **Notification** | 无 Toast / 系统托盘，反馈靠模态对话框 |
| **Wizard** | 自定义 CalibrationWizard，非 QWizard 框架 |
| **Shortcut** | 仅 7 个快捷键，缺 Ctrl+Z/S/O/F |
| **Context Menu** | 无右键菜单 |
| **Recent File** | 已实现（RecentProjects 类 + 子菜单） |
| **Undo/Redo** | 仅缺陷选区局部 undo，无 QUndoStack 命令模式 |
| **Busy State** | 无忙碌指示器，仅进度条 |
| **Loading** | LoadingDialog 有不确定进度条，无旋转动画 |

---

## 三、重构后的 GUI 架构

### 3.1 新增组件

| 组件 | 文件 | 职责 |
|------|------|------|
| **ThemeManager** | [theme_manager.py](file:///d:/work/demo/industrial-vision/repair_app/ui/theme_manager.py) | 统一设计 token + QSS 生成 + 主题切换 |
| **Toast** | [toast.py](file:///d:/work/demo/industrial-vision/repair_app/ui/toast.py) | 非模态浮层通知（4 级别） |
| **BusyIndicator** | [busy_indicator.py](file:///d:/work/demo/industrial-vision/repair_app/ui/busy_indicator.py) | 状态栏旋转动画 + 文字标签 |
| **UndoStack** | [undo_framework.py](file:///d:/work/demo/industrial-vision/repair_app/ui/undo_framework.py) | QUndoStack + Ctrl+Z/Y |
| **ContextMenuManager** | [context_menu.py](file:///d:/work/demo/industrial-vision/repair_app/ui/context_menu.py) | 视图右键菜单 |

### 3.2 设计 Token 体系（ThemeManager）

```
ThemeManager
├── Palette（调色板）
│   ├── Dark（深色，默认）
│   └── Light（浅色，可切换）
├── Typography（排版）
│   ├── family_ui: Segoe UI / Microsoft YaHei UI / PingFang SC
│   ├── family_mono: Cascadia Code / Consolas
│   └── 7 级字号（10/12/13/14/16/20/24px）
├── Spacing（间距，8px 栅格）
│   └── xs/sm/md/lg/xl/xxl
└── Radius（圆角，工业软件偏方正）
    └── none/sm(3)/md(4)/lg(6)/pill(10)
```

### 3.3 菜单结构（参考 Siemens NX / SolidWorks）

重构前：文件 / 工具 / 帮助（3 个菜单）
重构后：**文件 / 编辑 / 视图 / 工具 / 帮助**（5 个菜单）

```
文件(&F)
├── 打开点云...          Ctrl+O
├── ─────────
├── 保存项目              Ctrl+S
├── 打开项目...
├── ─────────
├── 最近项目 ▸            （子菜单，动态填充）
├── ─────────
├── 打开导出目录
├── 打开日志目录
├── ─────────
└── 退出                  Ctrl+Q

编辑(&E)                   ← 新增
├── 撤销                  Ctrl+Z
├── 重做                  Ctrl+Y
├── ─────────
├── 清除选区
├── ─────────
└── 参数预设管理...        Ctrl+Shift+P

视图(&V)                   ← 新增
├── 重置视角              F
├── 适应窗口              Ctrl+Shift+F
├── ─────────
├── 显示/隐藏坐标轴        （复选）
├── ─────────
└── 主题 ▸
    ├── 深色主题           （复选）
    └── 浅色主题           （复选）

工具(&T)
├── 🤖 导出工业机器人轨迹...  Ctrl+R
├── ─────────
├── 🎯 单道沉积标定向导...    Ctrl+Shift+C
├── 📐 坐标系变换...          Ctrl+Shift+T
├── ─────────
├── ⚙️ 参数预设管理...        Ctrl+Shift+P
├── 🔬 批量验证...            Ctrl+Shift+B
└── ✓ 参数校验器...           Ctrl+Shift+V

帮助(&H)
├── 关于
└── 关于 Qt
```

### 3.4 工具栏（参考 SolidWorks CommandManager）

新增 QToolBar，包含：
- 📂 打开（Ctrl+O）
- 💾 保存（Ctrl+S）
- ─── 分隔 ───
- ↩ 撤销（Ctrl+Z）
- ↪ 重做（Ctrl+Y）
- ─── 分隔 ───
- 🎯 重置视角（F）
- 🔍 适应（Ctrl+Shift+F）
- ─── 分隔 ───
- 🌙 主题（切换深色/浅色）

### 3.5 状态栏（参考 ANSYS / VS Code）

```
[就绪] [处理中...]  |  v1.0.0  |  ✅ License 有效  |  项目: 未命名  |  ⚫ 本地模式
   ↑                    ↑              ↑                   ↑               ↑
BusyLabel           版本        License状态          项目名         连接模式
(旋转动画+文字)
```

**BusyLabel**：计算时显示旋转动画 + "处理中..."，空闲时显示"就绪"。

### 3.6 右键上下文菜单（参考 NX / Geomagic）

在 3D 视图上右键弹出：
```
视图
├── 重置视角              F
├── 适应窗口              Ctrl+Shift+F
└── 显示/隐藏坐标轴

选区
├── 清除选区
└── 反选

工具
├── 撤销                  Ctrl+Z
└── 重做                  Ctrl+Y

导出
├── 导出 G-code...        Ctrl+E
└── 导出机器人轨迹...     Ctrl+R
```

### 3.7 Toast 通知（参考 VS Code）

非模态浮层，右下角显示，自动消失：
- `Toast.info(parent, "项目已保存")` — 蓝色，3 秒
- `Toast.success(parent, "计算完成")` — 绿色，3 秒
- `Toast.warning(parent, "MATLAB 未启动")` — 橙色，4 秒
- `Toast.error(parent, "导出失败")` — 红色，5 秒

特性：淡入淡出动画、多条堆叠、不抢焦点。

### 3.8 Undo/Redo 框架（参考 SolidWorks 特征树）

基于 Qt QUndoStack + QUndoCommand：
- `UndoStack.instance()` — 全局单例
- `CallbackAction` — 基于回调的可撤销动作
- `SelectionAction` — 选区操作动作
- `create_undo_action()` / `create_redo_action()` — 自动联动 enabled

快捷键：
- Ctrl+Z — 撤销
- Ctrl+Y / Ctrl+Shift+Z — 重做

---

## 四、QSS 统一管理

### 4.1 重构前

```python
# main_window.py 第 102-242 行
_DARK_THEME_QSS = """
    QMainWindow, QWidget { background:#0B1120; color:#CBD5E1; ... }
    QPushButton { background:#1E293B; ... }
    ...
"""
self.setStyleSheet(_DARK_THEME_QSS)
```

问题：颜色硬编码、散落多处、无法切换主题。

### 4.2 重构后

```python
# main_window.py
def _apply_theme(self):
    self.setStyleSheet(ThemeManager.get_qss())

# run_app.py
ThemeManager.apply(app, theme="dark")  # 统一应用到 QApplication
```

ThemeManager 生成 16000+ 字符的完整 QSS，覆盖 20+ 控件类型：
- 基础控件（QMainWindow / QWidget / QLabel / QPushButton）
- 输入控件（QComboBox / QSpinBox / QTextEdit / QLineEdit）
- 选择控件（QCheckBox / QRadioButton）
- 容器（QGroupBox / QScrollArea / QFrame）
- 导航（QMenuBar / QMenu / QToolBar / QTabWidget）
- 反馈（QProgressBar / QStatusBar / QToolTip）
- 滚动（QScrollBar）
- 高级（QDockWidget / QHeaderView / QTableView）

### 4.3 Design Token 示例

```python
@dataclass(frozen=True)
class Palette:
    bg_app: str = "#0B1120"          # 应用主背景
    bg_panel: str = "#0F172A"        # 面板背景
    accent: str = "#2563EB"          # 主强调色
    success: str = "#10B981"         # 成功
    warning: str = "#F59E0B"         # 警告
    error: str = "#EF4444"           # 错误
    # ... 30+ 命名颜色

@dataclass(frozen=True)
class Typography:
    family_ui: str = "'Segoe UI', 'Microsoft YaHei UI', 'PingFang SC', sans-serif"
    size_body: str = "12px"
    # ... 7 级字号
```

改色只需修改 theme_manager.py 一处，全项目自动生效。

---

## 五、快捷键完整清单

| 快捷键 | 功能 | 来源 |
|--------|------|------|
| Ctrl+O | 打开点云 | 新增 |
| Ctrl+S | 保存项目 | 新增 |
| Ctrl+Q | 退出 | 原有 |
| **Ctrl+Z** | **撤销** | **新增** |
| **Ctrl+Y** | **重做** | **新增** |
| **Ctrl+Shift+Z** | **重做（备选）** | **新增** |
| **F** | **重置视角** | **新增** |
| **Ctrl+Shift+F** | **适应窗口** | **新增** |
| Ctrl+R | 导出机器人轨迹 | 原有 |
| Ctrl+Shift+C | 标定向导 | 原有 |
| Ctrl+Shift+T | 坐标系变换 | 原有 |
| Ctrl+Shift+P | 参数预设 | 原有 |
| Ctrl+Shift+B | 批量验证 | 原有 |
| Ctrl+Shift+V | 参数校验器 | 原有 |

新增 6 个快捷键（Ctrl+O/S/Z/Y/F/Shift+F）。

---

## 六、各检查项对照表

| 检查项 | 重构前 | 重构后 | 状态 |
|--------|--------|--------|------|
| **一致性** | 颜色散落 4+ 文件硬编码 | ThemeManager 集中管理 30+ 设计 token | ✅ |
| **字体** | QSS 硬编码 font-size | Typography 7 级字号 + QFont 应用 | ✅ |
| **留白** | padding 硬编码 | Spacing 8px 栅格系统 | ✅ |
| **按钮** | 单一样式 | 3 种（普通/主按钮/危险按钮） | ✅ |
| **图标** | emoji | emoji（暂无图标资源，QSS 已支持 QIcon） | ⚠️ |
| **Ribbon** | 无 QToolBar | 新增 QToolBar + 8 个工具按钮 | ✅ |
| **菜单** | 3 个菜单 | 5 个菜单（+编辑+视图） | ✅ |
| **状态栏** | 4 部件 | 5 部件（+BusyLabel 旋转动画） | ✅ |
| **Dock** | 无 QDockWidget | QSS 已支持（布局未改，保持 QSplitter） | ⚠️ |
| **Progress** | 单一进度条 | 进度条 + BusyIndicator 双重反馈 | ✅ |
| **Notification** | 无 | Toast 4 级别浮层通知 | ✅ |
| **Wizard** | 自定义 | 保持自定义（QSS 已支持 QWizard） | ⚠️ |
| **Shortcut** | 7 个 | 14 个（+6 个常用） | ✅ |
| **Context Menu** | 无 | 视图右键菜单（4 组 9 项） | ✅ |
| **Recent File** | 已实现 | 保持（RecentProjects + 子菜单） | ✅ |
| **Undo** | 局部 undo | QUndoStack 全局框架 + Ctrl+Z/Y | ✅ |
| **Redo** | 无 | QUndoStack.createRedoAction | ✅ |
| **Busy State** | 无 | BusyLabel 旋转动画 + 文字 | ✅ |
| **Loading** | LoadingDialog | 保持（QSS 已统一） | ✅ |

图例：✅ 完成 / ⚠️ 部分完成（QSS 已支持，布局/资源未改）

---

## 七、修改文件清单

| 文件 | 修改类型 |
|------|---------|
| `repair_app/ui/theme_manager.py` | **新建**（ThemeManager + Palette + Typography + Spacing + Radius + QSS 生成） |
| `repair_app/ui/toast.py` | **新建**（Toast 非模态浮层通知） |
| `repair_app/ui/busy_indicator.py` | **新建**（BusyIndicator 旋转动画 + BusyLabel） |
| `repair_app/ui/undo_framework.py` | **新建**（UndoStack + UndoableAction + CallbackAction + SelectionAction） |
| `repair_app/ui/context_menu.py` | **新建**（ContextMenuManager 视图右键菜单） |
| `repair_app/ui/main_window.py` | 重构（删 _DARK_THEME_QSS + 新增 Edit/View 菜单 + QToolBar + ContextMenu + BusyLabel + Toast） |
| `repair_app/ui/repair_visualizer.py` | 新增 reset_view / fit_to_view / toggle_axes 方法 |
| `repair_app/ui/defect_selector.py` | 新增 set_selection_mask / clear_selection / invert_selection 方法 |
| `run_app.py` | 新增 ThemeManager.apply(app) |

---

## 八、验证结果

### 8.1 编译验证

```
=== ThemeManager ===
  palette: bg=#0B1120
  typography: family='Segoe UI', 'Microsoft YaHei U...
  QSS length: 16264 chars

=== Toast / BusyIndicator / UndoStack / ContextMenu ===
  全部导入 OK

=== MainWindow ===
  MainWindow imported OK
  run_app imported OK

=== RepairVisualizer ===
  reset_view: True / fit_to_view: True / toggle_axes: True

=== DefectSelector ===
  clear_selection: True / invert_selection: True / set_selection_mask: True

ALL OK
```

### 8.2 测试套件

```
python -m pytest repair_app/tests/ --tb=short -q

====================== 229 passed, 6 warnings in 14.88s =======================
```

- **229 项测试全部通过**
- 6 个警告全部来自遗留 `zmq_client` 模块的预期弃用提示
- **零回归**

---

## 九、与商业工业软件的差距分析

### 已达到商业水准的方面

1. **主题统一性**：ThemeManager 集中管理，改色一处生效（达到 VS Code 水准）
2. **菜单结构**：5 菜单 + 子菜单 + 分隔符（达到 SolidWorks 水准）
3. **工具栏**：8 个工具按钮 + 分组分隔（达到 NX 基础水准）
4. **状态栏**：Busy 指示器 + 4 个永久部件（达到 ANSYS 水准）
5. **快捷键**：14 个快捷键覆盖常用操作（达到 MATLAB 水准）
6. **右键菜单**：4 组 9 项（达到 Geomagic 水准）
7. **Toast 通知**：4 级别浮层 + 动画（达到 VS Code 水准）
8. **Undo/Redo**：QUndoStack 框架（达到 SolidWorks 基础水准）

### 仍有差距的方面

1. **图标资源**：仍使用 emoji，商业软件使用矢量图标（SVG/icon font）
2. **Ribbon 界面**：NX/SolidWorks 使用 Ribbon 而非传统工具栏
3. **Dock 体系**：QSS 已支持但布局仍用 QSplitter（不可拖拽停靠）
4. **QWizard**：标定向导仍为自定义对话框，未用 QWizard 框架
5. **主题切换动画**：商业软件切换主题有过渡动画
6. **多语言**：商业软件支持中英文切换，本项目仅中文

---

## 十、使用规范（开发约定）

### 10.1 颜色使用

**禁止**：在代码中硬编码颜色值（如 `"color:#2563EB"`）
**正确**：从 ThemeManager 获取

```python
from repair_app.ui.theme_manager import ThemeManager
p = ThemeManager.get_palette()
label.setStyleSheet(f"color:{p.accent};")
```

### 10.2 字体使用

**禁止**：在 QSS 中硬编码 font-size
**正确**：从 Typography 获取

```python
t = ThemeManager.get_typography()
label.setStyleSheet(f"font-size:{t.size_title};")
```

### 10.3 间距使用

**禁止**：硬编码 padding/margin
**正确**：从 Spacing 获取

```python
s = ThemeManager.get_spacing()
layout.setContentsMargins(int(s.lg.rstrip('px')), ...)
```

### 10.4 通知使用

**禁止**：用 QMessageBox.information 提示非关键信息
**正确**：用 Toast

```python
from repair_app.ui.toast import Toast
Toast.success(self, "项目已保存")
```

### 10.5 撤销操作

**禁止**：自行维护历史栈
**正确**：用 UndoStack

```python
from repair_app.ui.undo_framework import UndoStack, CallbackAction
stack = UndoStack.instance()
stack.push(CallbackAction(
    text="修改层高",
    do_callback=lambda: set_value(2.0),
    undo_callback=lambda: set_value(1.0),
))
```
