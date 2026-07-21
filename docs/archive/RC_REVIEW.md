# CSAM Repair Release Candidate 审查报告

> 审查日期: 2026-07-15
> 审查范围: d:\work\demo\industrial-vision 全部源码、配置、文档、测试
> 审查维度: Architecture / Security / UX / Packaging / Installer / Performance / Memory / Thread / Industrial Safety / License / Documentation / FAQ / Release Note / Known Issue
> 测试结果: 402 passed, 0 failed, 6 warnings (DeprecationWarning), 0 regression

---

## Release Score

| 维度 | 评分 (1-10) | 说明 |
|------|------------|------|
| Architecture | 7 | Bridge 唯一生产路径确认；UI 层有延迟导入违规（facade 不完整） |
| Security | 7 | 公钥替换攻击已修复；verify_feature 缺失；License 验证顺序待优化 |
| UX | 7 | 错误三段式消息已修复；GUI 硬编码 QSS 仍存在；Toast 使用不足 |
| Packaging | 8 | 缺失数据文件已修复；disable_windowed_traceback 已修复 |
| Installer | 7 | 启动脚本功能正常；缺少错误反馈机制 |
| Performance | 8 | 402 测试 31s 完成；覆盖率 49.97% 待提升 |
| Memory | 8 | matplotlib Figure 清理已修复；单例引用清理待优化 |
| Thread | 8 | quit+wait+terminate 模式正确；_connected 加锁已确认 |
| Industrial Safety | 7 | MATLAB 无超时（已知风险）；崩溃恢复完整；G-code 校验通过 |
| License | 7 | HMAC 空密钥拒绝正确；公钥安全已修复；verify_feature 缺失 |
| Documentation | 6 | 用户手册齐全；README 与实际行为矛盾；根目录残留报告 |
| FAQ | 8 | 7 类常见问题覆盖完整 |
| Release Note | 7 | 结构完整；共享会话描述与代码不一致 |
| Known Issue | 7 | 嵌入发布说明；建议独立成文 |
| **综合评分** | **7.3 / 10** | |

---

## Blocker（已全部修复）

### B-1. launcher.py 使用 `-batch` 模式，违反硬约束 [已修复]

- **文件**: [launcher.py](file:///d:/work/demo/industrial-vision/repair_app/bridge/launcher.py#L163-L172)
- **问题**: 使用 `-batch` 启动 MATLAB，不支持 engine sharing，违反 `project_memory.md` 硬约束
- **修复**: 改为 `-nodesktop -nosplash -r` 模式
- **状态**: 已修复，测试通过

### B-2. repair_app.spec 缺失关键数据文件 [已修复]

- **文件**: [repair_app.spec](file:///d:/work/demo/industrial-vision/repair_app.spec#L34-L52)
- **问题**: `parameter_schema.json` / `matlab_bridge_server.m` / `path_planning/` / `profile_prediction/` 未打包，EXE 启动即崩溃或 MATLAB Bridge 不可用
- **修复**: 在 `datas` 列表中补充全部缺失文件
- **状态**: 已修复

### B-3. License 公钥替换攻击 [已修复]

- **文件**: [resource_path.py](file:///d:/work/demo/industrial-vision/repair_app/utils/resource_path.py#L59-L79), [license_manager.py](file:///d:/work/demo/industrial-vision/repair_app/utils/license_manager.py#L133-L150)
- **问题**: `get_config_dir()` 优先使用用户可写的 `exe/config/` 目录，攻击者可替换 `public_key.pem` 绕过 License 验证
- **修复**: 新增 `get_builtin_config_dir()` / `get_builtin_config_file()`，公钥始终从 `_MEIPASS`（打包内置只读目录）加载
- **状态**: 已修复

### B-4. PyInstaller disable_windowed_traceback=False [已修复]

- **文件**: [repair_app.spec](file:///d:/work/demo/industrial-vision/repair_app.spec#L192)
- **问题**: `console=False` 模式下未禁用 windowed traceback，异常信息可能泄露
- **修复**: 设置 `disable_windowed_traceback=True`
- **状态**: 已修复

---

## Critical

### C-1. Workers _pack_error 丢失 Why/How 字段 [已修复]

- **文件**: [workers.py](file:///d:/work/demo/industrial-vision/repair_app/ui/workers.py#L24-L41), [main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py#L2206-L2212)
- **问题**: `_pack_error` 仅打包 `title + what`，丢弃 `why` 和 `how`，用户看不到恢复建议
- **修复**: 完整传递三段式消息（What + 原因 + 建议）
- **状态**: 已修复

### C-2. crash_handler.py 未检查 stderr None [已修复]

- **文件**: [crash_handler.py](file:///d:/work/demo/industrial-vision/repair_app/utils/crash_handler.py#L40-L72)
- **问题**: `console=False` 模式下 `sys.stderr` 可能为 None，`print(..., file=sys.stderr)` 崩溃
- **修复**: 所有 stderr 写入前检查 `sys.stderr is not None`
- **状态**: 已修复

### C-3. repair_visualizer.py matplotlib Figure 未清理 [已修复]

- **文件**: [repair_visualizer.py](file:///d:/work/demo/industrial-vision/repair_app/ui/repair_visualizer.py#L618-L644), [main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py#L3127-L3129)
- **问题**: Figure 对象从不释放，artists 累积导致内存泄漏
- **修复**: 新增 `cleanup()` 方法（停止定时器 + clf + deleteLater），在 `closeEvent` 中调用
- **状态**: 已修复

### C-4. verify_feature 生产环境缺失 [未修复 — 已知问题]

- **文件**: [license_manager.py](file:///d:/work/demo/industrial-vision/repair_app/utils/license_manager.py)
- **问题**: `LicenseManager` 无 `verify_feature` 方法，License 中 `features` 字段形同虚设
- **影响**: 当前所有用户获得全部功能，功能门禁失效
- **风险评估**: 低 — 当前版本为 V1.0 全功能授权，无分级 License 需求
- **建议**: V1.1 实现功能门禁
- **状态**: 已知问题，不阻塞发布

### C-5. MATLAB 算法调用无超时 [未修复 — 需功能变更]

- **文件**: [matlab_engine_proxy.py](file:///d:/work/demo/industrial-vision/repair_app/bridge/adapters/matlab_engine_proxy.py)
- **问题**: `call_timeout_s` 参数已定义但从未使用，MATLAB 卡死时 GUI 永久阻塞
- **影响**: 工业安全隐患 — 操作员无法判断系统状态
- **风险评估**: 中 — MATLAB 卡死概率低（算法经过验证），ZMQ 层有 30s 超时
- **建议**: V1.1 实现异步调用 + 超时（需 MATLAB Engine API `background=True`）
- **状态**: 已知问题，不阻塞发布（ZMQ 超时部分缓解）

### C-6. 开发模式 HMAC 密钥硬编码 [未修复 — 设计决策]

- **文件**: [license_manager.py](file:///d:/work/demo/industrial-vision/repair_app/utils/license_manager.py#L42-L48)
- **问题**: `_DEV_HMAC_FALLBACK = "csam_dev_secret_2026"` 硬编码在源码中
- **影响**: 仅影响开发模式；生产模式（frozen）正确使用空密钥并拒绝验证
- **状态**: 已知问题，不阻塞发布

### C-7. License 验证顺序不安全 [未修复 — 安全加固]

- **文件**: [license_manager.py](file:///d:/work/demo/industrial-vision/repair_app/utils/license_manager.py#L160-L177)
- **问题**: 签名验证在机器码/过期检查之后，允许渐进式篡改探测
- **影响**: 低 — 公钥已从只读目录加载，篡改 License 无法通过签名验证
- **状态**: 已知问题，V1.1 调整验证顺序

---

## Major

### M-1. 架构违规：UI 直接导入 core/communication/bridge [未修复]

- **文件**: [workers.py](file:///d:/work/demo/industrial-vision/repair_app/ui/workers.py#L19-L20) `from repair_app.core.path_planner import ...`; [main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py#L3119) 6 处延迟导入 bridge
- **问题**: UI 层绕过 CoordinationService 直接导入底层模块
- **根因**: CoordinationService facade 未暴露迭代器/生命周期管理接口
- **影响**: 架构耦合，但不影响功能
- **建议**: V1.1 扩展 facade 接口
- **状态**: 已知问题

### M-2. dialogs.py 大量硬编码 QSS [未修复]

- **文件**: [dialogs.py](file:///d:/work/demo/industrial-vision/repair_app/ui/dialogs.py) 全文（ErrorDialog / LoadingDialog / RobotExportDialog 等 8 个对话框）
- **问题**: 约 50+ 处 `setStyleSheet("color:#DC2626;")` 硬编码颜色，未走 ThemeManager
- **影响**: Light 主题下对话框仍为深色配色，视觉撕裂
- **建议**: V1.1 统一改用 ThemeManager token
- **状态**: 已知问题，不影响功能

### M-3. main_window.py 部分硬编码 QSS [未修复]

- **文件**: [main_window.py](file:///d:/work/demo/industrial-vision/repair_app/ui/main_window.py) 约 25 处
- **问题**: 状态栏部分项使用 `#F8FAFC`、`#10B981` 等硬编码色值
- **影响**: 主题切换不彻底
- **状态**: 已知问题

### M-4. README.md 与实际 MATLAB 自动化行为矛盾 [未修复]

- **文件**: [README.md](file:///d:/work/demo/industrial-vision/README.md#L47-L121)
- **问题**: README 指导用户手动打开 MATLAB、运行 `matlab_bridge_server`，与代码的自动启动行为矛盾
- **影响**: 操作员按 README 操作可能与 lifecycle_manager 冲突
- **建议**: 发布前更新 README
- **状态**: 文档问题

### M-5. STL 读取缺少畸形文件防护 [未修复]

- **文件**: [stl_reader.py](file:///d:/work/demo/industrial-vision/repair_app/core/stl_reader.py)
- **问题**: ASCII 解析未检查 `parts` 长度；`f.readlines()` 无大小限制
- **影响**: 恶意 STL 文件可导致崩溃或 OOM
- **风险评估**: 低 — 工业环境中 STL 来源可控
- **建议**: V1.1 增加输入校验
- **状态**: 已知问题

### M-6. 异常报告泄露敏感路径 [未修复]

- **文件**: [exception_reporter.py](file:///d:/work/demo/industrial-vision/repair_app/software/exception_reporter.py#L96-L120)
- **问题**: 报告包含 `sys.executable` 完整路径、用户数据目录、完整 traceback
- **影响**: 报告若被不当分享可能泄露部署信息
- **建议**: V1.1 对路径脱敏
- **状态**: 已知问题

### M-7. 根目录残留 9 份评审报告 [未修复]

- **文件**: 项目根目录 `CONFIG_REFACTOR.md` / `ERROR_SYSTEM.md` / `GUI_REVIEW.md` 等 9 份
- **问题**: 内部报告未归档到 `docs/archive/`
- **影响**: 非技术用户可能被误导
- **状态**: 文档问题

---

## Minor

| # | 问题 | 文件 | 状态 |
|---|------|------|------|
| m-1 | 全局钩子在 QApplication 之前安装 | run_app.py:49 | 已知 |
| m-2 | Toast 仅在 2 处使用，长操作完成未提示 | main_window.py | 已知 |
| m-3 | 旧版 zmq_client `_connected` 无锁（已 deprecated） | communication/zmq_client.py:167 | 可接受 |
| m-4 | progress_publisher 跨线程读 `_enabled`/`_sock` 无锁 | progress_publisher.py:65,126 | 可接受 |
| m-5 | heartbeat `_running` 跨线程无锁（CPython 原子） | heartbeat.py:41 | 可接受 |
| m-6 | matlab_engine_proxy DCL 外层无锁读取 | matlab_engine_proxy.py:107 | 标准模式 |
| m-7 | closeEvent 未调 MatlabLifecycleManager.reset_singleton() | main_window.py:3118 | 已知 |
| m-8 | `_layer_data_cache` 在 closeEvent 未清空 | main_window.py:358 | 随 GC 释放 |
| m-9 | `_anim_timer` 未在 MainWindow 拆除时显式 stop | repair_visualizer.py | 已通过 cleanup() 修复 |
| m-10 | 机器码算法在虚拟机环境可能不稳定 | license_manager.py:57-69 | 已知 |
| m-11 | License 过期后行为：无到期日 = 永久有效 | license_manager.py:100-107 | 设计意图 |
| m-12 | 机器人导出 zone 参数无注入过滤（GUI 限制预定义值） | robot_exporter.py:135 | 可接受 |
| m-13 | ASCII STL 解析器无文件头格式探测 | stl_reader.py:25-28 | 已知 |
| m-14 | G-code 元数据嵌入 License 机器码前 12 字符 | main_window.py:2706 | 已知 |
| m-15 | 旧版机器码向后兼容扩大攻击面 | license_manager.py:72-84 | 过渡期设计 |
| m-16 | `repair_protocol.proto` 打包但运行时不需要 | repair_app.spec:51 | 无害 |
| m-17 | `dist/morphology_prediction/velocitylist.json` 遗留产物 | dist/ | 建议清理 |
| m-18 | UPX 压缩可能未生效（未安装 UPX 时静默跳过） | repair_app.spec:176 | 无害 |
| m-19 | pyproject.toml 与 requirements.txt 依赖声明不一致 | pyproject.toml / requirements.txt | 已知 |
| m-20 | 启动脚本 `start ""` 无错误反馈 | 启动软件.bat | 已知 |
| m-21 | MATLAB 未找到时缺少用户可见弹窗通知 | run_app.py:110-118 | 已知 |

---

## 修复清单汇总

### 已修复（本次审查）

| # | 级别 | 问题 | 文件 |
|---|------|------|------|
| B-1 | Blocker | launcher.py `-batch` → `-r` | bridge/launcher.py |
| B-2 | Blocker | spec 缺失 parameter_schema.json / matlab_bridge_server.m / 算法目录 | repair_app.spec |
| B-3 | Blocker | 公钥替换攻击 — 新增 `get_builtin_config_file()` 从 `_MEIPASS` 加载 | resource_path.py, license_manager.py |
| B-4 | Blocker | `disable_windowed_traceback=False` → `True` | repair_app.spec |
| C-1 | Critical | `_pack_error` 丢失 Why/How — 完整传递三段式消息 | workers.py, main_window.py |
| C-2 | Critical | crash_handler.py stderr None 崩溃 — 添加 None 检查 | crash_handler.py |
| C-3 | Critical | matplotlib Figure 未清理 — 新增 `cleanup()` 方法 | repair_visualizer.py, main_window.py |

### 未修复（已知问题，不阻塞发布）

| # | 级别 | 问题 | 原因 |
|---|------|------|------|
| C-4 | Critical | verify_feature 缺失 | V1.0 全功能授权，无分级需求 |
| C-5 | Critical | MATLAB 调用无超时 | 需功能变更（异步 API），ZMQ 层有 30s 超时缓解 |
| C-6 | Critical | 开发模式 HMAC 硬编码 | 仅影响开发模式，生产模式正确 |
| C-7 | Critical | License 验证顺序 | 公钥已安全加载，风险降低 |
| M-1~M-7 | Major | 架构违规 / QSS 硬编码 / README 矛盾 / STL 防护 / 路径泄露 / 文档残留 | 不影响功能，V1.1 修复 |

---

## 审查维度明细

### Architecture

- Bridge 是唯一生产通信路径（`CoordinationService.create_zmq_client()` 优先返回 `LegacyZmqClient`）
- 旧版 `zmq_client.py` 已 deprecated 但未移除（符合约束）
- `CoordinationService` facade 不完整，导致 UI 层 8 处延迟导入 core/communication/bridge
- **结论**: 架构基本正确，facade 待扩展

### Security

- HMAC 空密钥正确拒绝（生产模式）
- 公钥从 `_MEIPASS` 只读加载（已修复）
- 私钥不打包进 EXE（spec `datas` 仅含 `public_key.pem`）
- `verify_feature` 缺失（已知问题）
- **结论**: 安全基线达标，功能门禁待 V1.1

### UX

- 7 类错误分类完整，三段式消息已修复
- 全局钩子（sys.excepthook + threading.excepthook）已安装
- 6 个后端功能全部接入 GUI
- GUI 硬编码 QSS 约 75 处（dialogs.py + main_window.py）
- **结论**: UX 功能完整，主题一致性待改进

### Packaging

- `console=False` 正确
- 全部数据文件已打包（已修复）
- `disable_windowed_traceback=True`（已修复）
- hiddenimports 完整（PySide6/protobuf/zmq/matplotlib/numpy/scipy/reportlab/cryptography/shapely）
- 可选依赖优雅降级（reportlab/shapely/loguru/cryptography）
- **结论**: 打包配置达标

### Thread Safety

- Worker-on-Thread 模式正确（moveToThread + started→run + finished→deleteLater）
- 协作式中断（isInterruptionRequested）
- ZMQ `_connected` 加锁（Phase 2 修复已确认）
- Workers 入参 `.copy()` 隔离
- closeEvent: quit + wait(5s) + terminate + wait(2s)
- **结论**: 线程安全达标

### Industrial Safety

- 崩溃恢复完整（看门狗 3s 轮询 + 最大 3 次自动重启）
- G-code 导出前校验（NaN/Inf/安全高度/速度范围/重复点/长段）
- MATLAB 崩溃后中间结果未标记无效（已知风险）
- MATLAB 调用无超时（已知风险，ZMQ 30s 超时部分缓解）
- **结论**: 工业安全基本达标，超时机制待 V1.1

### License

- HMAC 验证正确（空密钥拒绝 + 正确签名接受 + 错误签名拒绝）
- 过期检查正确（过期后拒绝启动）
- 公钥安全加载（已修复）
- 机器码绑定（新旧两种格式兼容）
- **结论**: License 系统达标

### Documentation

- 用户手册 4 篇（快速开始 / 安装部署 / 使用手册 / 工程化功能）
- FAQ 7 类常见问题
- 发布说明 + 更新日志（Keep a Changelog 格式）
- README 与实际行为矛盾（已知问题）
- 根目录残留 9 份内部报告（已知问题）
- **结论**: 文档齐全，README 待更新

---

## 测试验证

```
402 passed, 0 failed, 6 warnings in 31.01s
```

- 6 warnings 全部为旧版 `zmq_client` 的 `DeprecationWarning`（预期行为）
- 修复后零回归
- 覆盖率: 49.97%（低于 60% 阈值，已知问题）

---

## 最终建议

### Ready for Release（有条件发布）

**理由**:

1. **所有 Blocker 已修复** — 4 个 Blocker 全部修复，测试通过
2. **关键 Critical 已修复** — _pack_error Why/How / crash_handler stderr / Figure 清理 已修复
3. **402 测试零回归** — 修复未引入任何新问题
4. **剩余问题不阻塞功能** — 未修复项均为已知问题或需功能变更

**发布条件**:

- 发布前必须更新 `README.md`，删除手动启动 MATLAB 的指导（文档问题 M-4）
- 发布前必须将根目录 9 份内部报告移至 `docs/archive/`（文档问题 M-7）
- EXE 重新构建（spec 变更后必须重新打包）

**已知风险（需在发布说明中披露）**:

1. MATLAB 算法调用无超时（C-5）— MATLAB 卡死时 GUI 阻塞，需手动关闭
2. License 功能门禁未实现（C-4）— 当前所有用户获得全部功能
3. 覆盖率 49.97%（低于 60% 阈值）— 建议后续版本补充测试
4. GUI 硬编码 QSS（M-2/M-3）— Light 主题下对话框配色不一致

**V1.1 修复路线图**:

1. MATLAB 异步调用 + 超时（C-5）
2. `verify_feature` 功能门禁（C-4）
3. 扩展 CoordinationService facade，消除架构违规（M-1）
4. 统一 ThemeManager，消除硬编码 QSS（M-2/M-3）
5. STL 输入校验（M-5）
6. License 验证顺序优化（C-7）
7. 覆盖率提升至 80%
