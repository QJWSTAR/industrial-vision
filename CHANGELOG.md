# 变更日志

本项目所有重要变更都将记录在此文件中。

本文件格式基于 [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)，
本项目遵循 [语义化版本](https://semver.org/spec/v2.0.0.html)。

## [1.0.0] — 2026-07-03

### 新增
- 6 层清晰架构（Domain、Engine、Repository、Service、Controller、UI Panels）
- IEngine 抽象，包含 IPathPlanner 和 IMorphologyPredictor 接口
- LocalEngine 封装 Python 原生的 path_planner 和 morphology_predictor
- ZMQ + Protobuf 通信层，用于 MATLAB 服务器集成
- RSA-2048 许可证管理，带 HMAC 回退
- 科学验证流水线（指标、验证器、数据集/实验管理）
- loguru 日志，支持结构化 JSON 输出和按日期轮转
- 崩溃处理器，带全局异常钩子
- 自动更新器，通过 GitHub Releases 进行 semver 比较
- LOD（细节层次）管理器，用于点云可视化
- 性能分析和基准测试工具
- 基于 GitHub Actions 的 CI/CD（多操作系统、多 Python 版本）
- pre-commit 钩子（flake8、bandit、trailing-whitespace 等）

### 变更
- 形貌预测：通过 KDTree + 路径点稀疏化实现 125 倍加速
- 参数定义集中在 config.py 中作为唯一数据源
- HMAC 密钥从硬编码改为环境变量
- 点云序列化：JSON 格式替代 allow_pickle=True 的 np.savez/np.load
- 随机数生成：统一使用 np.random.randint

### 修复
- np.savez/np.load（allow_pickle=True）中的代码注入漏洞
- 静默错误吞没（try-except-pass）替换为正确的日志记录
- config.py、main_window.py、pyproject.toml 之间的版本不一致
- 5 个因 sys.path 导入问题导致的测试失败
- left_panel.py 和 validation_service.py 之间的参数边界重复
- 死代码移除：exceptions.py（12 个未使用的异常类）

### 技术债务（已知）
- UI 层直接导入 core/algorithm 模块（main_window.py）— 见 CTO 评审报告高优先级 #5
- 新的 UI 面板（LeftPanel、RightPanel、HeaderPanel）尚未集成到 main_window.py
- MATLAB 算法依赖尚未完全迁移到 Python
- 无插件/AI/ML 能力

## [1.0.1] — 2026-07-07

### 新增
- LICENSE（MIT）
- CONTRIBUTING.md（贡献指南、代码风格、提交规范）
- ARCHITECTURE.md（架构文档、模块职责、数据流）
- GitHub Issue 模板（Bug Report、Feature Request）
- GitHub Pull Request 模板

### 变更
- calibration_wizard.py 从根目录迁移至 repair_app/utils/
- robot_exporter.py 从根目录迁移至 repair_app/export/
- 更新对应模块的导入路径（main_window.py、test_stage5.py、repair_app.spec）

### 修复
- repair_engine_service.py：print 改为 logger.info
- report_generator.py：print 改为 logger.warning
- calibration_wizard.py：_log_warning 改为 logger.warning

### 移除
- 备份文件：repair_visualizer.py.bak、main_window.py.bak
- 调试脚本：debug_demo_files.py
- 生成物：repair_report.pdf、_preview*.png、demo_screenshot.png、defect_3d_viewer.html
- 缓存目录：__pycache__/、.pytest_cache/、.matplotlib_cache/、.trae-html-share-packages/
- 开发报告：tech-debt-fix-report/、release-summary/、migration-plan/、technical-audit-report/
- 根目录临时文件：PDF 论文、HTML 开发计划、重构报告、README_ENGINE.md
- 鸡蛋信息：csam_repair.egg-info/、UNKNOWN.egg-info/

### 改进
- .gitignore 增强：覆盖生成物、缓存、IDE 文件、pytest 产物
- 所有 199 项测试通过，无回归
