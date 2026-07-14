# 兼容性检查清单

在每次发布前验证跨平台兼容性。

## Windows 10 兼容性

- [ ] 应用程序在 Windows 10 (1903+) 上无错误启动
- [ ] ZMQ 传输使用 `tcp://127.0.0.1:5555`（而非 `ipc://`）
- [ ] 中日韩字体渲染正确（Microsoft YaHei）
- [ ] 包含中文字符的文件路径不会导致崩溃
- [ ] Visual C++ Runtime 2015-2022 已捆绑或可用
- [ ] PyInstaller 可执行文件可在纯净的 Windows 10 虚拟机上运行（未安装 Python）
- [ ] 无硬编码的 POSIX 专用路径（`/tmp/`、`/usr/` 等）
- [ ] Windows 文件对话框可用于点云导入
- [ ] G-code 导出写入用户可访问的目录
- [ ] 使用 reportlab 生成 PDF 报告功能正常
- [ ] 许可证管理器通过 `uuid.getnode()` + `platform.node()` 读取机器 ID
- [ ] 线程关闭使用 `requestInterruption()`（而非 `terminate()`）

## Windows 11 兼容性

- [ ] 应用程序在 Windows 11 上无错误启动
- [ ] 高 DPI 缩放渲染正确（Qt `AA_EnableHighDpiScaling`）
- [ ] 窗口控件（最小化/最大化/关闭）功能正常
- [ ] 任务栏图标显示正确
- [ ] 深色模式/浅色模式不会导致渲染问题
- [ ] Windows Security / Defender 不会标记该可执行文件
- [ ] 所有 Windows 10 检查项在 Windows 11 上均通过

## macOS 兼容性

- [ ] 应用程序在 macOS 10.14+ 上无错误启动
- [ ] ZMQ 传输使用 `ipc:///tmp/csam_engine`（Unix 域套接字）
- [ ] 中日韩字体渲染正确（PingFang SC）
- [ ] `.app` 包结构有效（`Contents/MacOS/`、`Contents/Resources/`）
- [ ] `Info.plist` 包含 `CFBundleIdentifier`、`CFBundleShortVersionString`、`LSMinimumSystemVersion`
- [ ] `Info.plist` 中 `NSHighResolutionCapable` 设置为 `True`
- [ ] 应用程序可通过 Rosetta 或原生方式在 Apple Silicon (M1/M2/M3) 上运行
- [ ] 应用程序可在 Intel x86_64 上运行
- [ ] Gatekeeper 不会阻止启动（分发需要代码签名）
- [ ] macOS 文件对话框可用于点云导入
- [ ] 线程关闭使用协作式中断模式正常工作
- [ ] 无平台守卫缺失的情况下调用 Windows 专用 API

## 跨平台功能一致性

- [ ] 点云加载（CSV/TXT/XYZ/ASC）在所有平台上均正常工作
- [ ] 3D 可视化（matplotlib）在所有平台上均正常渲染
- [ ] 缺陷选择（矩形/自由手绘/画笔）在所有平台上均正常工作
- [ ] 路径规划在所有平台上产生相同结果
- [ ] 形貌预测在所有平台上产生相同结果
- [ ] G-code 导出在所有平台上产生相同输出
- [ ] PDF 报告生成在所有平台上产生相同输出
- [ ] 许可证验证在所有平台上均正常工作
- [ ] 日志记录在所有平台上均正常工作（文件轮转、控制台输出）
- [ ] 配置加载在所有平台上均正常工作（`config/` 目录解析）

## Python 版本兼容性

- [ ] Python 3.10 — 全部 145 个测试通过
- [ ] Python 3.11 — 全部 145 个测试通过
- [ ] Python 3.12 — 全部 145 个测试通过
- [ ] 未使用已弃用的 API（检查测试输出中的 `DeprecationWarning`）
- [ ] `pyproject.toml` 中 `requires-python` 设置为 `>=3.10`

## 依赖兼容性

- [ ] numpy >= 1.21 — 导入和操作正常
- [ ] scipy >= 1.7 — KDTree、插值、SVD 正常
- [ ] PySide6 >= 6.4 — Qt 控件、OpenGL 控件渲染正常
- [ ] matplotlib >= 3.5 — QtAgg 后端正常
- [ ] pyzmq >= 24 — ZMQ 上下文、套接字、轮询正常
- [ ] protobuf >= 5.26 — `runtime_version` 导入成功
- [ ] reportlab >= 4.0 — PDF 生成正常
- [ ] cryptography >= 41.0 — RSA 密钥加载和验证正常
- [ ] shapely >= 1.8 — 几何操作正常
