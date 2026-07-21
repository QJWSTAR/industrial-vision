# UX Review Must Fix — 修复报告

> 版本：1.0.0 RC ｜ 更新日期：2026-07-15 ｜ 文档语言：简体中文
>
> 本文档记录 Product Review 中 8 项 Must Fix（MF-1 ~ MF-8）的增强版修复详情。
> 前置文档：PRODUCT_REVIEW.md（5 角色产品体验审查）、Release_Blocker_Fix_Report.md（RC 阶段修复）

---

## 修复总览

| 编号 | 问题 | 修复状态 | 涉及文件 |
|------|------|----------|----------|
| MF-1 | 导航模式陷阱 | ✅ 完成 | defect_selector.py |
| MF-2 | MATLAB Loading 无反馈 | ✅ 完成 | dialogs.py, main_window.py |
| MF-3 | License Flow 不拦截 | ✅ 完成 | run_app.py, main_window.py |
| MF-4 | 错误提示不统一 | ✅ 完成 | dialogs.py, main_window.py |
| MF-5 | G-code 无追溯信息 | ✅ 完成 | gcode_exporter.py, export_service.py, main_window.py |
| MF-6 | 文档冲突 | ✅ 完成 | docs/FAQ/常见问题.md |
| MF-7 | Tooltip 缺失 | ✅ 完成 | main_window.py, defect_selector.py |
| MF-8 | 参数范围双源冲突 | ✅ 完成 | config.py, main_window.py |

**测试结果：229 passed, 0 failed, 6 warnings（预期弃用警告）**

---

## MF-1：导航模式陷阱

### 问题
用户加载点云后默认处于导航模式，点击 3D 视图无反应。用户不知道当前处于什么模式，也不知道如何切换到选取模式。鼠标光标在两种模式下没有视觉区分。

### 修复内容

**1. 当前模式提示横幅**
在工具栏下方添加醒目的模式横幅标签 `_lb_mode_banner`，实时显示当前模式：
- 导航模式：蓝色横幅 "🧭 当前：导航模式 — 可用鼠标旋转/缩放 3D 视图，无法框选缺陷"
- 选取模式：橙色横幅 "✂️ 当前：选取模式（矩形框选）— 在 3D 视图中按住鼠标拖动以选择缺陷区域"

**2. Hover Cursor 鼠标光标**
- 导航模式：`Qt.OpenHandCursor`（手掌光标）
- 选取模式：`Qt.CrossCursor`（十字光标）

**3. Status Bar 信息增强**
`_update_info` 方法输出格式改为 `[模式标签] 选中: X / Y 点`，在状态信息中包含当前模式。

**4. 子模式联动修复**
修复 `_cb_mode` 下拉框未连接信号导致子模式切换无效的 bug，新增 `_on_submode_changed` 方法，切换时更新 `self._mode` 并刷新横幅。

### 涉及文件
- [defect_selector.py](file:///d:/work/demo/industrial-vision/repair_app/ui/defect_selector.py)

---

## MF-2：MATLAB Loading 无反馈

### 问题
用户点击"开始计算"后，MATLAB 启动需要 60-120 秒，期间只有进度条文字变化，没有可取消的对话框，没有超时机制，用户不知道是否在正常工作。

### 修复内容

**1. LoadingDialog 组件**（新建 `repair_app/ui/dialogs.py`）
模态进度对话框，包含：
- 标题 + 状态文字（滚动动画显示工作进行中）
- 不确定进度条（滚动动画）
- 倒计时显示（默认 180 秒）
- Cancel 取消按钮

**2. 后台线程执行**
新增 `_EnsureReadyWorker`（QThread 子类），将 `manager.ensure_ready()` 放到后台线程执行，避免阻塞 UI。

**3. Cancel 取消功能**
用户点击取消后，对话框关闭，返回失败状态，主流程中止计算并提示"MATLAB 启动已取消"。

**4. Timeout 超时机制**
默认 180 秒超时，超时后自动关闭对话框并返回失败，触发 ErrorDialog 提示用户。

### 涉及文件
- [dialogs.py](file:///d:/work/demo/industrial-vision/repair_app/ui/dialogs.py)（新建）
- [main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py)（`_on_start_calculation` 方法）

---

## MF-3：License Flow 不拦截

### 问题
License 验证失败后仍进入完整 GUI，仅显示红色警告横幅。用户可以浏览界面但无法操作，体验极差。

### 修复内容

**1. License 验证前置到 run_app.py**
在 `QApplication` 创建后、`MainWindow` 创建前，执行 License 验证：
```python
license_mgr = LicenseManager()
if not license_mgr.load_license():
    QMessageBox.critical(None, "License 无效 — 无法启动软件", ...)
    sys.exit(1)
```

**2. License 失败拒绝启动**
License 无效时弹出 Critical 对话框，显示错误详情和解决步骤，然后 `sys.exit(1)` 退出，不创建 MainWindow。

**3. 移除 MainWindow 中的横幅代码**
License 已在启动前验证通过，MainWindow 中的红色警告横幅代码已移除（不再需要）。MainWindow 仅保留状态栏 License 状态指示。

### 涉及文件
- [run_app.py](file:///d:/work/demo/industrial-vision/run_app.py)
- [main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py)（`__init__` 和 `_setup_ui` 方法）

---

## MF-4：统一 Error Dialog

### 问题
错误提示使用 `QMessageBox.warning` 直接显示 `_friendly_error()` 翻译后的文字，用户看到的是一整段技术性错误信息，没有区分"发生了什么/为什么/如何解决"，也没有展开技术日志的选项。

### 修复内容

**1. ErrorDialog 组件**（新建 `repair_app/ui/dialogs.py`）
统一错误对话框，三段式信息架构：
- **发生了什么**（What）— 红色边框，描述错误本身
- **为什么**（Why）— 黄色边框，解释错误原因
- **如何解决**（How）— 绿色边框，给出解决步骤

**2. 技术日志展开**
底部可折叠的"技术日志"区域，默认隐藏，技术员可点击展开查看完整 traceback。

**3. classify_error 分类器**
根据异常消息内容自动分类（超时/连接/文件/License/内存/其他），生成对应的三段式消息。

**4. _show_error 便捷函数**
封装 `classify_error + ErrorDialog.show`，一行调用替换原有 12 处 `QMessageBox.warning + _friendly_error`：
```python
_show_error(self, "导出失败", e)
```

### 替换的 12 个调用点
缓存失败、加载失败、请求构建失败（×2）、计算失败、路径规划失败、远程服务路径规划失败、导出失败（×2）、保存失败、打开失败，以及 MATLAB 启动失败/异常（MF-2 中替换）。

### 涉及文件
- [dialogs.py](file:///d:/work/demo/industrial-vision/repair_app/ui/dialogs.py)（新建）
- [main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py)（12 处错误处理点）

---

## MF-5：G-code Metadata 完整追溯

### 问题
G-code 文件头部仅有软件版本和生成时间，缺少模型版本、参数、材料、Git Commit、License ID 等追溯信息，无法满足工业生产追溯要求。

### 修复内容

**1. 完整 7 项追溯元数据**
G-code 文件头部现在包含：
```
(===== 追溯信息 =====)
(软件版本: 1.0.0)
(模型版本: demo_pointcloud.xyz)
(生成时间: 2026-07-15 16:30:00)
(材料: 316L 不锈钢)
(Git Commit: a1b2c3d)
(License ID: ABCDEF123456)
(参数: layer_height_mm=2.0, scanning_angle_deg=-45.0, ...)
(====================)
```

**2. set_metadata 方法**
GCodeExporter 新增 `set_metadata()` 方法，接受 model_version、material、parameters、license_id。

**3. Git Commit 自动捕获**
新增 `_get_git_commit()` 函数，通过 `git rev-parse --short HEAD` 获取当前 commit hash（失败返回 "unknown"）。

**4. 调用端传入完整数据**
`_on_export_gcode` 方法从 UI 收集材料、参数、点云文件名、License 机器码，构建 metadata dict 传入 ExportService。

### 涉及文件
- [gcode_exporter.py](file:///d:/work/demo/industrial-vision/repair_app/export/gcode_exporter.py)
- [export_service.py](file:///d:/work/demo/industrial-vision/repair_app/service/export_service.py)
- [main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py)（`_on_export_gcode` 方法）

---

## MF-6：修正文档冲突

### 问题
FAQ 文档中多处描述与软件实际行为冲突，特别是关于本地引擎、降级策略、手动启动 MATLAB 等内容。

### 修正的冲突条目

| Q编号 | 冲突内容 | 修正后 |
|-------|----------|--------|
| Q8 | 要求用户在 MATLAB 中手动执行 `matlab_bridge_server` | Bridge 由软件自动启动，用户无需手动操作 |
| Q17 | 称"只用本地引擎不需要 MATLAB" | 生产环境必须使用 MATLAB |
| Q18 | 建议"不能升级用本地引擎" | 版本不满足返回错误，联系管理员升级 |
| Q19 | 要求用户手动打开 MATLAB 检查 | MATLAB 服务由软件自动拉起 |
| Q22 | 称"日常用本地引擎就够了" | 生产统一用 MATLAB |
| Q23 | 描述自动降级到 Python 原型 | MATLAB 不可用返回错误，不自动降级 |
| Q24 | 称"MATLAB 坏了能用本地的" | MATLAB 不可用返回错误 |
| Q25 | 建议"经常断改用本地引擎" | 排查 MATLAB 服务问题 |
| Q28 | 要求在 MATLAB 中 Ctrl+C 重启 | 重启软件自动拉起 Bridge |
| Q30 | 要求手动重启 `matlab_bridge_server` | 重启 GUI 自动拉起 Bridge |
| Q41 | 建议"工具箱失效切本地引擎" | 联系 IT 续期后重启软件 |
| 术语表-降级策略 | 描述 auto 模式自动降级 | MATLAB 不可用返回错误 |

### 涉及文件
- [常见问题.md](file:///d:/work/demo/industrial-vision/docs/FAQ/常见问题.md)

---

## MF-7：补全所有 Tooltip

### 问题
部分 UI 控件缺少 Tooltip，用户不知道每个参数的含义和典型值范围。

### 补全的 Tooltip

| 控件 | Tooltip |
|------|---------|
| 材料选择下拉框 | 选择喷涂材料。不同材料有不同的临界速度和密度 |
| 计算引擎下拉框 | 选择计算引擎。本地引擎用于快速预览；远程服务连接 MATLAB |
| 深度补偿 SpinBox | 深度补偿系数。对预测的沉积深度进行缩放。典型值 0.8-1.2 |
| 预测层数 SpinBox | 形貌预测的层数。层数越多预测越精细但计算时间越长 |
| 规划层数 SpinBox | 喷涂层数。层数越多修复越厚，但计算时间越长 |
| 路径规划 9 个参数 | 每层高度、扫描角度、扫描步长、边缘步长、倾斜角度、增材缓冲、修复缓冲、路径过渡距离、避障精度 |
| 冷喷涂 10 个参数 | 粒子速度、临界速度、喷嘴直径、喷涂角度、喷涂距离、粉末粒径、气体温度、气体压力、送粉速度、移动速度 |

### 涉及文件
- [main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py)
- [config.py](file:///d:/work/demo/industrial-vision/repair_app/utils/config.py)（UI_PARAM_SPECS 中内嵌 tooltip）
- [defect_selector.py](file:///d:/work/demo/industrial-vision/repair_app/ui/defect_selector.py)

---

## MF-8：建立唯一 Parameter Schema

### 问题
`config.py` 的 `PARAM_SPECS`（21 项参数权威源）与 `main_window.py` 中硬编码的 `pp_params`（9 项）和 `cs_params`（10 项）存在大面积范围冲突。例如：
- `particle_velocity`：UI 上限 2000 vs PARAM_SPECS 2000（已统一），但 `gas_pressure` 下限 UI 为 1 vs PARAM_SPECS 为 1
- `layer_height`：UI 范围 0.1-10.0 vs PARAM_SPECS 0.1-20.0
- `scanning_angle`：UI 范围 -90 到 90 vs PARAM_SPECS -360 到 360

### 修复内容

**1. UI_PARAM_SPECS 映射表**（config.py）
新建 `UI_PARAM_SPECS` 列表，作为 PARAM_SPECS → UI spinbox 的唯一桥梁：
```python
UI_PARAM_SPECS = [
    ("layer_height_mm", "layer_height", "层高", " mm", "tooltip...", "pp", False),
    ("scanning_angle_deg", "scanning_angle", "扫描角度", " °", "tooltip...", "pp", False),
    ...
]
```
每个条目包含：spec_key（对应 PARAM_SPECS）、ui_short_key、中文标签、单位后缀、tooltip、分组（pp/cs）、是否只读。

**2. get_ui_param 函数**（config.py）
```python
def get_ui_param(spec_key) -> tuple:
    """返回 (lo, hi, default, step, label, suffix, tooltip, read_only)"""
```
范围/默认值/步长全部从 PARAM_SPECS 读取，UI 不再有硬编码范围。

**3. UI 动态生成**（main_window.py）
路径规划参数和冷喷涂参数的 spinbox 改为从 `UI_PARAM_SPECS` 动态生成：
```python
for spec_key, ui_key, label, suffix, tooltip, _grp, read_only in UI_PARAM_SPECS:
    if _grp != "pp": continue
    lo, hi, default, step = get_ui_param(spec_key)[:4]
    sp = QDoubleSpinBox()
    sp.setRange(lo, hi)  # ← 范围来自 PARAM_SPECS
    sp.setValue(default) # ← 默认值来自 PARAM_SPECS
    sp.setSingleStep(step) # ← 步长来自 PARAM_SPECS
```

**4. 消除双源冲突**
main_window.py 中的 `pp_params`、`cs_params`、`pp_tooltips`、`cs_tooltips` 四个硬编码列表全部删除，统一由 `UI_PARAM_SPECS` + `PARAM_SPECS` 提供。

### 涉及文件
- [config.py](file:///d:/work/demo/industrial-vision/repair_app/utils/config.py)（新增 UI_PARAM_SPECS + get_ui_param）
- [main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py)（`_build_path_planning_panel` 和 `_build_morphology_panel` 方法）

---

## 验证结果

### 编译检查
```
All files compile OK
```
（dialogs.py, defect_selector.py, gcode_exporter.py, export_service.py, config.py, main_window.py, run_app.py）

### 测试结果
```
229 passed, 6 warnings in 18.15s
```
- 229 个测试全部通过
- 6 个 warnings 均为预期的 LegacyZmqClient 弃用警告
- 0 个失败、0 个错误

### 修复文件清单

| 文件 | 修改类型 | MF 编号 |
|------|----------|---------|
| repair_app/ui/dialogs.py | 新建 | MF-2, MF-4 |
| repair_app/ui/defect_selector.py | 修改 | MF-1 |
| repair_app/export/gcode_exporter.py | 修改 | MF-5 |
| repair_app/service/export_service.py | 修改 | MF-5 |
| repair_app/utils/config.py | 修改 | MF-7, MF-8 |
| repair_app/ui/main_window.py | 修改 | MF-2, MF-3, MF-4, MF-5, MF-7, MF-8 |
| run_app.py | 修改 | MF-3 |
| docs/FAQ/常见问题.md | 修改 | MF-6 |

---

## 结论

8 项 Must Fix 全部完成。产品体验从 RC 阶段的"可用"提升到"可交付"水平：

- **MF-1**：用户不再困在导航模式，模式状态一目了然
- **MF-2**：MATLAB 启动有进度对话框，可取消，有超时
- **MF-3**：License 失败直接拒绝启动，不再进入半锁定状态
- **MF-4**：所有错误统一三段式提示，技术日志可展开
- **MF-5**：G-code 文件含完整 7 项追溯信息，满足工业追溯要求
- **MF-6**：FAQ 文档与软件实际行为一致
- **MF-7**：所有 UI 控件有 Tooltip，用户知道每个参数含义
- **MF-8**：参数范围单一权威源，消除双源冲突
