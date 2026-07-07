# CSAM Repair — 架构文档

## 概述

CSAM Repair 是一款跨平台（macOS、Windows、Linux）桌面应用，用于冷喷涂增材制造缺陷修复。基于 PySide6（Qt for Python）构建，提供交互式 3D 可视化工作流，涵盖点云处理、路径规划、形貌预测和工业导出。

## 分层架构

```
┌─────────────────────────────────────────────┐
│  表现层（UI）                                 │
│  repair_app/ui/                              │
│  - MainWindow、RepairVisualizer、            │
│    DefectSelector、Workers                   │
├─────────────────────────────────────────────┤
│  控制器层                                     │
│  repair_app/controller/                      │
│  - AppController、WorkflowController         │
├─────────────────────────────────────────────┤
│  服务层（业务逻辑）                            │
│  repair_app/service/                         │
│  - CoordinationService、FileService、         │
│    ExportService、RepairEngineService        │
├─────────────────────────────────────────────┤
│  领域层（模型与接口）                          │
│  repair_app/domain/                          │
│  - PointCloud、DefectRegion、ProcessParams   │
│  - IEngine、IPathPlanner、IMorphologyPredictor│
├─────────────────────────────────────────────┤
│  引擎层                                       │
│  repair_app/engine/                          │
│  - LocalEngine（Python 实现）                 │
├─────────────────────────────────────────────┤
│  核心层（算法）                                │
│  repair_app/core/                            │
│  - PathPlanner、MorphologyPredictor、         │
│    FeasibilityChecker、MaterialDatabase      │
├─────────────────────────────────────────────┤
│  基础设施层                                    │
│  repair_app/repository/  （数据访问）          │
│  repair_app/communication/（ZMQ/Protobuf）    │
│  repair_app/platform/    （操作系统抽象）       │
│  repair_app/export/      （G-code、PDF）      │
└─────────────────────────────────────────────┘
```

## 模块职责

### `repair_app/ui/`
- 基于 PySide6 的 Qt 图形界面
- 使用 matplotlib 进行 3D 可视化
- 交互式缺陷选取（套索、画笔、矩形）
- 逐层动画播放
- 暗色主题 QSS 样式表

### `repair_app/controller/`
- 应用状态管理
- 工作流协调（当前由 MainWindow 承担）
- 说明：AppController 和 WorkflowController 已作为死代码移除

### `repair_app/service/`
- **CoordinationService**：中介 UI ↔ core/communication 的访问
- **FileService**：点云加载、路径点持久化
- **ExportService**：G-code 和 PDF 导出编排
- **RepairEngineService**：引擎生命周期管理

### `repair_app/domain/`
- **models.py**：核心数据结构（PointCloud、DefectRegion、ProcessParams、Waypoint、RepairResult）
- **interfaces.py**：抽象基类（IEngine、IPathPlanner、IMorphologyPredictor）

### `repair_app/engine/`
- **LocalEngine**：Python 原型，封装核心算法
- 设计用于未来替换为 MATLAB ZMQ 引擎

### `repair_app/core/`
- **path_planner.py**：逐层光栅路径生成
- **morphology_predictor.py**：沉积形貌模拟
- **feasibility_checker.py**：参数可行性分析
- **material_database.py**：材料属性查询
- **defect_sample.py**：合成缺陷生成
- **normal_estimator.py**：点云法向量估计
- **stl_reader.py**：STL 文件解析

### `repair_app/communication/`
- **zmq_client.py**：用于 MATLAB 引擎的 ZMQ REQ/REP 客户端
- **repair_serialization.py**：Protobuf 请求/响应序列化
- **repair_protocol_pb2.py**：生成的 Protobuf 绑定

### `repair_app/platform/`
- **__init__.py**：操作系统检测（is_windows、is_macos、is_linux）
- **transport.py**：平台感知的 ZMQ 传输选择
- **fonts.py**：matplotlib/reportlab 的 CJK 字体解析

### `repair_app/export/`
- **gcode_exporter.py**：工业级 G-code 生成
- **robot_exporter.py**：KUKA KRL / ABB Rapid 代码生成
- **report_generator.py**：PDF 修复报告生成
- **export_validator.py**：刀具路径验证与安全检查

### `repair_app/utils/`
- **config.py**：集中配置（唯一数据源）
- **logger_config.py**：结构化日志（loguru，带标准库回退）
- **license_manager.py**：RSA-2048 许可证验证
- **crash_handler.py**：全局异常钩子
- **auto_updater.py**：通过 GitHub API 检查版本更新
- **resource_path.py**：PyInstaller 资源路径解析
- **calibration_wizard.py**：单道沉积标定向导
- **lod.py**：LOD 点云管理
- **look_up.py**：CFD 查找表工具

### `repair_app/validation/`
- **validator.py**：科学验证流水线
- **metrics.py**：定量指标计算
- **dataset.py**：验证数据集管理
- **experiment.py**：实验跟踪
- **result_manager.py**：结果持久化

### `repair_app/repository/`
- **file_repository.py**：文件 I/O 抽象
- **material_repository.py**：材料数据访问

## 数据流

```
点云（CSV/TXT/XYZ）
  → FileService.load_point_cloud()
  → DefectSelector（交互式选取）
  → PathPlanningWorker（QThread）
    → PathPlanner（核心算法）
    → Waypoints（ndarray）
  → MorphologyWorker（QThread）
    → MorphologyPredictor（核心算法）
    → Repair points（ndarray）
  → ExportService
    → G-code（.nc）或 PDF 报告
```

## 关键设计决策

1. **CoordinationService 模式**：UI 层绝不直接导入 core/communication 模块
2. **引擎抽象**：IEngine 接口支持在本地 Python ↔ MATLAB ZMQ 之间切换
3. **领域模型**：类型化数据类（PointCloud、ProcessParams）替代分散的字典
4. **单一配置来源**：`config.py` 的 PARAM_SPECS 定义所有参数边界
5. **Loguru 带回退**：结构化日志优雅降级为标准库日志
6. **平台抽象**：所有操作系统相关代码隔离在 `repair_app/platform/` 中

## 跨平台说明

- ZMQ：Windows 使用 `tcp://`，POSIX 使用 `ipc://`
- 字体：`platform/fonts.py` 中按平台选择 CJK 字体路径
- 路径：全局使用 `Path` 对象，`resource_path.py` 用于 PyInstaller 兼容
- 打包：单一 PyInstaller spec，按平台条件使用 BUNDLE（macOS .app）

## 已知技术债务

1. MainWindow 直接协调工作流（Controller 层较薄）
2. 无 MATLAB 引擎 ZMQ 实现
3. UI 面板（LeftPanel、RightPanel、HeaderPanel）尚未集成
4. main_window.py 中存在部分长函数（超过 100 行）
5. 11 个模块零测试覆盖率