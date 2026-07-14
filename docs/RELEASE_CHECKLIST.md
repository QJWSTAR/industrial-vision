# 发布检查清单

本检查清单用于版本发布前的全面验证。所有项目必须勾选通过后方可签字发布。

---

## 代码质量

- [ ] 全部单元测试通过（276 项）
- [ ] 端到端验证通过（27 项）
- [ ] 无 import 错误
- [ ] 无 `__pycache__` 残留
- [ ] `.gitignore` 配置正确

## 功能验证

- [ ] STL 导入正常
- [ ] 路径规划生成航点
- [ ] 形貌预测生成 mesh / layer_profiles / particle_dist
- [ ] GUI 实例化正常
- [ ] `ProfileResultPanel` 渲染正常
- [ ] G-code 导出正常
- [ ] PDF 报告导出正常

## MATLAB 集成

- [ ] `matlab_bridge_server.m` 可启动
- [ ] MATLAB 共享会话可连接
- [ ] `run_path_planning` 可调用
- [ ] `run_profile_prediction` 可调用
- [ ] 降级策略生效（MATLAB 不可用时）

## 通信协议

- [ ] Protobuf v2.1 序列化 / 反序列化正常
- [ ] ZeroMQ REP/REQ 通信正常
- [ ] Bridge 无死锁

## 文档

- [ ] README 更新
- [ ] 用户手册完整
- [ ] 部署手册完整
- [ ] CHANGELOG 更新
- [ ] Release Notes 更新

## 部署

- [ ] PyInstaller 打包成功
- [ ] 纯净机器测试通过
- [ ] Windows 部署验证
- [ ] Linux 部署验证

## 安全

- [ ] 无硬编码密钥
- [ ] License 验证正常
- [ ] 日志不含敏感信息
