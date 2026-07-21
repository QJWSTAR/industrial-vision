# Release Blocker 修复报告

> **日期**：2026-07-15
> **阶段**：Release Candidate (RC)
> **范围**：PROJECT_HEALTH_REPORT.md + PRODUCT_REVIEW.md 中的全部 Must Fix

---

## 一、修复列表

### 第一部分：4 大类 Release Blocker（13 项，此前已修复，本次验证全部 PASS）

#### ① Runtime Crash（2/2 PASS）

| # | 问题 | 文件 | 状态 |
|---|------|------|------|
| RC-1 | stl_reader.py import 顺序 | [stl_reader.py:7](file:///d:/work/demo/industrial-vision/repair_app/core/stl_reader.py#L7) | ✅ `import os` 在顶部 |
| RC-2 | reset_singleton 重复定义 | [matlab_engine_proxy.py:227](file:///d:/work/demo/industrial-vision/repair_app/bridge/adapters/matlab_engine_proxy.py#L227) | ✅ 仅 1 个带锁版本 |

#### ② Safety（4/4 PASS）

| # | 问题 | 文件 | 状态 |
|---|------|------|------|
| RC-3 | G-code 增量坐标模式 | [gcode_exporter.py:75-137](file:///d:/work/demo/industrial-vision/repair_app/export/gcode_exporter.py#L75) | ✅ 输出差值 dx/dy/dz |
| RC-4 | License HMAC 空密钥拒绝 | [license_manager.py:219-221](file:///d:/work/demo/industrial-vision/repair_app/utils/license_manager.py#L219) | ✅ frozen+空密钥返回 False |
| RC-5 | License 5 入口校验 | [main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) | ✅ 5/5 入口全覆盖 |
| RC-6 | public_key.pem 打包 | [repair_app.spec:41](file:///d:/work/demo/industrial-vision/repair_app.spec#L41) | ✅ datas 含 public_key.pem |

#### ③ Packaging（4/4 PASS）

| # | 问题 | 文件 | 状态 |
|---|------|------|------|
| RC-7 | Windows icon | p1.ico + [spec:22-32](file:///d:/work/demo/industrial-vision/repair_app.spec#L22) | ✅ .ico 优先搜索 |
| RC-8 | console=False | [spec:183](file:///d:/work/demo/industrial-vision/repair_app.spec#L183) | ✅ 硬编码 False |
| RC-9 | 启动 bat | [启动软件.bat](file:///d:/work/demo/industrial-vision/启动软件.bat) | ✅ 支持 EXE + 开发模式 |
| RC-10 | spec hiddenimports | [spec:121-130](file:///d:/work/demo/industrial-vision/repair_app.spec#L121) | ✅ loguru + bridge 子模块 |

#### ④ Thread Safety（3/3 PASS）

| # | 问题 | 文件 | 状态 |
|---|------|------|------|
| RC-11 | zmq_client 加锁 | [zmq_client.py:172,177,289,304,309](file:///d:/work/demo/industrial-vision/repair_app/bridge/communication/zmq_client.py#L172) | ✅ threading.Lock 保护 |
| RC-12 | terminate→quit+wait | [main_window.py closeEvent](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py#L2832) + [workers.py:182](file:///d:/work/demo/industrial-vision/repair_app/ui/workers.py#L182) | ✅ quit+wait(5000) + Poller |
| RC-13 | progress_subscriber 生命周期 | [progress_subscriber.py:145-146](file:///d:/work/demo/industrial-vision/repair_app/ui/progress_subscriber.py#L145) | ✅ finished→deleteLater |

---

### 第二部分：PRODUCT_REVIEW Must Fix（8/8 本次修复）

| # | 问题 | 修复方案 | 文件 | 行号 |
|---|------|----------|------|------|
| MF-1 | 导航/选取模式陷阱 | 加载点云后自动调用 `_on_nav_toggled(False)` 切换到选取模式 | [defect_selector.py:318-321](file:///d:/work/demo/industrial-vision/repair_app/ui/defect_selector.py#L318) | |
| MF-2 | MATLAB 启动无反馈 | 添加进度条(2%)、状态栏预估时间提示、`processEvents()` 强制刷新 UI、友好的错误对话框（含解决方法） | [main_window.py:1910-1944](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py#L1910) | |
| MF-3 | License 失败仍显示完整界面 | License 无效时在标题栏下方显示红色警告横幅，提示功能已禁用 | [main_window.py:490-498,521-523](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py#L490) | |
| MF-4 | 错误消息透传原始异常 | 新增 `_friendly_error()` 辅助函数，按错误类型（超时/连接/文件/License/内存）翻译为用户可读消息；11 处 `str(e)` 全部替换 | [main_window.py:68-82](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py#L68) | |
| MF-5 | G-code 无追溯信息 | G-code 头部增加软件版本和生成时间戳 | [gcode_exporter.py:152-167](file:///d:/work/demo/industrial-vision/repair_app/export/gcode_exporter.py#L152) | |
| MF-6 | FAQ Q39 与 License 矛盾 | 修正 Q39 表述：说明 License 可能含到期时间，引导用户查看 About 对话框 | [常见问题.md:249](file:///d:/work/demo/industrial-vision/docs/FAQ/常见问题.md#L249) | |
| MF-7 | 参数 spinbox 无 tooltip | 为 19 个参数 spinbox（路径规划 9 + 冷喷涂 10）全部设置中文 tooltip，含典型值建议 | [main_window.py:696-712,833-850](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py#L696) | |
| MF-8 | 参数范围双源冲突 | UI 冷喷涂参数范围统一为 config.py PARAM_SPECS 权威值（粒子速度上限 1200→2000、临界速度 1000→2000、粉末粒径下限 5→1、气体温度下限 200→20、气体压力下限 10→1、送粉速度下限 5→1、移动速度下限 50→10） | [main_window.py:821-831](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py#L821) | |

---

## 二、修改文件清单

| 文件 | 修改内容 | 涉及修复项 |
|------|----------|-----------|
| `repair_app/ui/main_window.py` | License 横幅、MATLAB 进度反馈、错误友好化、参数 tooltip、参数范围统一 | MF-2, MF-3, MF-4, MF-7, MF-8 |
| `repair_app/ui/defect_selector.py` | 自动切换选取模式 | MF-1 |
| `repair_app/export/gcode_exporter.py` | G-code 头部追溯信息 | MF-5 |
| `docs/FAQ/常见问题.md` | Q39 表述修正 | MF-6 |

---

## 三、风险评估

| 风险项 | 等级 | 说明 | 缓解措施 |
|--------|------|------|----------|
| MF-1: `_on_nav_toggled` 调用时机 | 低 | `set_points` 在 `defect_selector.py` 中调用，此时 UI 已初始化 | 验证确认方法存在（第 216 行），且 `_btn_nav` 已在 `__init__` 中创建 |
| MF-4: `_friendly_error` 匹配精度 | 低 | 关键词匹配可能误判（如错误消息中恰好含 "file"） | 兜底分支保留原始错误消息 + "联系管理员"指引 |
| MF-7: tooltip 文本过长 | 低 | 部分 tooltip 含典型值建议，可能超出气泡显示区域 | Qt 自动换行，且用户可悬停查看完整内容 |
| MF-8: 参数范围放宽 | 中 | 上限放宽后用户可能输入极端值导致算法异常 | 后端 `PARAM_BOUNDS` + `ValidationService` 仍为权威校验源 |
| 无新增功能 | — | 所有修复均为 Bug Fix / UX 改善 / 文档修正 | 未修改架构、未增加功能、未优化代码风格 |

---

## 四、回归测试

### 测试结果

| 测试套件 | 通过 | 失败 | 错误 | 说明 |
|----------|------|------|------|------|
| `repair_app/tests/` | 229 | 0 | 0 | ✅ 全部通过 |
| `repair_app/bridge/tests/` (排除集成) | 39 | 0 | 0 | ✅ 全部通过（CSAM_ALGORITHM_ENGINE=python） |

```
repair_app/tests/:         229 passed, 0 failed
repair_app/bridge/tests/:   39 passed, 0 failed (CSAM_ALGORITHM_ENGINE=python)
总计:                       268 passed, 0 failed
```

### 编译检查

```
python -m py_compile main_window.py gcode_exporter.py defect_selector.py
→ COMPILE_OK
```

### 环境说明

- Python 3.12.9
- PySide6 6.11.1, matplotlib 3.11.0, reportlab 5.0.0
- Bridge 集成测试需 MATLAB（当前环境不可用），以 `CSAM_ALGORITHM_ENGINE=python` 降级验证
- `test_no_license_file` 需确保 `config/license.key` 不存在（验证前已清理）

---

## 五、是否还有 Release Blocker

### 结论：无 Release Blocker

### 逐项确认

| 类别 | 项数 | 状态 |
|------|------|------|
| ① Runtime Crash | 2 | ✅ 全部 PASS |
| ② Safety | 4 | ✅ 全部 PASS |
| ③ Packaging | 4 | ✅ 全部 PASS |
| ④ Thread Safety | 3 | ✅ 全部 PASS |
| Must Fix (MF-1~8) | 8 | ✅ 全部修复 |
| **合计** | **21** | **✅ 0 阻塞** |

### 发布前仍需人工验证

以下为非代码验证（需图形界面或 MATLAB 环境）：

1. **EXE 打包**：`python -m PyInstaller --clean repair_app.spec` → 确认 `dist/CSAM_Repair.exe` 生成
2. **EXE 启动**：双击 EXE → 确认主窗口显示、License 横幅（无 license 时）、参数 tooltip 显示
3. **MATLAB 端到端**：启动 MATLAB Bridge → 加载点云 → 选区（确认自动切换选取模式）→ 一键计算 → 确认进度条和状态栏反馈
4. **G-code 导出**：导出后打开文件 → 确认头部含软件版本和时间戳
5. **错误提示**：触发 MATLAB 不可用错误 → 确认弹窗含"解决方法"指引

---

## 六、总结

本次 RC 阶段共验证和修复 **21 个 Release Blocker**：

- **13 项**（4 大类）此前已修复，本次验证全部 PASS
- **8 项**（PRODUCT_REVIEW Must Fix）本次修复，编译通过，268 个测试全部通过

**未修改架构、未增加功能、未优化代码风格**——仅修复阻塞发布的缺陷。

项目已达到 v1.0 Release Candidate 标准，可进入发布流程。

---

*报告生成日期：2026-07-15*
*验证方法：13 项自动验证 + 8 项代码修复 + 268 个回归测试*
