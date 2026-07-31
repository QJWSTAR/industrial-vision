# Windows 与 MATLAB R2025b 稳定性验收手册

> 版本：1.1.0 | 协议：v2.1（请求/结果）+ v3.0（实时事件） | 更新日期：2026-07-29 | 文档语言：简体中文

---

## 目录

- [1. 文档目的与发布门槛](#1-文档目的与发布门槛)
- [2. 被测系统与通信契约](#2-被测系统与通信契约)
- [3. 测试环境要求](#3-测试环境要求)
- [4. 建立证据目录与测试记录](#4-建立证据目录与测试记录)
- [5. 获取候选版本](#5-获取候选版本)
- [6. 配置并验证 Python 环境](#6-配置并验证-python-环境)
- [7. 端口与进程预检查](#7-端口与进程预检查)
- [8. MATLAB R2025b 与 Python 互操作预检查](#8-matlab-r2025b-与-python-互操作预检查)
- [9. 验证取消注册表与实时发布接口](#9-验证取消注册表与实时发布接口)
- [10. MATLAB 路径规划冒烟测试](#10-matlab-路径规划冒烟测试)
- [11. MATLAB 形貌预测冒烟测试](#11-matlab-形貌预测冒烟测试)
- [12. GUI 端到端实时动画验收](#12-gui-端到端实时动画验收)
- [13. 取消机制验收](#13-取消机制验收)
- [14. 错误恢复验收](#14-错误恢复验收)
- [15. 10 分钟稳定性与资源验收](#15-10-分钟稳定性与资源验收)
- [16. 退出清理验收](#16-退出清理验收)
- [17. 验收记录矩阵](#17-验收记录矩阵)
- [18. 最终判定规则](#18-最终判定规则)
- [19. 常见问题与恢复方法](#19-常见问题与恢复方法)

## 1. 文档目的与发布门槛

本手册用于在真实 Windows 工作站上验证以下目标是否成立：

1. MATLAB R2025b 完成路径规划和形貌预测计算。
2. Python GUI 在 MATLAB 计算过程中实时显示逐层路径和形貌动画。
3. 高频 mesh 消息不会无限堆积，GUI 不出现持续卡顿。
4. 用户可在路径规划或形貌预测阶段取消计算。
5. 端口冲突、MATLAB Worker 异常退出和通信超时能够被发现并恢复。
6. 一次任务结束或取消后，可以安全启动下一次任务。
7. 软件退出后，不遗留由本应用创建的线程、端口和 MATLAB Worker。

本手册是候选版本（Release Candidate，RC）的验收门槛，不是单纯的安装说明。

> **重要限制**
>
> Python 自动化测试通过，只能证明消息队列、状态机和错误处理逻辑满足代码层契约。只有本手册中的 MATLAB 互操作、真实几何计算、实时动画、取消、故障恢复和稳定性测试全部通过，才能将该版本判定为“Windows + MATLAB R2025b 稳定候选版”。

### 1.1 阻断项

以下任意一项未执行或失败，均不得宣称“稳定产品”：

- MATLAB `version('-release')` 不是 `2025b`。
- MATLAB 无法加载项目 `venv` 中的 Python。
- `logical(py.bool)` 转换失败。
- MATLAB 数组通过 `pyargs(...)` 传入 Python 发布器失败。
- 路径规划真实 STL 冒烟测试失败。
- 形貌预测真实 STL/Excel 冒烟测试失败。
- 路径阶段取消或形貌阶段取消失败。
- 取消后无法再次计算。
- GUI 出现持续超过 1 秒的冻结，或实时帧持续堆积。
- MATLAB Worker 异常退出后，应用无法恢复。
- 10 分钟稳定性测试未执行或失败。
- 退出后遗留监听端口、运行线程或由应用启动的 MATLAB Worker。

## 2. 被测系统与通信契约

### 2.1 通道分工

| 通道 | 默认地址 | ZeroMQ 模式 | 可靠性要求 | 用途 |
|------|----------|-------------|------------|------|
| 主请求通道 | `tcp://127.0.0.1:5555` | Python GUI REQ / Bridge REP | 请求-应答 | 健康检查、路径规划、形貌预测、最终结果 |
| 实时进度通道 | `tcp://127.0.0.1:5556` | Bridge PUB / GUI SUB | 按事件类型处理 | 路径层、形貌预览、层末关键帧、heartbeat、终止事件 |
| 取消控制通道 | `tcp://127.0.0.1:5557` | GUI REQ / Bridge REP | 请求-应答、幂等 | 独立发送取消请求和确认，不受主计算阻塞影响 |

三个端口必须由一套 Bridge 实例统一拥有。一个 GUI 进程中应只有：

- 一个 `ComputeController`；
- 一个长生命周期 `ProgressSubscriber`；
- 一个实时 SUB socket；
- 一个 MATLAB Bridge；
- 一个进度 PUB socket；
- 一个取消 REP socket。

REP socket（主请求通道与取消控制通道）已配置 `RCVTIMEO=100ms` 与 `SNDTIMEO=5000ms`，确保 `stop()` 能够在有限时间内中断阻塞的 `recv`/`send`，不会因客户端失联导致 Bridge 无法退出。PUB socket 维持 `LINGER=0`，关闭时不等待订阅者。

### 2.2 协议版本

- 主请求和最终结果继续兼容 Protobuf v2.1。
- 实时消息使用 v3 `ProgressEnvelope`。
- 取消控制使用 v3 `ControlRequest` / `ControlResponse`。
- 健康检查中的 `service_version` 和 `protocol_version` 是两个独立字段，不能将服务版本误判为协议版本。

### 2.3 实时数据策略

| 数据 | Bridge 发布策略 | GUI 消费策略 |
|------|-----------------|--------------|
| 路径层 | 每层可靠发布 | 按层号累积，不得丢层 |
| 形貌预览 | MATLAB 默认上限约 8 FPS，可降采样 | latest-frame-wins，旧预览允许被新预览覆盖 |
| 层末形貌 | 完整分辨率关键帧，可靠发布 | 必须显示并保留为该层最终状态 |
| heartbeat | 仅表示存活，不参与算法 payload 序号 | 更新存活时间，不得使排队路径层变成“过期” |
| terminal | COMPLETED / FAILED / CANCELLED 可靠发布 | 每任务只接受一个有效终态 |

GUI 默认每 200 ms 排空一次实时缓冲区，即渲染上限约 5 FPS。MATLAB 默认最多发布约 8 FPS。两端限帧的目的不是追求最高帧率，而是保证计算期间窗口仍可拖动、切页和取消。

## 3. 测试环境要求

### 3.1 必需环境

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 x64 或 Windows 11 x64，已安装最新稳定更新 |
| MATLAB | MATLAB R2025b 64 位完整安装 |
| Python | 3.10–3.12，推荐 3.11 或 3.12，64 位 |
| Git | 建议 2.40 或更高 |
| PowerShell | Windows PowerShell 5.1 或 PowerShell 7 |
| 内存 | 最低 16 GB，建议 32 GB |
| 显卡 | 支持当前 PySide6/Matplotlib 3D 渲染；更新到厂商稳定驱动 |
| 权限 | 可创建虚拟环境、监听本机 5555–5557 端口、启动 MATLAB |

### 3.2 MATLAB 工具箱

在 MATLAB 中运行：

```matlab
ver
```

保存完整输出。基础验证至少要求 MATLAB 本体可用；如果算法依赖的函数由额外工具箱提供，`which` 或真实计算会明确暴露缺失项。不得用捕获异常后静默跳过的方式将工具箱缺失标为通过。

### 3.3 测试数据

仓库内应存在：

```text
path_planning\part.stl
path_planning\substrate.stl
path_planning\target.stl
profile_prediction\part.stl
profile_prediction\substrate-surface.xlsx
```

这些文件是本手册的固定冒烟输入。正式项目数据可作为附加验证，但不能替代固定输入。

## 4. 建立证据目录与测试记录

在 PowerShell 中进入预定工作目录，创建本次验收的唯一证据目录：

```powershell
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$Evidence = Join-Path (Get-Location) "artifacts\windows-r2025b\$Stamp"
New-Item -ItemType Directory -Force -Path $Evidence | Out-Null
Start-Transcript -Path (Join-Path $Evidence "powershell-transcript.txt")
$Evidence
```

预期结果：

- PowerShell 输出一个绝对路径。
- 目录中出现 `powershell-transcript.txt`。
- 后续所有命令都在同一个 transcript 中。

建议最终证据至少包含：

```text
artifacts\windows-r2025b\<timestamp>\
├── powershell-transcript.txt
├── environment.txt
├── git-head.txt
├── python-realtime-tests.txt
├── python-full-tests.txt
├── matlab-version.txt
├── matlab-preflight.txt
├── matlab-path-smoke.txt
├── matlab-topography-smoke.txt
├── ports-before.txt
├── ports-running.txt
├── ports-after.txt
├── process-samples.csv
├── app-log.txt
├── screenshots\
└── acceptance-matrix.md
```

截图至少包括：

- MATLAB R2025b 版本与 `pyenv`；
- 路径逐层显示；
- 形貌动画中间帧；
- 层末完整形貌；
- 路径阶段取消结果；
- 形貌阶段取消结果；
- 故障提示和恢复结果；
- 成功任务的最终结果页。

## 5. 获取候选版本

### 5.1 全新克隆

```powershell
git clone https://github.com/QJWSTAR/industrial-vision.git
Set-Location industrial-vision
git fetch --all --prune
git switch codex/stable-realtime-pipeline
```

如果验收的是 PR，请使用 PR 页面给出的分支名或精确 commit SHA 替换上面的分支。

### 5.2 固化版本证据

```powershell
git status --short
git branch --show-current
git rev-parse HEAD | Tee-Object -FilePath (Join-Path $Evidence "git-head.txt")
git log -1 --oneline
```

预期结果：

- 当前分支为待验收分支。
- `git status --short` 没有输出。
- `git-head.txt` 中保存 40 位 commit SHA。
- 后续测试期间不得切换 commit 或修改源码；若修改，必须重新开始验收并建立新证据目录。

## 6. 配置并验证 Python 环境

### 6.1 检查版本

```powershell
py -0p
py -3.11 --version
git --version
& "C:\Program Files\MATLAB\R2025b\bin\matlab.exe" -batch "disp(version); disp(version('-release'))"
```

如果未安装 Python 3.11，可将本手册中的 `py -3.11` 替换为已安装的 3.10 或 3.12。

预期结果：

- Python 是 64 位 CPython 3.10–3.12。
- MATLAB 输出版本信息，release 精确为 `2025b`。

将环境信息保存为证据：

```powershell
@(
    "Date: $(Get-Date -Format o)"
    "Windows: $((Get-CimInstance Win32_OperatingSystem).Caption)"
    "WindowsVersion: $((Get-CimInstance Win32_OperatingSystem).Version)"
    "PowerShell: $($PSVersionTable.PSVersion)"
    "PythonLauncher:"
    (py -0p 2>&1 | Out-String)
    "Git:"
    (git --version 2>&1 | Out-String)
) | Set-Content -Encoding UTF8 (Join-Path $Evidence "environment.txt")
```

### 6.2 创建固定名称的虚拟环境

```powershell
py -3.11 -m venv venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,full]"
```

> 虚拟环境必须命名为 `venv`。`matlab_bridge_server.m` 会优先查找项目根目录下的 `venv\Scripts\python.exe`。改成 `.venv` 或其他名称会使自动启动的 Bridge 使用错误的 Python。

预期结果：

- PowerShell 提示符出现 `(venv)`。
- 安装命令退出码为 0。
- 没有依赖解析冲突。

### 6.3 设置本次 PowerShell 会话的运行参数

```powershell
$env:CSAM_DEVELOPER_MODE = "true"
$env:CSAM_ALGORITHM_ENGINE = "matlab"
$env:CSAM_MATLAB_EXE = "C:\Program Files\MATLAB\R2025b\bin\matlab.exe"
$env:CSAM_ZMQ_ADDRESS = "tcp://127.0.0.1:5555"
$env:CSAM_ZMQ_PROGRESS_ADDRESS = "tcp://127.0.0.1:5556"
$env:CSAM_ZMQ_CONTROL_ADDRESS = "tcp://127.0.0.1:5557"
```

`CSAM_DEVELOPER_MODE=true` 只用于绕过测试工作站上的许可证校验，不是生产配置。正式发布验收还应在有效许可证下补跑一次 GUI 启动。

### 6.4 导入检查

```powershell
python -c "import sys, numpy, PySide6, zmq, google.protobuf; print(sys.version); print(sys.executable); print(numpy.__version__); print(PySide6.__version__); print(zmq.__version__); print(google.protobuf.__version__)"
python -c "from repair_app.bridge.operation_control import CancellationControlServer; from repair_app.bridge.progress_publisher import ProgressPublisher; from repair_app.ui.compute_controller import ComputeController; from repair_app.ui.progress_subscriber import ProgressSubscriber; print('imports: OK')"
```

预期结果：

- `sys.executable` 指向当前仓库的 `venv\Scripts\python.exe`。
- 所有依赖版本均能输出。
- 最后一行是 `imports: OK`。
- 没有 DLL 加载失败、Protobuf 版本错误或 Qt platform plugin 错误。

### 6.5 稳定性专项测试

```powershell
python -m pytest repair_app\tests\test_realtime_stability.py -q 2>&1 |
    Tee-Object -FilePath (Join-Path $Evidence "python-realtime-tests.txt")
```

预期结果：

- 11 项测试全部通过。
- 0 failures。
- 覆盖 latest-frame-wins、路径层可靠累积、heartbeat 序号、唯一终态、取消幂等、线程停止和背压边界。

### 6.6 完整 Python 测试

```powershell
python -m pytest 2>&1 |
    Tee-Object -FilePath (Join-Path $Evidence "python-full-tests.txt")
```

预期结果：

- 退出码为 0。
- 0 failures、0 errors。
- Windows 因平台条件产生的 skip 数可能与其他系统不同，因此不要将总 passed/skip 数硬编码为唯一标准。
- 当前非 MATLAB 开发机基线为 `2468 passed, 3 skipped, 0 failed`；Windows 的核心判定仍是 0 failures。

## 7. 端口与进程预检查

关闭所有可能运行的旧版 GUI 和 Bridge，然后执行：

```powershell
Get-NetTCPConnection -LocalPort 5555,5556,5557 -State Listen -ErrorAction SilentlyContinue |
    Sort-Object LocalPort |
    Format-Table -AutoSize |
    Out-String |
    Tee-Object -FilePath (Join-Path $Evidence "ports-before.txt")
```

预期结果：

- 全新测试开始前没有 5555、5556、5557 的监听记录。

如果有监听记录，定位所属进程：

```powershell
Get-NetTCPConnection -LocalPort 5555,5556,5557 -State Listen -ErrorAction SilentlyContinue |
    ForEach-Object {
        Get-Process -Id $_.OwningProcess |
            Select-Object Id, ProcessName, Path
    }
```

不要直接运行按进程名批量结束 MATLAB 的命令。先确认 PID 是否属于本次测试；手工 MATLAB 会话和其他项目的 MATLAB 进程不得被强制关闭。

## 8. MATLAB R2025b 与 Python 互操作预检查

### 8.1 启动全新 MATLAB 会话

从开始菜单启动 **MATLAB R2025b**。不要复用已经加载过其他 Python 解释器的 MATLAB 会话。

在命令窗口执行以下代码，将 `root` 改成仓库绝对路径：

```matlab
version
version('-release')
root = 'D:\work\industrial-vision';
cd(root);

pe = pyenv;
if pe.Status ~= "NotLoaded" && ...
        ~strcmpi(char(pe.Version), fullfile(root, 'venv', 'Scripts', 'python.exe'))
    error(['MATLAB 已加载其他 Python。请关闭 MATLAB，重新启动后再执行本节。', ...
           ' 当前 Python: ', char(pe.Version)]);
end

pyenv('Version', fullfile(root, 'venv', 'Scripts', 'python.exe'), ...
      'ExecutionMode', 'InProcess');
pe = pyenv

addpath(fullfile(root, 'path_planning'));
addpath(fullfile(root, 'profile_prediction'));

which run_path_planning
which run_profile_prediction

py.importlib.import_module('repair_app.bridge.operation_control');
py.importlib.import_module('repair_app.bridge.progress_publisher');
disp('MATLAB-Python preflight: OK');
```

预期结果：

- `version('-release')` 返回 `2025b`。
- `pe.Version` 指向当前仓库的 `venv\Scripts\python.exe`。
- `pe.ExecutionMode` 为 `InProcess`。
- `run_path_planning` 和 `run_profile_prediction` 均解析到当前仓库下的 `.m` 文件。
- 两个 Python 模块导入无异常。
- 最后一行是 `MATLAB-Python preflight: OK`。

若 `venv\Scripts\python.exe` 不存在，`matlab_bridge_server.m` 会输出明确警告 `WARNING: venv not found. Using system Python.` 并提示如何创建虚拟环境。此时 Bridge 仍会尝试用系统 Python 启动，但通常因缺少 `repair_app` 依赖而失败，必须先按第 6.2 节创建 `venv` 再重试。

Bridge 启动后，`MatlabEngineProxy` 在 pyenv 宿主模式下按以下三级递进策略连接 MATLAB 引擎，确保任一层失败都能自动降级到下一层：

1. `connect_matlab()`（无参数）—— 连接当前宿主 MATLAB 会话，最轻量；
2. `connect_matlab(sharedName)` —— 按名称 `matlab_bridge` 连接共享会话；
3. `start_matlab(background=True)` —— 启动后台引擎会话，作为兜底（耗时较长）。

外部模式（Python 不在 MATLAB 进程内）则依次尝试 `find_matlab` + 按名称连接、默认共享会话、独立启动（仅 `CSAM_ALGORITHM_ENGINE=matlab` 时）。全部失败时抛出 `EngineUnavailableError`，由上层降级或报错。

将 MATLAB 命令窗口输出复制到：

```text
artifacts\windows-r2025b\<timestamp>\matlab-preflight.txt
```

同时保存 MATLAB 版本输出到 `matlab-version.txt`。

### 8.2 检查测试输入

```matlab
required_files = {
    fullfile(root, 'path_planning', 'part.stl')
    fullfile(root, 'path_planning', 'substrate.stl')
    fullfile(root, 'path_planning', 'target.stl')
    fullfile(root, 'profile_prediction', 'part.stl')
    fullfile(root, 'profile_prediction', 'substrate-surface.xlsx')
};
for i = 1:numel(required_files)
    assert(isfile(required_files{i}), "Missing test file: " + required_files{i});
    fprintf('FOUND %s\n', required_files{i});
end
```

预期结果：

- 输出 5 行 `FOUND ...`。
- 没有 assertion error。

## 9. 验证取消注册表与实时发布接口

这些检查专门覆盖 MATLAB R2025b 与嵌入式 Python 之间最容易发生兼容问题的边界，不能用 Python 单元测试替代。

### 9.1 `logical(py.bool)` 转换

在同一个全新 MATLAB 会话中执行：

```matlab
op = ['op_', lower(dec2hex(randi(2^52)))];  % MATLAB-native UUID, no JVM needed
py.repair_app.bridge.operation_control.begin_operation(op);
tf = logical(py.repair_app.bridge.operation_control.is_cancel_requested(op));
assert(~tf, 'New operation must not be cancelled');
py.repair_app.bridge.operation_control.finish_operation(op, 'completed');
disp('logical(py.bool): OK');
```

预期结果：

- `tf` 是 MATLAB logical，值为 `false`。
- 没有类型转换异常。
- 最后一行是 `logical(py.bool): OK`。

### 9.2 MATLAB 数组、`pyargs` 和 logical 互操作

确保 GUI 和其他 Bridge 尚未运行，然后执行：

```matlab
publisher = py.repair_app.bridge.progress_publisher.ProgressPublisher.get_instance();
started = logical(publisher.start());
assert(started, 'ProgressPublisher failed to bind tcp://127.0.0.1:5556');

op = ['op_', lower(dec2hex(randi(2^52)))];  % MATLAB-native UUID, no JVM needed
publisher.begin_operation(op);

mesh = [
    0, 0, 0,  1, 0, 0,  0, 1, 0
    0, 0, 1,  1, 0, 1,  0, 1, 1
];

publisher.publish_progress(pyargs( ...
    'request_id', op, ...
    'stage', int32(3), ...
    'event_type', int32(2), ...
    'mesh_frame_kind', int32(2), ...
    'layer_index', int32(1), ...
    'total_layers', int32(1), ...
    'progress', double(1.0), ...
    'message', 'R2025b interop smoke', ...
    'mesh_triangles', mesh, ...
    'reliable', logical(true)));

pause(0.2);
publisher.finish_operation(op);
stopped = logical(publisher.stop());
assert(stopped, 'ProgressPublisher did not stop cleanly');
disp('MATLAB array + pyargs + logical: OK');
```

预期结果：

- `publisher.start()` 返回 true。
- MATLAB `2×9 double` 数组被 Python/Numpy 接受。
- `logical(true)` 被 Python 参数处理接受。
- 无 `TypeError`、NumPy 转换错误或 `CSAM:ProgressPublishFailed`。
- 5556 在 `publisher.stop()` 后释放。
- 最后一行是 `MATLAB array + pyargs + logical: OK`。

如果本节失败，记录完整 MATLAB stack trace，不得继续将实时动画标为通过。

## 10. MATLAB 路径规划冒烟测试

在 MATLAB 中执行：

```matlab
params = struct;
params.request_id = '';

path_stl = fullfile(root, 'path_planning', 'part.stl');
t_path = tic;
[p, feed, layers, meta] = run_path_planning(path_stl, params);
path_elapsed = toc(t_path);

assert(~isempty(p), 'Path output is empty');
assert(size(p, 2) >= 6, 'Path output must contain xyz + normal');
assert(size(feed, 1) == size(p, 1), 'Feed count mismatch');
assert(size(layers, 1) == size(p, 1), 'Layer count mismatch');
assert(all(isfinite(p), 'all'), 'Path contains NaN/Inf');
assert(all(isfinite(feed), 'all'), 'Feed contains NaN/Inf');
assert(all(isfinite(layers), 'all'), 'Layers contain NaN/Inf');
assert(all(feed >= 0), 'Feed contains negative value');
assert(min(layers) >= 1, 'Layer index must start from 1');
assert(double(meta.waypoint_count) == size(p, 1), 'Metadata waypoint mismatch');
assert(double(meta.layer_count) == max(layers), 'Metadata layer mismatch');

fprintf('PATH_SMOKE_PASS waypoints=%d layers=%d elapsed=%.3fs\n', ...
        size(p, 1), max(layers), path_elapsed);
```

预期结果：

- 输出非空 `M×6` 或更多列的航点矩阵。
- feed 和 layer 数量与航点一致。
- 航点、速度、层号均无 NaN/Inf。
- 层号从 1 起。
- `meta` 与输出矩阵一致。
- 最后一行以 `PATH_SMOKE_PASS` 开头。

将命令和完整输出保存到 `matlab-path-smoke.txt`。同时记录所有 warning；warning 不能直接忽略，应判断是输入数据警告、性能警告还是功能失败。

## 11. MATLAB 形貌预测冒烟测试

完整形貌预测可能耗时较长。基础冒烟测试仅使用上一步生成的前 3 个航点，以验证真实 STL、Excel、粒子计算、mesh 更新和结果结构的完整链路。

```matlab
p_smoke = p(1:min(3, size(p, 1)), :);

topo_params = struct;
topo_params.request_id = '';
topo_params.preview_fps = 8;
topo_params.preview_max_triangles = 300;

topo_stl = fullfile(root, 'profile_prediction', 'part.stl');
topo_xlsx = fullfile(root, 'profile_prediction', 'substrate-surface.xlsx');

t_topo = tic;
result = run_profile_prediction( ...
    topo_stl, topo_xlsx, topo_params, p_smoke, []);
topo_elapsed = toc(t_topo);

assert(~isempty(result.mesh), 'Topography mesh is empty');
assert(size(result.mesh, 2) == 9, 'Mesh must be N x 9 triangles');
assert(all(isfinite(result.mesh), 'all'), 'Mesh contains NaN/Inf');
assert(size(result.layer_profiles, 2) == 4, ...
       'Layer profiles must have four columns');
assert(isfinite(result.uniformity) && result.uniformity >= 0, ...
       'Uniformity is invalid');
assert(isfinite(result.estimated_mass_g) && result.estimated_mass_g >= 0, ...
       'Estimated mass is invalid');
assert(isfinite(result.estimated_time_s) && result.estimated_time_s >= 0, ...
       'Estimated time is invalid');
assert(isfinite(result.predicted_volume_mm3) && ...
       result.predicted_volume_mm3 >= 0, 'Predicted volume is invalid');
assert(double(result.waypoint_count) == size(p_smoke, 1), ...
       'Topography waypoint count mismatch');

fprintf(['TOPO_SMOKE_PASS triangles=%d profiles=%d waypoints=%d ', ...
         'elapsed=%.3fs warnings=%d\n'], ...
        size(result.mesh, 1), size(result.layer_profiles, 1), ...
        result.waypoint_count, topo_elapsed, numel(result.warnings));
disp(result.warnings);
```

预期结果：

- `result.mesh` 是非空 `N×9` 有限值矩阵。
- `layer_profiles` 即使为空也保持 4 列结构；非空时每行表示一层。
- 质量、时间、体积和均匀性均为有限非负值。
- `waypoint_count` 与输入航点数一致。
- 无未处理异常。
- 最后一行摘要以 `TOPO_SMOKE_PASS` 开头。

如 `result.warnings` 非空，应逐条写入 `matlab-topography-smoke.txt`：

- 可接受：固定冒烟输入不包含某个可选数据源，但核心 mesh 仍成功生成。
- 不可接受：STL/Excel 读取失败、函数缺失、矩阵维度错误、Python 发布错误、结果为空或包含 NaN/Inf。

## 12. GUI 端到端实时动画验收

### 12.1 清理手工测试会话

先关闭第 8–11 节使用的手工 MATLAB 会话，确认端口已释放：

```powershell
Get-NetTCPConnection -LocalPort 5555,5556,5557 -State Listen -ErrorAction SilentlyContinue
```

预期没有输出。这样可以验证应用“自动启动并拥有 MATLAB Worker”的路径，而不是误复用手工会话。

### 12.2 启动 GUI

在已激活 `venv` 且已设置环境变量的 PowerShell 中执行：

```powershell
python run_app.py
```

预期结果：

- Python 主窗口先出现，MATLAB 启动在后台进行，窗口不会因 MATLAB 冷启动而持续无响应。
- 状态区域经历“正在启动 MATLAB”并最终进入 Ready。
- 未安装许可证的测试机在开发者模式下可以进入主界面。
- 演示点云自动加载，或可以通过“加载点云”流程加载。
- 不出现两个主窗口、两个进度订阅器或重复 Bridge。

### 12.3 验证三个端口

在第二个 PowerShell 窗口执行：

```powershell
Get-NetTCPConnection -LocalPort 5555,5556,5557 -State Listen -ErrorAction Stop |
    Sort-Object LocalPort |
    Select-Object LocalAddress, LocalPort, State, OwningProcess |
    Tee-Object -FilePath (Join-Path $Evidence "ports-running.txt")
```

预期结果：

- 5555、5556、5557 各有且只有一个监听记录。
- 三个端口属于同一套 MATLAB/嵌入式 Python Bridge。
- 没有 `Address already in use`。

### 12.4 路径实时显示

1. 加载仓库中的固定点云或 GUI 演示点云。
2. 选取一个规模适中的缺陷区域。
3. 打开参数面板。
4. 检查“路径规划”和“冷喷涂”两个参数分组均非空。
5. 确认 `particle_velocity` 等冷喷涂参数可见且有默认值。
6. 点击“生成修复路径”。
7. 在计算过程中拖动窗口、切换页面、操作 3D 视角。
8. 观察路径是否按层逐步出现，而不是等待 MATLAB 全部完成后一次性出现。

预期结果：

- 参数面板不再因 `pp/cs` 与 `path_planning/cold_spray` 不一致而为空。
- 不出现 `KeyError: 'particle_velocity'`。
- 路径层按层号依次累积；最终层数与 MATLAB 最终结果一致。
- 路径显示不会因形貌预览的 latest-frame-wins 策略而丢层。
- 窗口持续响应，无超过 1 秒的冻结。
- 最终结果到达后不会清空或重复覆盖已经显示的有效实时路径。

### 12.5 形貌实时显示

1. 路径完成后进入“形貌预测”。
2. 点击“执行形貌预测”。
3. 观察沉积 mesh 在计算过程中更新。
4. 在动画期间持续拖动窗口、旋转视角、切换页面。
5. 记录 30 秒视频或连续截图，至少覆盖一个层末。

预期结果：

- MATLAB 预览发布频率不高于约 8 FPS。
- GUI 默认约 5 FPS 渲染，不会按网络消息数量无限排队。
- 网络积压时显示最新预览，允许跳过旧的中间预览。
- 每层结束时出现完整分辨率关键帧。
- 路径和形貌显示可以共存，不互相清空。
- 最终形貌与最后一个完整关键帧一致。
- 窗口持续响应，无明显输入延迟和持续卡顿。

## 13. 取消机制验收

取消是协作式取消：GUI 通过 5557 发送请求，Bridge 确认后，MATLAB 在安全检查点停止并发布唯一 `CANCELLED` 终态。收到取消 ACK 不等于算法已经完成清理。

默认超时：

- 取消 ACK：2 秒；
- MATLAB 完成清理：15 秒；
- heartbeat 健康判断：5 秒一次，连续 3 次未成功约 15 秒判定异常。

### 13.1 路径规划阶段取消

1. 启动一个路径规划任务。
2. 确认至少出现一个进度或路径层。
3. 点击“取消”。
4. 观察状态直至任务真正结束。
5. 保存截图和日志。

预期结果：

- UI 立即显示“正在取消计算”或等价状态。
- 取消按钮禁用，防止重复提交。
- Controller 保持 busy/CANCELLING，不得在仅收到 ACK 后提前变成 IDLE。
- MATLAB 在下一个安全检查点停止。
- 只出现一次 `CANCELLED` 终态。
- 不出现 SUCCESS 与 CANCELLED 同时到达的竞态。
- UI 不挂死，不显示虚假的 100% 成功。

### 13.2 形貌预测阶段取消

1. 重新启动任务并完成路径规划。
2. 启动形貌预测。
3. 等待至少出现一个 mesh 预览。
4. 点击“取消”。
5. 观察状态直至任务真正结束。

预期结果与 13.1 相同，并额外要求：

- 已经显示的最后一帧可以保留，但必须明确标记任务已取消。
- 不得将已取消的中间预览当作最终成功结果。

### 13.3 重复取消与取消后重试

1. 启动第三个任务。
2. 快速连续点击取消按钮，或在按钮禁用前模拟两次点击。
3. 等待 `CANCELLED`。
4. 立即启动同一输入的新任务。
5. 让新任务成功完成。

预期结果：

- 重复取消请求是幂等的，不触发第二个终态。
- 不出现 REQ socket 状态错误。
- 取消完成前不能启动新任务。
- 取消完成后能启动新任务。
- 新任务有新的 operation ID，不继承旧任务的取消标志、序号、mesh 或路径缓存。
- `ProgressPublisher.begin_operation` 在新任务开始时会清空 `_reliable` 队列，避免旧任务的 terminal 事件（如上一轮的 `CANCELLED`/`FAILED`）污染新任务的实时流；`finish_operation` 在任务结束时清理该 operation 的序列号字典项，防止长期运行后内存单调增长。

### 13.4 安全边界

验证日志中不得出现以下行为：

- 按 `MATLAB.exe` 进程名批量 kill。
- 取消 ACK 后立即强杀 MATLAB。
- 对手工启动或复用的 MATLAB 会话执行自动 kill。

只有当前应用明确拥有的 MATLAB Worker，在取消清理超时或不可恢复错误后，才允许按记录的精确 PID 终止。

## 14. 错误恢复验收

故障注入必须在专用测试工作站执行，不要在保存着未完成 MATLAB 工作的机器上执行。

### 14.1 进度端口 5556 冲突

确保 GUI 未运行。在 PowerShell A 中占用 5556：

```powershell
.\venv\Scripts\python.exe -c "import time,zmq; c=zmq.Context(); s=c.socket(zmq.PUB); s.bind('tcp://127.0.0.1:5556'); print('5556 occupied'); time.sleep(600)"
```

在 PowerShell B 中运行 GUI：

```powershell
python run_app.py
```

预期结果：

- Bridge 报告进度端口绑定失败。
- 应用显示结构化、可理解的错误，不得假装实时服务已就绪。
- GUI 不死锁。
- 不创建第二个 ProgressPublisher。
- `MatlabAdapter` 一旦检测到实时通信服务启动失败，会在本次进程内将 `_matlab_available` 置为 `False`，后续请求不再重复尝试 MATLAB 路径，避免反复失败造成的卡顿。
- `ComputeController` 在 MATLAB 启动失败路径上会对 `_matlab_service` 执行 `close()` 并置 `None`，避免泄露 ZMQ 客户端 socket。
- 关闭 GUI 后，在 PowerShell A 按 Ctrl+C 释放占用。
- 重新启动 GUI 后三个端口均能正常绑定并完成一次计算。

### 14.2 取消端口 5557 冲突

用相同方式占用 5557：

```powershell
.\venv\Scripts\python.exe -c "import time,zmq; c=zmq.Context(); s=c.socket(zmq.REP); s.bind('tcp://127.0.0.1:5557'); print('5557 occupied'); time.sleep(600)"
```

预期结果：

- Bridge 明确报告取消控制端口绑定失败。
- 应用不能把“取消不可用”的任务当作完整稳定服务启动。
- 不挂死，不出现无限重试或多个控制线程。
- `BridgeServer.stop()` 在设置 `_running=False` 后会强制关闭 REP socket（`linger=0`），中断可能阻塞在 `recv`/`send` 上的调用；配合 `RCVTIMEO=100ms`/`SNDTIMEO=5000ms`，关闭路径不会无限等待客户端。
- 释放端口并重启后恢复正常。

### 14.3 应用拥有的 MATLAB Worker 异常退出

1. 先关闭所有手工 MATLAB 会话。
2. 由 `python run_app.py` 自动启动 MATLAB。
3. 在 GUI 日志中记录应用启动的 MATLAB PID。
4. 用以下命令核对命令行：

```powershell
Get-CimInstance Win32_Process -Filter "Name='MATLAB.exe'" |
    Select-Object ProcessId, ParentProcessId, CommandLine |
    Format-List
```

5. 只对命令行包含当前仓库路径和 `matlab_bridge_server` 的精确 PID 注入故障：

```powershell
Stop-Process -Id <APP_OWNED_MATLAB_PID> -Force
```

预期结果：

- 应用检测到 MATLAB Worker/heartbeat 丢失并显示错误。
- 状态进入 CRASHED/RECOVERING，而不是继续显示成功。
- 不保留旧任务为 busy。
- `MatlabLifecycleManager._try_restart` 在后台线程执行重启（MATLAB 冷启动耗时 30–60s），不阻塞 Qt 主线程，窗口在恢复期间仍可响应。
- `MatlabBridgeLauncher.restart()` 在重新调用 `start()` 前会等待旧 Bridge 端口释放（最多 10s），避免残留端口被误判为“已就绪”导致复用一个已经死亡的会话。
- 下一次启动计算时，应用自动启动新的 owned MATLAB Worker。
- 新 MATLAB PID 与旧 PID 不同。
- 5555、5556、5557 重新各有一个监听者。
- 恢复后可以成功完成一次任务。
- 计算过程中若发生引擎级异常（`EngineUnavailableError`、`MatlabEngineUnhealthyError`、`EngineCrashError`），`execution_scope` 将状态转为 `RECOVERING`；若只是临时网络错误（`BridgeError` 子类如连接超时），状态保持 `READY`，允许下次重试而不触发完整恢复流程。

### 14.4 手工 MATLAB 会话保护

1. 手工启动 MATLAB R2025b 并运行 `matlab_bridge_server`。
2. 启动 GUI，使其复用现有 5555 Bridge。
3. 触发取消超时或关闭 GUI。

预期结果：

- 日志明确显示“复用现有 MATLAB 会话”。
- GUI 不得终止手工 MATLAB PID。
- 关闭 GUI 后，手工 MATLAB 仍然运行。

## 15. 10 分钟稳定性与资源验收

### 15.1 场景要求

在同一个 GUI 进程中连续运行至少 10 分钟，并完成：

1. 一次路径阶段取消；
2. 一次形貌阶段取消；
3. 至少一次完整成功；
4. 同一输入总计至少运行 3 次；
5. 每次任务之间不重启 GUI；
6. 运行期间持续操作窗口和 3D 视角。

### 15.2 资源采样

在单独 PowerShell 中执行以下 10 分钟采样：

```powershell
$Csv = Join-Path $Evidence "process-samples.csv"
1..120 | ForEach-Object {
    Get-Process -Name python,pythonw,MATLAB -ErrorAction SilentlyContinue |
        Select-Object `
            @{Name="Timestamp";Expression={(Get-Date).ToString("o")}}, `
            ProcessName, Id, `
            @{Name="WorkingSetMB";Expression={[math]::Round($_.WorkingSet64 / 1MB, 2)}}, `
            @{Name="PrivateMemoryMB";Expression={[math]::Round($_.PrivateMemorySize64 / 1MB, 2)}}, `
            CPU, Handles |
        Export-Csv -Path $Csv -Append -NoTypeInformation
    Start-Sleep -Seconds 5
}
```

### 15.3 通过标准

- UI 无持续超过 1 秒的冻结。
- 预览稳定在约 5–10 FPS 的目标区间，不出现网络消息越积越多。
- 完整成功任务的路径层数量最终齐全。
- 每个任务只有一个 terminal 事件，不丢失、不重复。
- 同一输入重复运行时，Python 和 MATLAB 内存不持续单调增长。
- 最后一轮任务结束并回到稳定空闲状态后，相对第一轮结束的内存增幅建议小于 25%。
- Handles 不持续单调增长。
- 没有 `Address already in use`。
- 没有 `QThread: Destroyed while thread is still running`。
- 没有持续 Protobuf parse error。
- 没有重复 `ComputeController`、`ProgressSubscriber` 或 PUB/SUB socket。
- 取消后下一次任务不继承旧 operation 的路径、mesh、状态或序号。
- `ProgressPublisher.finish_operation` 在每个任务结束时清理该 operation 的序列号字典项，长时间重复运行（≥10 次）后 `_sequence_by_operation` 不应持续增长；`begin_operation` 清空 `_reliable` 队列确保旧 terminal 事件不残留。
- `MatlabAdapter._matlab_available` 在首次 MATLAB 失败后置 `False`，后续请求直接跳过 MATLAB 路径，不应在 10 分钟窗口内看到反复重试 MATLAB 引擎的日志风暴。

若内存增幅超过 25%，不得仅凭任务规模解释。应延长到 30 分钟并使用采样数据定位是 MATLAB 算法缓存、Python mesh、Qt 对象还是日志增长。

## 16. 退出清理验收

### 16.1 正常退出

1. 确保当前没有任务运行。
2. 用窗口关闭按钮退出 GUI。
3. 等待 10 秒。
4. 执行：

```powershell
Get-NetTCPConnection -LocalPort 5555,5556,5557 -State Listen -ErrorAction SilentlyContinue |
    Format-Table -AutoSize |
    Out-String |
    Tee-Object -FilePath (Join-Path $Evidence "ports-after.txt")

Get-CimInstance Win32_Process -Filter "Name='MATLAB.exe'" |
    Select-Object ProcessId, ParentProcessId, CommandLine
```

预期结果：

- 三个端口均已释放。
- 由本应用启动的 MATLAB Worker 已退出。
- 手工启动且被复用的 MATLAB 会话仍运行。
- 日志中没有 QThread 销毁警告。
- `MatlabBridgeLauncher.stop()` 通过 `_stop_lock` 防止 `atexit` 回调与显式 `stop()`/`restart()` 并发重入；重复调用安全。
- `MatlabAdapter.shutdown()` 幂等（`_shutdown_done` 标志保护），`_cleanup` 与显式 `shutdown()` 重复调用不会二次释放 MATLAB 引擎引用或实时通信 socket。
- `BridgeServer.stop()` 强制关闭 REP socket 中断阻塞的 `recv`/`send`，退出过程有超时上限，不会因客户端失联而无限等待。

### 16.2 计算中关闭

1. 再次启动 GUI。
2. 在形貌计算中关闭主窗口。
3. 确认退出提示。
4. 等待清理结束后重复端口和进程检查。

预期结果：

- 应用先请求协作式取消和线程停止，再退出。
- 退出过程有超时上限，不无限等待。
- `MatlabBridgeLauncher.start()` 在 MATLAB 进程提前退出或等待端口就绪超时的早期退出路径上，会清理可能派生的子进程（`_force_kill_os`），不残留僵尸 MATLAB。
- 不遗留 5555–5557。
- 不遗留应用拥有的 MATLAB Worker。

最后停止 PowerShell transcript：

```powershell
Stop-Transcript
```

## 17. 验收记录矩阵

复制以下表格到 `acceptance-matrix.md`，填写“实际结果”“证据”和“结论”：

| ID | 验收项目 | 核心步骤 | 预期结果 | 实际结果 | 证据路径 | 结论 |
|----|----------|----------|----------|----------|----------|------|
| ENV-01 | Windows/Python/MATLAB 版本 | 第 3、6 节 | Windows x64；Python 3.10–3.12；R2025b | 待填写 | `environment.txt` | PASS/FAIL |
| PY-01 | Python 完整测试 | 第 6.5、6.6 节 | 0 failures | 待填写 | `python-*.txt` | PASS/FAIL |
| MAT-01 | MATLAB Python 环境 | 第 8 节 | InProcess；指向项目 venv | 待填写 | `matlab-preflight.txt` | PASS/FAIL |
| PROTO-01 | MATLAB/Python 类型互操作 | 第 9 节 | `py.bool`、数组、`pyargs` 全部通过 | 待填写 | MATLAB 输出 | PASS/FAIL |
| PATH-01 | 路径规划真实计算 | 第 10 节 | 非空有限航点，层号和 meta 一致 | 待填写 | `matlab-path-smoke.txt` | PASS/FAIL |
| TOPO-01 | 形貌预测真实计算 | 第 11 节 | 非空 N×9 mesh，指标有效 | 待填写 | `matlab-topography-smoke.txt` | PASS/FAIL |
| UI-01 | 路径与形貌实时动画 | 第 12 节 | 逐层路径、限帧 mesh、窗口响应 | 待填写 | 截图/视频/日志 | PASS/FAIL |
| CANCEL-01 | 路径阶段取消 | 第 13.1 节 | 唯一 CANCELLED，可恢复 | 待填写 | 截图/日志 | PASS/FAIL |
| CANCEL-02 | 形貌阶段取消 | 第 13.2 节 | 唯一 CANCELLED，不伪成功 | 待填写 | 截图/日志 | PASS/FAIL |
| CANCEL-03 | 重复取消与重试 | 第 13.3 节 | 幂等；新任务不继承旧状态 | 待填写 | 日志 | PASS/FAIL |
| RECOVERY-01 | 端口冲突 | 第 14.1、14.2 节 | 明确失败；释放后可恢复 | 待填写 | 日志/端口输出 | PASS/FAIL |
| RECOVERY-02 | owned Worker 崩溃 | 第 14.3 节 | 检测、重启、下次任务成功 | 待填写 | PID/日志/截图 | PASS/FAIL |
| RECOVERY-03 | 手工 MATLAB 保护 | 第 14.4 节 | 复用会话不被 kill | 待填写 | PID/日志 | PASS/FAIL |
| SOAK-01 | 10 分钟稳定性 | 第 15 节 | 无冻结、积压、持续资源增长 | 待填写 | `process-samples.csv` | PASS/FAIL |
| SHUTDOWN-01 | 正常与计算中退出 | 第 16 节 | 无端口、线程、owned Worker 遗留 | 待填写 | `ports-after.txt`/日志 | PASS/FAIL |

每个 FAIL 必须附：

- 首次失败时间；
- 精确 commit SHA；
- 完整日志；
- 最小复现步骤；
- 是否可稳定复现；
- 截图或视频；
- 对应 issue 链接。

## 18. 最终判定规则

### 18.1 可晋级 Windows R2025b RC

只有同时满足以下条件，才可判定为 **Windows + MATLAB R2025b RC 通过**：

- 第 17 节所有阻断项均为 PASS；
- Python 完整测试 0 failures；
- MATLAB 路径和形貌真实计算通过；
- 两阶段取消与取消后重试通过；
- 端口冲突和 owned Worker 崩溃恢复通过；
- 手工 MATLAB 会话保护通过；
- 10 分钟稳定性测试通过；
- 正常退出和计算中退出均无残留；
- 所有证据与 commit SHA 对应。

### 18.2 不可宣称稳定

出现以下情况时，结论只能是“代码级改造完成，Windows R2025b 实测待完成”：

- 只跑了 Python 测试；
- MATLAB 不在本机；
- 使用了非 R2025b MATLAB；
- 使用 Python Demo 代替 MATLAB 引擎；
- 只验证最终结果，没有验证实时动画；
- 只验证取消按钮，没有验证 MATLAB 确实停止和下一任务恢复；
- 未执行故障注入；
- 未执行 10 分钟稳定性测试。

## 19. 常见问题与恢复方法

### 19.1 PowerShell 禁止激活脚本

错误类似：

```text
running scripts is disabled on this system
```

只对当前 PowerShell 进程放开：

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\venv\Scripts\Activate.ps1
```

不要为测试修改整台机器的永久执行策略。

### 19.2 MATLAB 已加载错误 Python

`pyenv` 一旦进入 Loaded 状态，通常不能在同一 MATLAB 进程中切换到不同解释器。关闭所有 MATLAB 窗口，重新启动 R2025b，然后先执行 `pyenv('Version', ...)`，再调用任何 `py.*`。

若 `matlab_bridge_server.m` 启动时输出 `WARNING: venv not found. Using system Python.`，说明项目根目录下没有 `venv\Scripts\python.exe`（或非 Windows 平台的 `venv/bin/python`）。此时 Bridge 会回退到系统 Python，通常因缺少 `repair_app` 依赖而失败。解决方法：按第 6.2 节创建名为 `venv` 的虚拟环境并执行 `python -m pip install -e ".[dev,full]"`，然后重启 MATLAB Bridge。

### 19.2a MATLAB 引擎连接失败

`MatlabEngineProxy` 在 pyenv 宿主模式下按三级递进策略连接：`connect_matlab()` → `connect_matlab(name)` → `start_matlab(background=True)`。若三层全部失败，会抛出 `EngineUnavailableError`。

常见原因：

- `matlab_bridge_server.m` 未运行，`CSAM_BRIDGE_IN_MATLAB` 环境变量未设置为 `1`，导致代理误判为外部模式；
- 共享会话名称不匹配（默认 `matlab_bridge`，可通过 `CSAM_MATLAB_SHARED_NAME` 覆盖）；
- MATLAB 引擎 API 未安装（需在 venv 中执行 `python -m pip install matlabengine`）。

`auto` 模式下连接失败会自动降级到 Python 原型；`matlab` 模式下则直接报错，不降级。

### 19.3 `ModuleNotFoundError: repair_app`

检查：

```matlab
char(py.sys.executable)
cell(py.sys.path)
```

预期 Python 可执行文件指向项目 `venv`。回到 PowerShell，在仓库根目录重新执行：

```powershell
.\venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,full]"
```

然后关闭并重启 MATLAB。

### 19.4 端口已占用

```powershell
Get-NetTCPConnection -LocalPort 5555,5556,5557 -State Listen |
    Select-Object LocalPort, OwningProcess
```

通过 PID 确认进程身份。不要使用 `taskkill /IM MATLAB.exe /F`，因为这会关闭所有 MATLAB 会话。

### 19.5 GUI 有更新但明显卡顿

依次检查：

1. MATLAB `preview_fps` 是否被设置到大于 10；
2. `preview_max_triangles` 是否过大；
3. 是否出现多个 `ProgressSubscriber`；
4. 是否每个网络帧都直接排入 Qt 主线程；
5. 5556 是否存在多个 Bridge/PUB；
6. GPU 驱动是否导致 3D 渲染回退到软件模式；
7. `process-samples.csv` 中 Python/MATLAB 内存是否持续增长。

### 19.6 取消已确认但 MATLAB 仍短暂运行

这是协作式取消的正常过渡状态。ACK 只表示 Bridge 已记录取消请求，MATLAB 要在下一个安全检查点停止。默认允许最多 15 秒完成清理。在此期间 Controller 必须保持 CANCELLING，不能启动新任务。

如果超过 15 秒：

- 保存日志和 operation ID；
- 检查 MATLAB 循环是否经过取消检查点；
- 只有应用拥有的 MATLAB Worker 才允许被精确 PID 终止；
- 复用的手工 MATLAB 会话不得被强杀。

### 19.7 配置加载失败导致 Bridge 启动异常

`DEFAULT_CONFIG` 已改为惰性初始化（`_ConfigProxy`），首次访问属性时才构造 `BridgeConfig`，避免模块导入阶段因 `parameter_schema.json` 异常导致级联导入失败。`_env_int`/`_env_str` 在读取 schema 失败时会记录警告并回退到传入的 `fallback` 值，不会抛出异常中断 Bridge 启动。

若日志出现 `读取 schema '...' 失败，使用 fallback=...` 警告，应检查 `parameter_schema.json` 是否存在且 `network_parameters` 节点完整。此时 Bridge 仍能以回退默认值启动，但超时、心跳间隔等参数可能与正式环境不一致，验收时需记录实际生效值。

### 19.8 MATLAB 反复失败后仍持续重试

`MatlabAdapter._matlab_available` 是进程内统一降级标志：首次 MATLAB 管线超时或异常后置 `False`，后续 `_invoke_pipeline_with_fallback` 和 `_try_profile_prediction` 直接跳过 MATLAB 路径，避免在 MATLAB 不可用时反复重试造成的卡顿和日志风暴。

若需在同一进程内重新尝试 MATLAB（例如已重启 MATLAB Bridge），应重启 GUI 进程以重置该标志。`auto` 模式下降级到 Python 原型；`matlab` 模式下首次失败即返回错误，不降级。
