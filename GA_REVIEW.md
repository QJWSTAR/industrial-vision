# GA_REVIEW — CSAM Repair v1.0.0 General Availability 最终审查

> **审查日期**：2026-07-15
> **审查目标**：确认 v1.0.0 是否可作为正式商业版本发布
> **审查模式**：只读审查，未修改任何代码
> **审查范围**：安装体验 / 发布产物 / 安全 / 工业安全 / 发布检查 / 最终评分

---

## 最终决策

```
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   最终决策：NO GO                                            ║
║                                                              ║
║   v1.0.0 不具备 General Availability 商业发布条件            ║
║                                                              ║
║   存在 4 个 GA Blocker（不可绕过）                           ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
```

**核心原因**：软件打包后因 License 机器绑定无法在任何非构建机器上启动，且缺少商业发布必需的第三方许可证文件与正式安装包。这些问题不是 V1.1 优化项，而是商业发布的硬性红线。

---

## 一、安装体验审查

### 1.1 平台支持

| 平台 | 状态 | 说明 |
|------|------|------|
| Windows 10/11 | ⚠️ 有条件通过 | EXE 可启动（仅限构建机器，见 B-GA-1）；VC Runtime 未显式处理（见 C-GA-3） |
| macOS 10.14+ | ⚠️ 代码存在 | build_macos.sh + .app bundle 配置存在，但未实际构建验证；未代码签名 |
| Linux | ⚠️ 代码存在 | POSIX 平台抽象（ipc socket）存在，但无 Linux 构建脚本与验证 |

### 1.2 安装方式

| 方式 | 状态 | 说明 |
|------|------|------|
| Installer（安装包） | ❌ FAIL | **无 NSIS/Inno Setup/MSI 安装包**，仅 PyInstaller 单文件 EXE（见 B-GA-3） |
| Portable（便携版） | ✅ PASS | 源码 + venv 方式可用；EXE 也可作为便携版 |
| 首次启动 | ⚠️ 部分通过 | 启动软件.bat 可拉起 EXE；但 License 验证阻断（见 B-GA-1） |
| 升级安装 | ❌ FAIL | 无升级机制，用户需手动删除旧 EXE + 拷贝新 EXE |
| 卸载 | ❌ FAIL | 无卸载程序，无"添加/删除程序"注册；用户需手动删除 EXE + %APPDATA%/CSAM_Repair |
| 配置保留 | ⚠️ 部分通过 | 用户数据在 %APPDATA%/CSAM_Repair（正确保留）；但 license.key 在 exe 同级 config/，升级时易丢失（见 C-GA-4） |

### 1.3 运行时依赖

| 依赖 | 状态 | 说明 |
|------|------|------|
| License | ❌ FAIL | **构建机器绑定的 license.key 无法分发**（见 B-GA-1） |
| MATLAB | ✅ PASS | 可选依赖；未安装时自动降级到 Python 启发式算法，软件仍可运行 |
| Python Runtime | ✅ PASS | PyInstaller 打包，无需用户安装 Python |
| VC Runtime | ⚠️ 未验证 | spec 中 `if IS_WINDOWS: pass`，未显式包含 VC Redist DLL（见 C-GA-3） |
| 依赖完整性 | ✅ PASS | requirements.txt 完整（10 个依赖），spec hiddenimports 覆盖全部模块 |

### 1.4 安装体验评分：4/10

---

## 二、发布产物审查

### 2.1 产物清单

| 产物 | 状态 | 说明 |
|------|------|------|
| Release Package | ⚠️ 部分通过 | dist/CSAM_Repair.exe (113 MB) + dist/config/ 存在；但 build/ 目录残留（见 C-GA-2） |
| Installer | ❌ FAIL | 无正式安装包（见 B-GA-3） |
| Portable | ✅ PASS | EXE 可作为便携版；源码方式可用 |
| README | ✅ PASS | 已更新为 Stable Release，无 RC 残留 |
| CHANGELOG | ✅ PASS | v0.7.0 → v1.0.0 完整变更记录 |
| LICENSE | ✅ PASS | MIT License（项目自身许可证） |
| **Third Party License** | ❌ FAIL | **缺失**（见 B-GA-2） |
| **NOTICE** | ❌ FAIL | **缺失**（见 B-GA-2） |
| User Manual | ✅ PASS | 4 篇（快速开始/安装部署/使用手册/软件工程化功能） |
| Developer Guide | ✅ PASS | 开发者指南 + 开发指南 |
| FAQ | ✅ PASS | 常见问题.md (222 行) |
| Quick Start | ✅ PASS | 5 分钟上手指南 |
| Known Issues | ✅ PASS | 10 个已知问题（3 限制 + 7 缺陷） |
| Release Notes | ✅ PASS | V1.0.0 Stable Release 发布说明 |

### 2.2 版本号一致性

| 位置 | 版本号 | 一致 |
|------|--------|------|
| repair_app/__init__.py | 1.0.0 (stable) | ✅ |
| VERSION 文件 | 1.0.0 | ✅ |
| bridge/__init__.py | 1.0.0 | ✅ |
| README.md | Stable Release | ✅ |
| 发布说明.md | 1.0.0 (正式版) | ✅ |
| 更新日志.md | [1.0.0] — 2026-07-15 | ✅ |
| DOCUMENT_INDEX.md | 1.0.0 Stable Release | ✅ |
| repair_app.spec | 从 __init__.py 读取 | ✅ |

**版本号全局一致 ✅**

### 2.3 发布产物评分：5/10

---

## 三、安全审查

### 3.1 License 安全

| 检查项 | 状态 | 说明 |
|--------|------|------|
| License 验证流程 | ✅ PASS | run_app.py 前置验证，失败则 sys.exit(1) |
| RSA-2048 签名 | ✅ PASS | PSS + SHA-256，算法正确 |
| 公钥防替换 | ✅ PASS | 从 _MEIPASS 只读加载（get_builtin_config_file） |
| HMAC 退化拒绝 | ✅ PASS | 生产环境（is_frozen）空密钥直接拒绝 |
| 机器码绑定 | ⚠️ 双刃剑 | 绑定 MAC+hostname，防盗用；但导致无法分发（见 B-GA-1） |
| License 激活流程 | ❌ FAIL | **无激活 UI、无机器码展示、无申请流程**（见 B-GA-1） |
| 试用模式 | ❌ FAIL | 无试用模式，无 CSAM_SKIP_LICENSE 环境变量 |

### 3.2 代码签名

| 检查项 | 状态 | 说明 |
|--------|------|------|
| Windows 代码签名 | ❌ FAIL | spec `codesign_identity=None`（见 B-GA-4） |
| macOS 代码签名 | ❌ FAIL | spec `codesign_identity=None` |
| macOS 公证 | ❌ FAIL | 无 notarization 配置 |

### 3.3 资源路径安全

| 检查项 | 状态 | 说明 |
|--------|------|------|
| resource_path.py | ✅ PASS | is_frozen() + _MEIPASS 正确处理 |
| 用户数据隔离 | ✅ PASS | %APPDATA%/CSAM_Repair（标准用户目录） |
| 临时文件 | ✅ PASS | PyInstaller 单文件模式解压到系统临时目录 |
| 配置目录回退 | ✅ PASS | exe 同级 config/ → _MEIPASS/config/ |

### 3.4 日志与崩溃

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 日志目录 | ✅ PASS | %APPDATA%/CSAM_Repair/logs/ |
| 崩溃日志 | ✅ PASS | crash_*.log + exception_*.log，UTF-8 编码 |
| stderr None 检查 | ✅ PASS | crash_handler 所有 stderr 写入前检查 |
| Traceback 泄露 | ✅ PASS | disable_windowed_traceback=True + ErrorManager 三段式消息 |
| 敏感信息泄露 | ✅ PASS | 公钥不写入日志；License 签名不完整输出 |

### 3.5 安全评分：5/10

---

## 四、工业安全审查

### 4.1 G-code 安全

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 坐标模式 | ✅ PASS | 绝对模式 G90 / 增量模式 G91 正确切换 |
| 增量模式首点 | ✅ PASS | G90 临时切换定位起点，再 G91 恢复 |
| 安全高度校验 | ✅ PASS | safe_z > z_max 强制校验，不满足则 BLOCKED |
| NaN/Inf 检查 | ✅ PASS | 航点坐标 NaN/Inf 阻止导出 |
| 进给速度范围 | ✅ PASS | [1, 60000] mm/min 范围校验 |
| 重复点检测 | ✅ PASS | WARNING 提示停顿/过喷风险 |
| 长段检测 | ✅ PASS | >80mm 段 WARNING 提示缺少过渡路径 |
| 抬刀回安全高度 | ✅ PASS | 每段结束 + 最终抬刀到 safe_z |
| 送粉 M 代码 | ✅ PASS | 开启/关闭成对，稳定延时 G4 |

### 4.2 G-code 元数据（追溯）

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 软件版本 | ✅ PASS | `(__version__)` |
| 模型版本 | ✅ PASS | set_metadata(model_version=...) |
| 生成时间 | ✅ PASS | YYYY-MM-DD HH:MM:SS |
| 材料 | ✅ PASS | set_metadata(material=...) |
| Git Commit | ✅ PASS | _get_git_commit() |
| License ID | ✅ PASS | machine_id[:12] |
| 参数 | ✅ PASS | key=value 逗号分隔 |
| 文件编码 | ✅ PASS | UTF-8（export 方法 open(encoding="utf-8")） |

### 4.3 G-code 工业安全评分：9/10

> G-code 模块是本项目工业安全最完善的部分，7 项追溯元数据 + 8 项安全校验全部到位。

### 4.4 其他工业安全

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 材料数据库 | ✅ PASS | material_db.json + material_database.py |
| 仿真验证 | ⚠️ 部分 | algorithm_validator.py 存在但 coverage 0%（未实际运行） |
| 导出验证 | ✅ PASS | export_validator.py 完整（6 项校验） |
| 错误分类 | ✅ PASS | 7 类错误码（LICENSE/MATLAB/FILE/MESH/NETWORK/EXPORT/UNKNOWN） |

---

## 五、发布检查

### 5.1 测试与质量

| 检查项 | 状态 | 说明 |
|--------|------|------|
| 所有测试通过 | ✅ PASS | 402 passed, 6 warnings (legacy DeprecationWarning), 0 failed |
| 覆盖率 | ⚠️ 50.02% | 低于 60% 阈值（已知问题 COV-1） |
| 无 Release Blocker（代码层） | ✅ PASS | RC 审查 4 Blocker + 3 Critical 全部修复 |
| 无 Critical（代码层） | ✅ PASS | 代码层无 Critical |
| Known Issue 已记录 | ✅ PASS | 10 个已知问题全部记录在 已知问题.md |

### 5.2 文档与发布材料

| 检查项 | 状态 | 说明 |
|--------|------|------|
| README 最新 | ✅ PASS | Stable Release，无 RC 残留 |
| FAQ 最新 | ✅ PASS | 222 行，覆盖安装/运行/MATLAB/License |
| **截图最新** | ❌ FAIL | docs/images/ 仅有 p1.jpg（图标），**无任何产品截图**（见 C-GA-1） |
| 版本一致 | ✅ PASS | 全局 1.0.0 stable |
| 所有链接有效 | ✅ PASS | docs check 58 个交叉引用全部有效 |
| 文档头部规范 | ✅ PASS | docs check 全部通过，0 警告 |
| Mermaid 流程图 | ✅ PASS | 7 个 |

### 5.3 发布检查评分：6/10

---

## 六、最终评分

### 6.1 维度评分

| 维度 | 评分 | 说明 |
|------|------|------|
| Architecture | 8/10 | Bridge 架构清晰，单一生产路径，协议通用，扩展性好 |
| Maintainability | 6/10 | MainWindow God Class (1898 行)；测试覆盖率 50%；旧版 communication/ 未清理 |
| Reliability | 7/10 | 7 类错误处理完整；降级策略可用；但 MATLAB 调用无超时（C-5） |
| Packaging | 3/10 | 无正式安装包；无代码签名；无卸载/升级；build/ 残留 |
| Documentation | 7/10 | 38 篇文档完整；但无截图；Third Party License 缺失 |
| Security | 5/10 | 公钥防替换 ✅；但 License 无法分发 ❌；无代码签名 ❌ |
| Industrial Safety | 9/10 | G-code 8 项校验 + 7 项追溯元数据，工业安全最完善 |
| User Experience | 4/10 | 无安装向导；无 License 激活；首次启动被 License 阻断 |

### 6.2 综合评分

```
综合评分 = (8 + 6 + 7 + 3 + 7 + 5 + 9 + 4) / 8 = 49/80 = 6.1/10
```

### 6.3 GA Blocker 清单

#### B-GA-1：License 机器绑定导致无法分发（致命）

**证据**：
- `dist/config/license.key` 的 `machine_id` = `7f81b126-06df-0f54-a53d-d8faeac4854e`
- 该 machine_id 基于构建机器的 MAC 地址 + hostname（`uuid.getnode()` + `platform.node()`）
- 实测：当前构建机器 machine_id 与 license.key 完全匹配
- `run_app.py` line 58-72：License 验证失败 → `QMessageBox.critical` → `sys.exit(1)`
- 软件在任何非构建机器上**拒绝启动**

**缺失项**：
- 无 License 激活 UI（用户无法查看本机机器码）
- 无 License 申请流程（用户无法获取 license.key）
- 无 License 导入功能（用户无法在 GUI 中导入 license.key）
- 无试用模式（无 CSAM_SKIP_LICENSE 环境变量，无 trial 机制）
- 无机器码展示对话框

**影响**：软件打包后**无法分发给任何最终用户**。这是商业发布的绝对红线。

**必须解决**（非 V1.1，是 V1.0 GA 必需）：
1. 新增"License 激活向导"：首次启动检测到 license.key 无效/缺失时，弹出向导
2. 向导展示本机机器码（二维码 + 文本），用户复制发给管理员
3. 提供 license.key 导入入口（文件选择对话框）
4. 可选：试用模式（7 天/30 天，功能受限）

#### B-GA-2：缺少 Third Party License 与 NOTICE 文件（法律合规）

**证据**：
- 项目根目录无 `THIRD_PARTY_LICENSES.txt`、无 `NOTICE` 文件
- 依赖清单（requirements.txt）包含 10 个第三方库：

| 依赖 | 许可证 | 合规要求 |
|------|--------|----------|
| PySide6 | LGPL/GPL/Qt Commercial | **必须**声明 LGPL，提供动态链接声明或对象文件 |
| pyzmq | LGPL/BSD | **必须**声明 LGPL |
| numpy | BSD-3-Clause | 必须保留版权声明 |
| scipy | BSD-3-Clause | 必须保留版权声明 |
| matplotlib | PSF-based | 必须保留版权声明 |
| shapely | BSD-3-Clause | 必须保留版权声明 |
| protobuf | BSD-3-Clause | 必须保留版权声明 |
| reportlab | BSD-3-Clause | 必须保留版权声明 |
| cryptography | Apache-2.0 OR BSD-3-Clause | 必须保留 NOTICE |
| loguru | MIT | 必须保留版权声明 |

**影响**：违反 LGPL（PySide6、pyzmq）与多个开源许可证的归属要求，商业发布存在法律风险。

**必须解决**：
1. 创建 `THIRD_PARTY_LICENSES.txt`，列出全部 10 个依赖的许可证全文
2. 创建 `NOTICE` 文件，声明项目使用的第三方库及其许可证
3. 特别处理 PySide6 LGPL 合规：声明动态链接、提供"重新链接"说明

#### B-GA-3：无真正意义的安装包（商业体验）

**证据**：
- 项目根目录无 `.nsi`（NSIS）、`.iss`（Inno Setup）、`.msi` 文件
- 仅有 `build_windows.bat` 调用 `pyinstaller --clean repair_app.spec`
- 产出为单文件 EXE（portable），非安装包

**缺失项**：
- 安装向导（许可协议、安装路径选择、快捷方式创建）
- 添加/删除程序注册（Windows 注册表）
- 卸载程序
- 升级安装机制（版本检测、旧版清理、配置迁移）
- 文件关联（.csam 项目文件双击打开）

**影响**：不符合商业软件安装体验标准；企业 IT 部门无法统一部署。

**必须解决**：
- 使用 NSIS 或 Inno Setup 创建正式安装包
- 包含许可协议、安装路径、快捷方式、卸载、文件关联

#### B-GA-4：EXE 未代码签名（信任与安全）

**证据**：
- `repair_app.spec` line 195：`codesign_identity=None`
- 无 macOS notarization 配置

**影响**：
- Windows SmartScreen 拦截未签名 EXE → 用户看到"Windows 已保护你的电脑"警告
- macOS Gatekeeper 拦截未签名 .app → 用户无法直接运行
- 企业环境安全策略可能直接删除/隔离未签名 EXE
- 用户信任度低，误判为恶意软件风险高

**必须解决**：
- 购买代码签名证书（EV 证书优先，可立即获得 SmartScreen 信誉）
- spec 配置 `codesign_identity`
- macOS 配置 Developer ID + notarization

### 6.4 Critical 清单（不阻塞但严重影响商业发布）

| ID | 问题 | 影响 |
|----|------|------|
| C-GA-1 | 无截图资源（docs/images/ 仅有图标 p1.jpg） | 用户手册/快速开始/发布说明无可视化预览，文档可读性差 |
| C-GA-2 | build/ 目录残留（PyInstaller 中间产物） | 发布包体积膨胀，可能泄露构建路径信息 |
| C-GA-3 | VC Runtime 未显式处理（spec `if IS_WINDOWS: pass`） | 干净 Windows 系统（无 VC Redist）可能无法启动 |
| C-GA-4 | license.key 在 exe 同级 config/（非用户数据目录） | 升级时删除旧 EXE 目录导致 license.key 丢失 |
| C-GA-5 | MATLAB 算法调用无超时（call_timeout_s 已定义未使用） | MATLAB 卡死时 GUI 永久阻塞（已知问题 C-5，仍未修复） |
| C-GA-6 | 测试覆盖率 50.02% < 60% 阈值 | 回归风险（已知问题 COV-1，仍未达标） |

---

## 七、Release Checklist 最终状态

| # | 检查项 | 状态 | 说明 |
|---|--------|------|------|
| 1 | 无 Release Blocker | ❌ FAIL | **4 个 GA Blocker**（B-GA-1 ~ B-GA-4） |
| 2 | 所有测试通过 | ✅ PASS | 402 passed, 0 failed |
| 3 | 文档一致 | ⚠️ PARTIAL | 38 篇文档一致；但缺 Third Party License + NOTICE |
| 4 | 打包成功 | ⚠️ PARTIAL | EXE 构建成功；但无正式安装包；未代码签名 |
| 5 | License 正常 | ❌ FAIL | **构建机器绑定，无法分发** |
| 6 | MATLAB 正常 | ✅ PASS | Bridge v2.1 + 降级策略 |
| 7 | G-code 正常 | ✅ PASS | G90/G91 + 8 项校验 + 7 项元数据 |
| 8 | Windows 正常 | ⚠️ PARTIAL | 代码可用；但未签名 + 无安装包 |
| 9 | macOS 正常 | ⚠️ PARTIAL | 代码存在；未实际构建验证 + 未签名 |
| 10 | Linux 正常 | ⚠️ PARTIAL | 代码存在；无构建脚本 + 未验证 |

**结论：4 项 FAIL，5 项 PARTIAL，仅 3 项 PASS。不满足 GA 发布条件。**

---

## 八、必须解决的问题（按优先级）

### P0 — GA 发布前必须解决（非 V1.1）

1. **B-GA-1：License 激活流程**
   - 新增 License 激活向导（机器码展示 + license.key 导入）
   - 移除 dist/config/ 中构建机器绑定的 license.key
   - 或：提供管理员签发工具 + 用户激活流程

2. **B-GA-2：Third Party License + NOTICE**
   - 创建 THIRD_PARTY_LICENSES.txt（10 个依赖许可证全文）
   - 创建 NOTICE 文件
   - 处理 PySide6 LGPL 合规

3. **B-GA-3：正式安装包**
   - 使用 NSIS/Inno Setup 创建安装包
   - 包含安装向导、卸载、文件关联

4. **B-GA-4：代码签名**
   - 购买代码签名证书
   - spec 配置 codesign_identity
   - macOS notarization

### P1 — 强烈建议在 GA 前解决

5. **C-GA-1：补充产品截图**（至少 8 张：主界面/加载点云/缺陷选取/路径规划/形貌预测/G-code 导出/About/License 状态）
6. **C-GA-2：清理 build/ 目录**（加入 .gitignore，发布包排除）
7. **C-GA-3：显式处理 VC Runtime**（spec 中显式包含或文档说明依赖）

---

## 九、对比 READY_FOR_RELEASE.md 的差异

| 检查项 | READY_FOR_RELEASE.md | GA_REVIEW.md（实际） | 差异原因 |
|--------|---------------------|---------------------|----------|
| 无 Release Blocker | ✅ PASS | ❌ FAIL | RC 审查仅关注代码层 Blocker，未审查**商业发布** Blocker |
| License 正常 | ✅ PASS | ❌ FAIL | RC 验证仅在构建机器测试通过，未考虑**分发到其他机器** |
| 打包成功 | ✅ PASS | ⚠️ PARTIAL | EXE 构建成功，但**无正式安装包 + 未签名** |
| 文档一致 | ✅ PASS | ⚠️ PARTIAL | 文档链接一致，但**缺 Third Party License + NOTICE** |
| Windows 正常 | ✅ PASS | ⚠️ PARTIAL | 代码可用，但**未签名 + 无安装包** |

**差异根本原因**：READY_FOR_RELEASE.md 的验证视角是"代码能否运行"，GA_REVIEW.md 的验证视角是"**能否作为商业产品交付给最终用户**"。两者标准不同。

---

## 十、结论

### v1.0.0 当前状态

- **代码质量**：良好（402 测试通过，RC Blocker 全部修复，G-code 工业安全完善）
- **商业发布就绪度**：**不足**

### 不能 GA 的核心原因

1. **软件打包后无法在非构建机器上启动**（License 机器绑定 + 无激活流程）— 这是致命的
2. **缺少商业发布必需的法律文件**（Third Party License + NOTICE）— 法律红线
3. **无正式安装包与代码签名**— 商业体验红线

### 建议

当前版本应保持为 **"Release Candidate"** 状态，不可宣布为 **"General Availability"**。

解决 P0 问题后，重新执行 GA 审查。P0 问题不属于 V1.1 功能开发，而是 V1.0 商业发布的必需交付物。

---

*本文件由 GA 最终审查流程生成。审查日期：2026-07-15。审查模式：只读，未修改任何代码。*
