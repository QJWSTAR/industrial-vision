# 工业视觉修复系统 — 试用说明

## 1. 软件用途

本软件是一个工业视觉引导的激光修复路径规划与形貌预测系统。支持导入三维点云数据，框选缺陷区域，自动生成修复路径，预测修复后形貌，并导出 G-code 用于激光加工设备。

---

## 2. Windows 系统要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Windows 10 64-bit 或 Windows 11 64-bit |
| Python | 3.12（推荐）或 3.10-3.11 |
| 内存 | 8 GB 以上 |
| 依赖 | 见 `requirements.txt`，通过 `pip install -r requirements.txt` 安装 |
| MATLAB | 可选（不安装也能使用本地 Python 引擎） |

---

## 3. 如何启动

### 方法一：双击启动（推荐）

1. 确保已安装 Python 3.12 并配置好 PATH
2. 打开命令行，进入本目录，执行：
   ```
   pip install -r requirements.txt
   ```
3. 双击 `启动软件.bat`

### 方法二：命令行启动

```bash
# 设置环境变量（首次启动建议）
set CSAM_DEVELOPER_MODE=1
set CSAM_ALGORITHM_ENGINE=python

# 启动
python run_app.py
```

---

## 4. 环境变量说明

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CSAM_DEVELOPER_MODE` | 0 | 设为 `1` 跳过许可证检查（开发/试用模式） |
| `CSAM_ALGORITHM_ENGINE` | `python` | 设为 `python` 使用本地引擎，设为 `matlab` 使用 MATLAB 引擎 |

---

## 5. 如何导入测试数据

软件支持以下格式的点云导入：

- **PLY**（推荐）— 包含顶点和法向量的点云
- **XYZ** — 纯坐标点云（法向量将自动估计）
- **STL** — 三角网格（将自动采样为点云）

### 快速测试

软件启动后会自动加载合成 Demo 数据（8000 个点），无需手动导入即可开始测试。

---

## 6. 推荐测试流程

```
启动软件 → 加载 Demo 点云（自动）
    ↓
导入点云（或直接使用 Demo 数据）
    ↓
框选缺陷区域（鼠标拖拽选择）
    ↓
点击"开始修复"
    ↓
路径规划（自动生成扫描路径）
    ↓
形貌预测（预览修复后效果）
    ↓
导出 G-code / PDF 报告 / CSV / JSON
```

### 操作提示

- **左键拖拽**：框选缺陷区域
- **右键**：取消选择
- **滚轮**：缩放点云
- **中键拖拽**：旋转视角
- 底部状态栏显示当前步骤进度

---

## 7. MATLAB 是否必须启动

**不必须。**

- 默认使用本地 Python 引擎（设置 `CSAM_ALGORITHM_ENGINE=python`）
- 如需使用 MATLAB 引擎加速计算，需：
  1. 安装 MATLAB R2023b 或更高版本
  2. 安装 MATLAB Engine API for Python
  3. 设置 `CSAM_ALGORITHM_ENGINE=matlab`
- MATLAB 不可用时，软件会自动降级到 Python 引擎并给出提示

---

## 8. 已知限制

| 限制 | 说明 |
|------|------|
| 合成 Demo 数据 | 当前 Demo 使用合成数据，不包含真实扫描点云 |
| MATLAB 路径规划 | MATLAB 引擎路径规划算法仍在调优中，Python 引擎为默认推荐 |
| 形貌预测精度 | 形貌预测为简化模型，实际修复效果需以加工验证为准 |
| 导出格式 | G-code 导出为通用格式，具体机床后处理可能需调整 |
| 无自定义图标 | 任务栏显示默认 Python 图标 |
| 大点云性能 | 点云超过 50,000 点时渲染和计算可能较慢 |

---

## 9. 常见问题

### Q: 启动报错 "No module named 'xxx'"
A: 依赖未安装，执行 `pip install -r requirements.txt`

### Q: 启动后窗口一片空白
A: 检查显卡驱动是否支持 OpenGL，或尝试设置 `QT_QPA_PLATFORM=offscreen`

### Q: 导入点云文件后无显示
A: 检查文件格式是否正确（PLY/XYZ/STL），点云数据是否包含有效坐标

### Q: 路径规划失败
A: 确认已框选缺陷区域，且缺陷区域包含足够的点

### Q: 导出 G-code 失败
A: 确认路径规划已完成，且输出目录有写入权限

---

## 10. 联系与反馈

如有问题或建议，请通过以下方式反馈：

- 记录软件日志：`%APPDATA%/CSAM/logs/`
- 记录崩溃报告：`%APPDATA%/CSAM/logs/exceptions/`

---

*最后更新：2026-07-18*