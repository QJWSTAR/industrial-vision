# 部署检查清单

在部署前验证生产就绪状态。

## 构建前验证

- [ ] 全部 145 个测试通过（`pytest --tb=short -q`）
- [ ] 测试覆盖率 >= 60%（`pytest --cov=repair_app --cov-report=term-missing`）
- [ ] 测试输出中无 `DeprecationWarning` 或 `PendingDeprecationWarning`
- [ ] `flake8 repair_app/ --count --max-complexity=15` 报告零错误
- [ ] `bandit -r repair_app/ -x repair_app/tests/ -ll` 报告零高严重性问题
- [ ] `pre-commit run --all-files` 通过
- [ ] 生产代码路径中无 `# TODO` 或 `# FIXME` 注释（已记录的技术债务可接受）
- [ ] 版本号在 `config.py`、`pyproject.toml`、`repair_app.spec` 中保持一致
- [ ] `CHANGELOG.md` 已更新发布说明
- [ ] Git 工作树是干净的（`git status` 显示无未提交更改）

## 环境配置

- [ ] `.env.example` 已更新包含所有环境变量
- [ ] 生产环境中已设置 `CSAM_HMAC_SECRET`（未使用开发回退值）
- [ ] 如需非默认地址，已配置 `CSAM_ZMQ_ADDRESS`
- [ ] 生产环境中 `CSAM_LOG_LEVEL` 设置为 `INFO` 或 `WARNING`
- [ ] `config/license.key` 和 `config/public_key.pem` 已存在（如启用了许可证强制验证）
- [ ] `config/calibration_db.json` 已存在且有效
- [ ] `repair_app/core/material_db.json` 已存在且有效

## 构建过程

### Windows 构建
- [ ] 构建机器已安装 Python 3.10+ 和 pip
- [ ] `pip install -r requirements.txt` 成功
- [ ] `pip install pyinstaller` 成功
- [ ] `python -c "import PySide6, zmq, google.protobuf, numpy, matplotlib, reportlab, cryptography"` 成功
- [ ] `build_windows.bat` 无错误完成
- [ ] `dist/CSAM_Repair.exe` 已创建
- [ ] 可执行文件大小合理（预期 100-300 MB）
- [ ] 图标已嵌入可执行文件（如 `p1.ico` 存在）

### macOS 构建
- [ ] 构建机器已安装 Python 3.10+ 和 pip
- [ ] `pip install -r requirements.txt` 成功
- [ ] `pip install pyinstaller` 成功
- [ ] 模块验证命令成功
- [ ] `bash build_macos.sh` 无错误完成
- [ ] `dist/CSAM_Repair.app` 已创建
- [ ] `Info.plist` 包含有效元数据
- [ ] 图标已嵌入 `.app` 包

## 纯净机器测试

- [ ] 可执行文件可在纯净的 Windows 10 虚拟机上运行（无 Python、无开发工具）
- [ ] 可执行文件可在纯净的 Windows 11 虚拟机上运行
- [ ] 可执行文件可在纯净的 macOS 上运行（无 Python、无开发工具）
- [ ] 应用程序在 30 秒内启动
- [ ] 无缺失 DLL 或框架错误
- [ ] 无防火墙或杀毒软件提示（或提示为预期内并已记录）

## 代码签名（macOS）

- [ ] Developer ID Application 证书可用
- [ ] `codesign --deep --force --sign "Developer ID Application: ..."` 成功
- [ ] `codesign --verify --verbose=4` 确认签名有效
- [ ] 已通过 `xcrun notarytool submit` 提交公证
- [ ] 公证状态为 "Accepted"
- [ ] `xcrun stapler staple` 成功
- [ ] `spctl --assess --verbose=4` 确认 Gatekeeper 批准

## 分发打包

### Windows
- [ ] Inno Setup 或 NSIS 安装程序脚本已配置
- [ ] 安装程序包含可执行文件、配置文件和图标
- [ ] 安装程序创建开始菜单和桌面快捷方式
- [ ] 安装程序包含卸载程序
- [ ] 安装程序已在纯净虚拟机上测试

### macOS
- [ ] 通过 `hdiutil create` 创建 DMG
- [ ] DMG 卷名称为 "CSAM Repair"
- [ ] DMG 使用 UDZO 压缩
- [ ] DMG 已进行代码签名和公证
- [ ] DMG 可挂载且应用程序可拖拽到 Applications

## 发布产物

- [ ] Windows 可执行文件或安装程序已上传至 GitHub Releases
- [ ] macOS DMG 已上传至 GitHub Releases
- [ ] GitHub Releases 中已编写发布说明
- [ ] Git 标签已推送（`git tag v1.0.0 && git push origin v1.0.0`）
- [ ] `CHANGELOG.md` 版本部分与发布标签匹配

## 部署后验证

- [ ] 下载链接可访问
- [ ] 下载的文件未损坏（校验和已验证）
- [ ] 最终用户可在 Windows 10 上安装并启动
- [ ] 最终用户可在 Windows 11 上安装并启动
- [ ] 最终用户可在 macOS 上安装并启动
- [ ] 演示数据加载并渲染正确
- [ ] G-code 导出生成有效输出
- [ ] PDF 报告导出生成有效输出
