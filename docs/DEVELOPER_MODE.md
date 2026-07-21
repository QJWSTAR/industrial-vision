# Developer Mode 开发者模式

> 版本：1.0.0 | 更新日期：2026-07-15

## 1. 用途

Developer Mode（开发者模式）让开发版软件**无需 License 即可启动**，用于内部开发、联调、测试和验证阶段。

当前项目处于内部开发阶段，暂时不需要商业 License 激活流程。Developer Mode 让团队成员能快速启动软件进行调试，不必为每台开发机器签发 License。

**关键原则**：Developer Mode **不删除 License 架构**，只是在启动流程中增加一个"跳过"开关。未来恢复商业授权时，只需关闭此开关，无需重构任何代码。

---

## 2. 如何开启

有两种方式开启 Developer Mode：

### 方式一：修改配置文件（持久化）

编辑 `config/app_config.json`：

```json
{
  "developer_mode": true
}
```

设为 `true` 即开启，设为 `false` 即关闭。

### 方式二：设置环境变量（临时覆盖）

```powershell
# Windows PowerShell（当前会话临时生效）
$env:CSAM_DEVELOPER_MODE = "true"

# 然后启动软件
python run_app.py
```

```bash
# macOS / Linux
export CSAM_DEVELOPER_MODE=true
python run_app.py
```

接受的值：`true` / `false` / `1` / `0` / `yes` / `no` / `on` / `off`（不区分大小写）。

### 优先级

环境变量 > 配置文件 > 默认值（`false`）

如果环境变量 `CSAM_DEVELOPER_MODE` 已设置，则忽略配置文件中的值。

---

## 3. 如何关闭

### 恢复为商业 License 模式

**方式一**：修改 `config/app_config.json`：

```json
{
  "developer_mode": false
}
```

**方式二**：删除环境变量：

```powershell
Remove-Item Env:CSAM_DEVELOPER_MODE
```

关闭后，软件启动时会执行完整的商业 License 校验流程（机器码绑定 + RSA 签名验证 + 过期检查）。

---

## 4. 为什么保留 License 架构

| 原因 | 说明 |
|------|------|
| 未来商业发布 | 正式版需要 License 控制授权范围和有效期 |
| 防盗用 | License 绑定机器码，防止未授权复制 |
| 功能分级 | 未来版本可能需要按 License 等级开放不同功能 |
| 审计追溯 | G-code 导出时记录 License ID，支持生产追溯 |

Developer Mode 只是"暂时跳过校验"，不是"移除校验能力"。License 架构的所有代码（`LicenseManager` / `LicenseData` / RSA 签名 / HMAC / 机器码 / 过期检查）全部保留且未修改。

---

## 5. 未来如何恢复商业授权

恢复商业授权只需 **3 步**，无需修改任何业务代码：

### 第 1 步：关闭 Developer Mode

```json
// config/app_config.json
{
  "developer_mode": false
}
```

### 第 2 步：签发 License

```powershell
# 生成密钥对（仅需一次）
python -m repair_app.utils.license_manager keygen

# 为目标机器签发 License（需获取目标机器码）
python -m repair_app.utils.license_manager issue "用户名" 365
```

### 第 3 步：分发 License 文件

将 `config/license.key` 和 `config/public_key.pem` 分发给用户，放置在 EXE 同级的 `config/` 目录下。

完成。软件启动时会自动执行完整 License 校验。

---

## 6. 架构说明

### 6.1 统一配置入口

```
config/app_config.json          ← 持久化配置（developer_mode: true/false）
        │
        ▼
repair_app/utils/app_config.py  ← AppConfig 单例（唯一 Truth Source）
        │
        │  AppConfig.is_developer_mode()
        │
        ▼
repair_app/utils/license_manager.py
        │
        │  LicenseManager.verify_runtime()
        │
        ├── Developer Mode → 返回 LicenseStatus(valid=True, mode="developer")
        │                    跳过 License 校验
        │
        └── Release Mode  → 调用 load_license()
                             执行完整商业 License 校验
```

### 6.2 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| AppConfig | `repair_app/utils/app_config.py` | 统一配置入口，线程安全单例，支持环境变量覆盖 |
| LicenseStatus | `repair_app/utils/license_manager.py` | 运行时校验结果数据类（valid / mode / message / days_remaining） |
| LicenseManager.verify_runtime() | `repair_app/utils/license_manager.py` | 启动流程唯一决策点，根据 Developer Mode 分支 |
| _log_developer_mode_banner() | `run_app.py` | Developer Mode 启动横幅日志 |

### 6.3 配置优先级

```
环境变量 CSAM_DEVELOPER_MODE  （最高优先级，临时覆盖）
        │
        ▼
config/app_config.json        （持久化配置）
        │
        ▼
默认值 false                   （安全默认：生产模式）
```

### 6.4 UI 标识

Developer Mode 下：

- **标题栏**：`冷喷涂缺陷修复软件 v1.0.0  【Developer Build】`
- **状态栏**：`🛠 Developer Mode`（黄色警告色）

Release Mode 下：

- **标题栏**：`冷喷涂缺陷修复软件 v1.0.0`
- **状态栏**：`✅ License 有效 (365 天)` 或 `⛔ License 无效`

### 6.5 启动日志

Developer Mode 启动日志：

```
============================================================
Developer Mode Enabled
License Verification Skipped
============================================================
```

Release Mode 启动日志：

```
Release Mode: License verified (365 days remaining)
License 有效，剩余 365 天
```

---

## 7. 测试

### 测试文件

`repair_app/tests/test_developer_mode.py` — 28 项测试，覆盖 6 大类：

| 测试类 | 测试数 | 说明 |
|--------|--------|------|
| TestAppConfig | 10 | 配置加载、优先级、环境变量、override、reload |
| TestLicenseStatus | 4 | 数据类封装 |
| TestVerifyRuntimeDeveloperMode | 5 | Developer Mode 4 场景 + 不调用 load_license |
| TestVerifyRuntimeReleaseMode | 3 | Release Mode 回归 |
| TestModeIsolation | 3 | 模式隔离性 |
| TestStartupFlowIntegration | 3 | 启动流程模拟 |

### Developer Mode 4 个场景

| 场景 | 输入 | 预期结果 |
|------|------|----------|
| License 文件不存在 | 无 license.key | 启动成功（跳过校验） |
| License 文件损坏 | 无效 JSON | 启动成功（跳过校验） |
| License 文件为空 | 空文件 | 启动成功（跳过校验） |
| License 文件正常 | 有效 license.key | 启动成功（跳过校验） |

### 运行测试

```powershell
# 仅运行 Developer Mode 测试
python -m pytest repair_app/tests/test_developer_mode.py -v

# 运行全部测试
.\run_all_tests.ps1 -Quick
```

---

## 8. 打包说明

`repair_app.spec` 已将 `config/app_config.json` 加入打包资源：

```python
# 应用级配置（Developer Mode 开关等，从 _MEIPASS 只读加载）
(str(PROJECT_DIR / 'config' / 'app_config.json'), 'config'),
```

打包后，`app_config.json` 从 `_MEIPASS/config/` 只读加载（与 `public_key.pem` 相同的安全策略）。

**注意**：打包发布商业版前，必须将 `config/app_config.json` 中的 `developer_mode` 设为 `false`。

---

## 9. 修改文件清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `config/app_config.json` | 新建 | Developer Mode 配置文件 |
| `repair_app/utils/app_config.py` | 新建 | AppConfig 统一配置入口 |
| `repair_app/utils/license_manager.py` | 修改 | 新增 LicenseStatus 类 + verify_runtime() 方法 |
| `run_app.py` | 修改 | 启动流程改用 verify_runtime() + Developer Mode 横幅日志 |
| `repair_app/ui/main_window.py` | 修改 | 标题栏追加 Developer Build + 状态栏 Developer Mode 标识 |
| `repair_app.spec` | 修改 | datas 新增 app_config.json + hiddenimports 新增 app_config |
| `repair_app/tests/test_developer_mode.py` | 新建 | 28 项 Developer Mode 测试 |

---

*本文档由 Developer Mode 实现流程生成。日期：2026-07-15。*
