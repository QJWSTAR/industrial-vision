# 回归检查清单

验证新更改未引入回归问题。

## 测试套件

- [ ] `pytest --tb=short -q` 报告 145 个通过，0 个失败
- [ ] 与基线运行相比无新警告
- [ ] `pytest --cov=repair_app --cov-report=term-missing` 覆盖率 >= 之前的基线（67%）
- [ ] `pytest repair_app/tests/test_stress.py -v --benchmark-only` — 无超过 10% 的性能回归

## 核心算法

- [ ] 相同输入参数下路径规划产生相同的路径点
- [ ] 相同输入下形貌预测产生相同的沉积层
- [ ] 相同点云下法向量估计产生相同的法向量
- [ ] 相同参数下可行性检查返回相同结果
- [ ] 材料数据库查询返回相同值

### 回归测试流程

```bash
# Save baseline output before changes
python -c "
from repair_app.core.path_planner import PathPlanner
# ... generate baseline waypoints ...
" > baseline_path.txt

# After changes, compare
python -c "
from repair_app.core.path_planner import PathPlanner
# ... generate new waypoints ...
" > new_path.txt

diff baseline_path.txt new_path.txt  # Should be empty
```

## 通信层

- [ ] ZMQ 客户端连接和断开无错误
- [ ] Protobuf 序列化/反序列化往返一致
- [ ] `repair_protocol_pb2.py` 生成相同的消息结构
- [ ] `repair_serialization.py` 产生相同的序列化输出
- [ ] ZMQ 地址解析在两个平台上均正常工作（`get_zmq_address_from_env()`）

## UI 层

- [ ] 应用程序启动且主窗口渲染正确
- [ ] 点云加载对话框打开并接受文件
- [ ] 3D 可视化渲染带颜色的点云
- [ ] 缺陷选择模式（矩形、自由手绘、画笔）均正常工作
- [ ] 参数输入字段接受并验证值
- [ ] 步骤导航（路径规划 → 形貌预测）正常工作
- [ ] 导出按钮触发正确的导出函数
- [ ] 视图控件（等轴测、俯视、侧视、正视）正常工作
- [ ] 层动画播放和暂停正常
- [ ] 层滑块可逐层浏览

## 导出功能

- [ ] G-code 导出生成有效的 `.nc` 文件
- [ ] G-code 包含安全 Z 轴移动、M 代码和进给速度映射
- [ ] PDF 报告导出生成有效的 `.pdf` 文件
- [ ] PDF 报告包含扫描信息、参数、摘要、对比图像
- [ ] 导出验证器在导出前捕获无效的路径点

## 许可证管理

- [ ] 许可证加载正确读取 `config/license.key`
- [ ] 机器 ID 验证同时接受新（`uuid.getnode`）和旧（`platform.node`）ID
- [ ] 过期许可证被拒绝并显示正确的错误消息
- [ ] 签名验证对 RSA 和 HMAC 回退均正常工作
- [ ] 缺失许可证文件时记录警告但不阻止启动

## 平台抽象

- [ ] `repair_app/platform/transport.py` 按操作系统返回正确的 ZMQ 地址
- [ ] `repair_app/platform/fonts.py` 按操作系统返回正确的中日韩字体
- [ ] `repair_app/utils/config.py` ASCII 目录别名正常工作（morphology_prediction、matlab_frames）
- [ ] 旧版中文目录名称仍可作为回退使用

## 线程安全

- [ ] 路径规划工作线程启动和停止无挂起
- [ ] 形貌预测工作线程启动和停止无挂起
- [ ] `requestInterruption()` 使工作线程在 1 秒内停止
- [ ] ZMQ 客户端 `close()` 终止轮询循环无死锁
- [ ] 无关于跨线程信号/槽连接的 Qt 警告

## 配置

- [ ] `config.py` 正确加载所有参数规格
- [ ] `PARAM_BOUNDS` 与 `PARAM_SPECS` 匹配（无缺失或多余条目）
- [ ] `APP_VERSION` 与 `pyproject.toml` 版本匹配
- [ ] `MATERIALS` 列表完整且与材料数据库匹配

## 文件 I/O

- [ ] 点云加载支持 CSV、TXT、XYZ、ASC 格式
- [ ] 带法向量的点云（6 列）解析正确
- [ ] 不带法向量的点云（3 列）通过估计生成法向量
- [ ] NPZ 文件以 `allow_pickle=False` 加载（无对象数组）
- [ ] JSON 附属元数据与 NPZ 数据一起正确加载
- [ ] 包含中文字符的文件路径在 Windows 上正常工作

## 安全性

- [ ] 任何 `np.load` 调用中无 `allow_pickle=True`
- [ ] 生产路径中无硬编码的 HMAC 密钥（使用环境变量）
- [ ] 无 `try-except-pass` 模式
- [ ] `bandit -r repair_app/ -x repair_app/tests/ -ll` 报告零问题
