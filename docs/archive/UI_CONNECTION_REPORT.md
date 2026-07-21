# UI Connection Report — Backend 功能 GUI 接线报告

> 版本：1.0.0 RC ｜ 更新日期：2026-07-15 ｜ 文档语言：简体中文
>
> 本文档记录 6 个已完成但未接入 GUI 的 Backend 功能的接线工作。
> 原则：Backend 不修改，仅增加菜单/按钮/ToolBar/Wizard/Shortcut/Signal Slot。

---

## 接线总览

| 功能 | 以前是否可用 | 现在如何进入 | 快捷键 | Backend 文件 | UI 对话框 |
|------|-------------|-------------|--------|-------------|----------|
| Robot Export | ❌ 不可用 | 工具菜单 / 导出按钮 | Ctrl+R | robot_exporter.py | RobotExportDialog |
| Calibration | ❌ 不可用 | 工具菜单 | Ctrl+Shift+C | calibration_wizard.py | CalibrationDialog |
| Coordinate System | ❌ 不可用 | 工具菜单 | Ctrl+Shift+T | coordination_service.py | CoordinateSystemDialog |
| Parameter Preset | ❌ 不可用 | 工具菜单 | Ctrl+Shift+P | config.py PARAM_SPECS | ParameterPresetDialog |
| Batch Validation | ❌ 不可用 | 工具菜单 | Ctrl+Shift+B | validation_service.py | BatchValidationDialog |
| Parameter Validator | ❌ 不可用 | 工具菜单 | Ctrl+Shift+V | validation_service.py | ParameterValidatorDialog |

**测试结果：229 passed, 0 failed, 6 warnings（预期弃用警告）**

---

## 1. Robot Export（工业机器人轨迹导出）

### 以前状态
❌ **不可用**。Backend `RobotExporter` 类已完整实现 KUKA KRL / ABB Rapid 两种格式导出，但 GUI 中无任何入口，用户无法从界面触发。

### 现在如何进入
- **入口 1**：菜单栏 → 工具(&T) → 🤖 导出工业机器人轨迹...
- **入口 2**：步骤 04 输出交付区 → 🤖 导出机器人轨迹 按钮（与"导出 G-code"并列）
- **快捷键**：Ctrl+R

### 截图位置
```
screenshots/ui_connection/01_robot_export_menu.png      — 菜单入口
screenshots/ui_connection/02_robot_export_dialog.png    — 导出对话框
screenshots/ui_connection/03_robot_export_button.png    — 按钮入口
```

### 对应代码
- **Backend**：[robot_exporter.py](file:///d:/work/demo/industrial-vision/repair_app/export/robot_exporter.py) — `RobotExporter.export()`
- **UI 对话框**：[dialogs.py](file:///d:/work/demo/industrial-vision/repair_app/ui/dialogs.py) — `RobotExportDialog` 类（第 378 行）
- **菜单接线**：[main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) — `_setup_menubar()` 第 1146 行
- **按钮接线**：[main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) — `_build_output_panel()` 第 780 行
- **Slot 方法**：[main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) — `_on_export_robot()` 第 2813 行
- **按钮启用联动**：第 1431 行（航点生成后启用）、第 1747 行（重置时禁用）

### 功能说明
- 支持 KUKA KRL 和 ABB Rapid 两种机器人品牌
- 可配置 TCP 速度、工具坐标系、基坐标系、逼近精度
- 自动将法向量转换为 KUKA ABC 欧拉角或 ABB 四元数
- 航点坐标自动从 mm 转换为 m

---

## 2. Calibration（单道沉积标定向导）

### 以前状态
❌ **不可用**。Backend `CalibrationWizard` 类已完整实现标定流程（参数设置→测量录入→修正系数计算→持久化），但 GUI 中无任何入口。

### 现在如何进入
- **入口**：菜单栏 → 工具(&T) → 🎯 单道沉积标定向导...
- **快捷键**：Ctrl+Shift+C

### 截图位置
```
screenshots/ui_connection/04_calibration_menu.png       — 菜单入口
screenshots/ui_connection/05_calibration_dialog.png     — 标定向导对话框
```

### 对应代码
- **Backend**：[calibration_wizard.py](file:///d:/work/demo/industrial-vision/repair_app/utils/calibration_wizard.py) — `CalibrationWizard` 类
- **UI 对话框**：[dialogs.py](file:///d:/work/demo/industrial-vision/repair_app/ui/dialogs.py) — `CalibrationDialog` 类（第 543 行）
- **菜单接线**：[main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) — `_setup_menubar()` 第 1153 行
- **Slot 方法**：[main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) — `_on_calibration()` 第 2820 行

### 功能说明
- 步骤 1：设置标定参数（喷嘴直径、喷涂距离、角度、速度、粒径、预热温度）
- 步骤 2：录入实测沉积宽度、高度、效率
- 自动计算宽度/高度/效率修正系数
- 保存到 `config/calibration_db.json`，后续形貌预测可读取修正

---

## 3. Coordinate System（坐标系变换）

### 以前状态
❌ **不可用**。Backend `CoordinationService` 已提供点云处理能力，但坐标系变换功能未接入 GUI，用户无法在软件内完成测量坐标系到加工坐标系的转换。

### 现在如何进入
- **入口**：菜单栏 → 工具(&T) → 📐 坐标系变换...
- **快捷键**：Ctrl+Shift+T

### 截图位置
```
screenshots/ui_connection/06_coord_menu.png             — 菜单入口
screenshots/ui_connection/07_coord_dialog.png           — 变换对话框
```

### 对应代码
- **Backend**：[coordination_service.py](file:///d:/work/demo/industrial-vision/repair_app/service/coordination_service.py) — `CoordinationService` 类
- **UI 对话框**：[dialogs.py](file:///d:/work/demo/industrial-vision/repair_app/ui/dialogs.py) — `CoordinateSystemDialog` 类（第 669 行）
- **菜单接线**：[main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) — `_setup_menubar()` 第 1158 行
- **Slot 方法**：[main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) — `_on_coord_transform()` 第 2826 行

### 功能说明
- 支持三轴平移（X/Y/Z，单位 mm）
- 支持三轴旋转（绕 X/Y/Z 轴，单位 °）
- 支持三轴缩放（X/Y/Z 独立缩放因子）
- 变换顺序：缩放 → 旋转 → 平移
- 变换结果自动应用到当前点云并刷新 3D 视图

---

## 4. Parameter Preset（参数预设管理）

### 以前状态
❌ **不可用**。Backend `PARAM_SPECS` / `PARAM_DEFAULTS` 已定义参数规范，但用户无法保存/加载自定义参数组合，每次使用都需要手动重新设置全部参数。

### 现在如何进入
- **入口**：菜单栏 → 工具(&T) → ⚙️ 参数预设管理...
- **快捷键**：Ctrl+Shift+P

### 截图位置
```
screenshots/ui_connection/08_preset_menu.png            — 菜单入口
screenshots/ui_connection/09_preset_dialog.png          — 预设管理对话框
```

### 对应代码
- **Backend**：[config.py](file:///d:/work/demo/industrial-vision/repair_app/utils/config.py) — `PARAM_SPECS` / `PARAM_DEFAULTS`
- **UI 对话框**：[dialogs.py](file:///d:/work/demo/industrial-vision/repair_app/ui/dialogs.py) — `ParameterPresetDialog` 类（第 824 行）
- **菜单接线**：[main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) — `_setup_menubar()` 第 1165 行
- **Slot 方法**：[main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) — `_on_param_preset()` 第 2843 行
- **参数应用**：[main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) — `_apply_preset_params()` 第 2850 行

### 功能说明
- 保存当前 UI 所有参数为 JSON 预设文件（`user_data/param_presets/`）
- 加载已有预设并自动应用到 UI spinbox
- 删除不需要的预设
- 双击列表项快速加载
- 适合不同材料/工艺的常用配置快速切换

---

## 5. Batch Validation（批量验证）

### 以前状态
❌ **不可用**。Backend `ValidationService.validate_params()` 已实现参数校验，但只能单次调用，用户无法批量对比多组参数组合的可行性。

### 现在如何进入
- **入口**：菜单栏 → 工具(&T) → 🔬 批量验证...
- **快捷键**：Ctrl+Shift+B

### 截图位置
```
screenshots/ui_connection/10_batch_menu.png             — 菜单入口
screenshots/ui_connection/11_batch_dialog.png           — 批量验证对话框
```

### 对应代码
- **Backend**：[validation_service.py](file:///d:/work/demo/industrial-vision/repair_app/service/validation_service.py) — `ValidationService.validate_params()`
- **UI 对话框**：[dialogs.py](file:///d:/work/demo/industrial-vision/repair_app/ui/dialogs.py) — `BatchValidationDialog` 类（第 987 行）
- **菜单接线**：[main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) — `_setup_menubar()` 第 1170 行
- **Slot 方法**：[main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) — `_on_batch_validation()` 第 2891 行

### 功能说明
- 支持 JSON 格式输入（单个 dict 或 list）
- 支持 key=value 逗号分隔格式（每行一组）
- 自动预填当前 UI 参数作为基础
- 批量执行 `ValidationService.validate_params()`
- 输出对比报告：每组参数的通过/失败状态 + 错误详情
- 统计通过率

---

## 6. Parameter Validator（参数校验器）

### 以前状态
❌ **不可用**。Backend `PARAM_BOUNDS` 和 `ValidationService` 已定义参数范围，但用户无法直观查看当前参数是否在合法范围内，只能在计算失败后才知道参数有误。

### 现在如何进入
- **入口**：菜单栏 → 工具(&T) → ✓ 参数校验器...
- **快捷键**：Ctrl+Shift+V

### 截图位置
```
screenshots/ui_connection/12_validator_menu.png         — 菜单入口
screenshots/ui_connection/13_validator_dialog.png       — 校验器对话框
```

### 对应代码
- **Backend**：[config.py](file:///d:/work/demo/industrial-vision/repair_app/utils/config.py) — `PARAM_BOUNDS` / `PARAM_SPECS`
- **Backend**：[validation_service.py](file:///d:/work/demo/industrial-vision/repair_app/service/validation_service.py) — `ValidationService`
- **UI 对话框**：[dialogs.py](file:///d:/work/demo/industrial-vision/repair_app/ui/dialogs.py) — `ParameterValidatorDialog` 类（第 1131 行）
- **菜单接线**：[main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) — `_setup_menubar()` 第 1175 行
- **Slot 方法**：[main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) — `_on_param_validator()` 第 2898 行

### 功能说明
- 打开时自动校验当前 UI 参数（无需手动点击）
- 逐项列出所有 PARAM_SPECS 参数的：参数名、当前值、合法范围、状态（✓/✗）
- 自动映射 UI short key 到 spec_key（layer_height → layer_height_mm 等）
- 底部显示总结："所有参数在合法范围内" 或 "存在参数超出范围，请修正"
- 支持"立即校验"按钮重新校验（修改参数后刷新）

---

## 修改文件清单

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| [dialogs.py](file:///d:/work/demo/industrial-vision/repair_app/ui/dialogs.py) | 修改 | 新增 6 个对话框类（RobotExportDialog / CalibrationDialog / CoordinateSystemDialog / ParameterPresetDialog / BatchValidationDialog / ParameterValidatorDialog） |
| [main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) | 修改 | 新增"工具"菜单 + 6 个 Slot 方法 + Robot 导出按钮 + 按钮启用联动 |

### 未修改的 Backend 文件（按要求不动）
- robot_exporter.py
- calibration_wizard.py
- coordination_service.py
- validation_service.py
- config.py
- export_service.py

---

## 接线方式说明

### 菜单栏
新增"工具(&T)"菜单，包含 6 个功能入口，每个入口配有：
- 图标 emoji（🤖🎯📐⚙️🔬✓）
- Tooltip 说明
- 键盘快捷键

### 按钮
Robot Export 额外在步骤 04 输出交付区添加了按钮（与"导出 G-code"并列），因为导出功能天然属于输出阶段。按钮启用状态与 G-code 按钮联动（有航点时启用）。

### Signal Slot 连接
每个菜单/按钮的 `triggered` / `clicked` 信号连接到对应的 `_on_xxx()` Slot 方法，方法内实例化对话框并 `exec()`。

### Wizard
Calibration 对话框采用向导式布局（步骤 1 → 步骤 2 → 保存），引导用户完成标定流程。

### Shortcut 快捷键
| 功能 | 快捷键 |
|------|--------|
| Robot Export | Ctrl+R |
| Calibration | Ctrl+Shift+C |
| Coordinate System | Ctrl+Shift+T |
| Parameter Preset | Ctrl+Shift+P |
| Batch Validation | Ctrl+Shift+B |
| Parameter Validator | Ctrl+Shift+V |

---

## 验证结果

### 编译检查
```
Compile OK
```

### 测试结果
```
229 passed, 6 warnings in 14.77s
```
- 229 个测试全部通过
- 6 个 warnings 均为预期的 LegacyZmqClient 弃用警告
- 0 个失败、0 个错误

### 截图采集说明
截图应保存到 `screenshots/ui_connection/` 目录，文件名按上述报告中的编号命名。建议在以下场景截图：
1. 启动软件后，展开"工具"菜单，截取菜单全貌
2. 逐一点击每个功能，截取对话框截图
3. Robot Export 按钮截图在步骤 04 输出交付区

---

## 结论

6 个 Backend 已完成功能全部接入 GUI：

| 功能 | 接入方式 | 用户可操作 |
|------|----------|-----------|
| Robot Export | 菜单 + 按钮 + 快捷键 | ✅ |
| Calibration | 菜单 + 快捷键 | ✅ |
| Coordinate System | 菜单 + 快捷键 | ✅ |
| Parameter Preset | 菜单 + 快捷键 | ✅ |
| Batch Validation | 菜单 + 快捷键 | ✅ |
| Parameter Validator | 菜单 + 快捷键 | ✅ |

所有功能通过"工具"菜单统一入口，符合工业软件的菜单分类惯例。Robot Export 额外提供输出区按钮入口，符合用户的操作直觉。Backend 代码零修改，仅通过 UI 层的 Signal-Slot 连接实现接线。
