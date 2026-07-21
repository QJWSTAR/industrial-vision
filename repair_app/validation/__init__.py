"""validation — 算法验证体系

不开发新算法，只验证现有 MATLAB 与 Python 算法的一致性。

模块：
- algorithm_validator: 双引擎执行器（同一输入分别跑 MATLAB / Python）
- result_comparator: 6 维结果比对（pointlist/velocitylist/Layer/Mesh/Volume/Uniformity）
- diff_report_generator: 自动生成 Diff Report（误差/耗时/版本）
"""
