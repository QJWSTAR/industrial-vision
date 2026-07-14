# MATLAB 算法完整调用图

> 基于仓库 `d:\work\demo\industrial-vision` 全部 30 个 `.m` 文件的逐文件审查。
> 生成时间：2026-07-14

---

## 1. 文件总览

| 目录 | 文件数 | 实际算法类别 |
|------|--------|-------------|
| `形貌预测\` | 8 | 路径规划（STL→切片→路径→机器人指令） |
| `路径规划\` | 15 | 形貌预测（CFD→射线追踪→沉积→可视化） |
| `matlab_server\` | 12 | 已弃用 v3.0 服务端 |
| `matlab_bridge_server.m` | 1 | 生产入口（进程宿主） |
| **合计** | **36** | |

> **目录命名反转**：`形貌预测\` 含路径规划算法，`路径规划\` 含形貌预测算法。

---

## 2. 全部 .m 文件清单

### 2.1 路径规划管线（`形貌预测\` 目录，8 个文件）

| # | 文件 | 函数签名 | 类别 |
|---|------|---------|------|
| 1 | `main.m` | 脚本（无函数） | 离线脚本 |
| 2 | `read_stl_file.m` | `triangles = read_stl_file(filename)` | 工具函数 |
| 3 | `model_process.m` | `[all_triangles, additive_cluster, repairing_clusters, x_min, x_max, y_min, y_max] = model_process(triangles, model_scale, tol, base_plane)` | 路径规划 |
| 4 | `layer_slice.m` | `[additive_layerlist, repairing_layerlist] = layer_slice(additive_cluster, repairing_clusters, layer_height, base_plane)` | 路径规划 |
| 5 | `generate_path.m` | `[pointlist, velocitylist, zonelist] = generate_path(additive_layerlist, repairing_layerlist, buffer_additive, buffer_repairing, scanning_angle, scanning_step, edge_step_size, tilt_angle, x_min, x_max, y_min, y_max, linkPath_freeDistance, resolution)` | 路径规划 |
| 6 | `aStarSearch.m` | `[pathX, pathY] = aStarSearch(xGrid, yGrid, occupancyMap, StartNode, OriginalGoalNode, GoalNode, movementType)` | 路径规划 |
| 7 | `point_interpretaion.m` | `moves_matrix = point_interpretaion(pointlist, nozzle_normal_vector, tol)` | 工具函数 |
| 8 | `robot_command_output.m` | `sprayArea = robot_command_output(moves_matrix, ReferencePoint, velocitylist, zonelist, robotcommandoutput, moduleID)` | 导出 |

### 2.2 形貌预测管线（`路径规划\` 目录，15 个文件）

| # | 文件 | 函数签名 | 类别 |
|---|------|---------|------|
| 9 | `main.m` | 脚本（无函数） | 离线脚本 |
| 10 | `read_STLfile.m` | `triangles = read_STLfile(stlfilename)` | 工具函数 |
| 11 | `particleFitting.m` | `[rays_indices, rays_origins, rays_directions, rays_speeds, rays_possiLengths, rays_Vcr, length_threshold, area_threshold] = particleFitting(excelFile, SoD)` | 形貌预测 |
| 12 | `spotInterp.m` | `spotsList = spotInterp(ReferencePoint, pointlist, velocitylist, spot_step_size)` | 路径规划 |
| 13 | `profilePredict.m` | `[oldTriangles, newTriangles] = profilePredict(triangles, removedFacetsIdx, raysCluster, intersected_tri_ids, intersection_points, boundaryVerticesCluster, nozzleOrientation, moveRays_origins, moveRays_directions, rays_speeds, rays_possiLengths, rays_Vcr, Coef_THK, C, length_threshold)` | 形貌预测 |
| 14 | `rayMove.m` | `[moveRays_origins, moveRays_directions, nozzleOrientation, Coef_THK] = rayMove(spotInfo, rays_origins, rays_directions)` | 形貌预测 |
| 15 | `ray_triangle_intersection.m` | `[intersected_ray_ids, intersected_tri_ids, intersection_points] = ray_triangle_intersection(rays_indices, rays_origins, rays_directions, triangles, tri_candidates)` | 工具函数 |
| 16 | `classifyRemovedTriangles.m` | `[removedFacetsIdx, removedFacetsCluster, raysCluster, boundaryVerticesCluster, C] = classifyRemovedTriangles(triangles, intersected_tri_ids, nozzleOrientation, intersected_ray_ids)` | 工具函数 |
| 17 | `recursiveSubdivide.m` | `subdivided = recursiveSubdivide(triangles, maxEdgeLength)` | 工具函数 |
| 18 | `improveShortEdges.m` | `triangles = improveShortEdges(triangles, boundary_vertices, length_threshold)` | 工具函数 |
| 19 | `buildOctree.m` | `node = buildOctree(triangles, max_depth, max_tri_per_node)` | 工具函数 |
| 20 | `batchOctreeFilter.m` | `tri_candidates = batchOctreeFilter(octree, rays_origins, rays_directions)` | 工具函数 |
| 21 | `createTriangulationFromMatrix.m` | `TR = createTriangulationFromMatrix(triangles)` | 工具函数 |
| 22 | `createfigures.m` | `createfigures(savefigure, increment, oldTriangles, newTriangles, moveRays_origins, nozzleOrientation, substrate_triangles, nozzlePath, path)` | 可视化 |
| 23 | `createvideo.m` | `createvideo(savevideo, path, totalFrame)` | 可视化 |

### 2.3 已弃用服务端（`matlab_server\`，12 个文件）

| # | 文件 | 类别 |
|---|------|------|
| 24-35 | `startup.m`, `server.m`, `dispatcher.m`, `registry.m`, `register_algorithms.m`, `config.m`, `health.m`, `heartbeat.m`, `json_codec.m`, `logger.m`, `resource_cleanup.m`, `lifecycle.m` | 已弃用 |

### 2.4 生产入口

| # | 文件 | 类别 |
|---|------|------|
| 36 | `matlab_bridge_server.m` | 进程宿主 |

---

## 3. 各文件详细说明

### 路径规划管线

#### read_stl_file.m
- **作用**：读取 STL 文件（自动检测二进制/ASCII），返回 N×12 三角面矩阵
- **输入**：`filename`（文件名）
- **输出**：`triangles`（N×12：`[x1,y1,z1,x2,y2,z2,x3,y3,z3,nx,ny,nz]`）
- **调用**：无外部调用；含 `read_binary_file`、`read_ascii_file` 子函数
- **工具箱**：`fread`、`typecast`、`fgetl`、`sscanf`

#### model_process.m
- **作用**：模型预处理——缩放→计算属性→移除平行面→分类 additive/repairing→连通分量聚类
- **输入**：`triangles`(N×12), `model_scale`, `tol`, `base_plane`
- **输出**：`all_triangles`(N×15), `additive_cluster`(1×1 cell), `repairing_clusters`(1×K cell), bbox
- **调用**：无外部；含 `generateVertexKey` 子函数
- **工具箱**：`containers.Map`、`graph`、`conncomp`、`uniquetol`、`ismembertol`

#### layer_slice.m
- **作用**：按层高对三角面簇切片，计算每层截面多边形轮廓
- **输入**：`additive_cluster`, `repairing_clusters`, `layer_height`, `base_plane`
- **输出**：`additive_layerlist`, `repairing_layerlist`（每项含 `[application, layertype, height, polygon]`）
- **调用**：无外部；含 `sliceLayers` 子函数
- **工具箱**：`graph`、`conncomp`、`dfsearch`、`uniquetol`、`ismembertol`、`bsxfun`

#### generate_path.m
- **作用**：核心路径规划——遍历每层每个区域，生成 Zig-Zag 填充+边缘补偿+区域间链接路径
- **输入**：13 个参数（两个 layerlist + 缓冲距离 + 扫描参数 + 包围盒 + 链接路径参数 + 分辨率）
- **输出**：`pointlist`(N×6), `velocitylist`(N×1 string), `zonelist`(N×1 string)
- **调用**：`aStarSearch`
- **内部子函数（8 个）**：

| 子函数 | 作用 |
|--------|------|
| `generate_infill` | Zig-Zag 填充：缓冲多边形→旋转→扫描线求交→排序（奇升偶降）→旋转回 |
| `rotate_vertices` | 绕原点旋转顶点 |
| `generate_edge` | 边缘补偿：沿外/内边界均匀采样+倾斜法向量 |
| `uniform_sampling_at_polyline` | 按弧长均匀重采样折线+计算倾斜法向量 |
| `generate_link` | 区域间链接：占据栅格+A*搜索+共线点去除 |
| `coordinate2index` | 坐标→栅格索引 |
| `adjustGoalIfOnEdge` | 目标在障碍上时搜索最近自由格 |
| `removeColinearPoints` | 去除共线中间点 |

- **工具箱**：`polyshape`、`regions`、`sortregions`、`polybuffer`、`polyxpoly`、`boundary`、`ishole`、`isinterior`、`meshgrid`

#### aStarSearch.m
- **作用**：A* 栅格路径搜索（支持 4/8 连通，动态权重）
- **输入**：`xGrid`, `yGrid`, `occupancyMap`, `StartNode`, `OriginalGoalNode`, `GoalNode`, `movementType`
- **输出**：`pathX`, `pathY`（路径坐标）
- **调用**：无外部；含 5 个子函数（`dynamicWeight`、`heuristic`、`isValidNeighbor`、`getMinFNode`、`reconstructPath`）
- **工具箱**：`containers.Map`

#### point_interpretaion.m
- **作用**：将航点法向量转换为 ABB reltool 欧拉角
- **输入**：`pointlist`(N×6), `nozzle_normal_vector`(1×3), `tol`
- **输出**：`moves_matrix`(N×6: `[x,y,z,ax,ay,az]` 度)
- **调用**：无
- **工具箱**：`cross`、`dot`、`norm`、`atan2d`

#### robot_command_output.m
- **作用**：生成 ABB Rapid MoveL/MoveJ 指令文件
- **输入**：`moves_matrix`, `ReferencePoint`, `velocitylist`, `zonelist`, `robotcommandoutput`, `moduleID`
- **输出**：`sprayArea`(2×3 喷涂范围)
- **调用**：无
- **工具箱**：`fopen`、`fprintf`

---

### 形貌预测管线

#### read_STLfile.m
- **作用**：读取 STL 文件返回 N×9 矩阵（不含法向量）
- **输出**：`triangles`(N×9)
- **工具箱**：`stlread`

#### particleFitting.m
- **作用**：从 CFD Excel 数据拟合颗粒分布，生成喷射线（位置+方向+速度+长度+临界速度）
- **输入**：`excelFile`, `SoD`（ standoff 距离）
- **输出**：8 个返回值（射线索引、原点、方向、速度、长度、临界速度、长度阈值、面积阈值）
- **工具箱**：`readmatrix`、`histcounts2`、`fittype`/`fit`（Curve Fitting Toolbox）、`griddata`

#### spotInterp.m
- **作用**：按弧长均匀重采样工具路径点，插值位置和姿态
- **输入**：`ReferencePoint`(1×6), `pointlist`(N×6), `velocitylist`, `spot_step_size`
- **输出**：`spotsList`(M×7: `[x,y,z,nx,ny,nz,补偿系数]`)
- **工具箱**：`containers.Map`

#### profilePredict.m
- **作用**：核心形貌预测——射线追踪+临界速度判定+边界投影+Delaunay 三角化+网格更新
- **输入**：15 个参数（三角网格+移除索引+射线簇+交点+边界顶点+喷嘴方向+射线数据+厚度系数+连接性+长度阈值）
- **输出**：`oldTriangles`（未更新三角面）, `newTriangles`（新沉积三角面）
- **调用**：`improveShortEdges`
- **内部子函数（6 个）**：

| 子函数 | 作用 |
|--------|------|
| `normalVector` | 计算三角面法向量 |
| `projectPointToPlane` | 点投影到平面 |
| `projectToBestPlane` | PCA 最佳拟合 2D 平面投影 |
| `adjustCoordinate` | 边界遮挡调整（polyxpoly 交点检测+对称反射） |
| `pointSymmetry2D` | 2D 点关于直线的对称 |
| `projectTo2DPlane` | 投影到已计算的 2D 平面 |

- **工具箱**：`delaunayTriangulation`、`isInterior`、`polyxpoly`、`cov`、`eig`

#### rayMove.m
- **作用**：通过 Rodrigues 旋转将参考射线变换到当前工具姿态
- **输入**：`spotInfo`(1×7), `rays_origins`, `rays_directions`
- **输出**：`moveRays_origins`, `moveRays_directions`, `nozzleOrientation`, `Coef_THK`
- **调用**：无外部；含 `rodrigues` 子函数
- **工具箱**：纯 MATLAB

#### ray_triangle_intersection.m
- **作用**：Möller-Trumbore 射线-三角面求交（最近交点）
- **输入**：射线数据+三角网格+候选三角形列表
- **输出**：`intersected_ray_ids`, `intersected_tri_ids`, `intersection_points`
- **工具箱**：纯 MATLAB

#### classifyRemovedTriangles.m
- **作用**：分类需移除的三角面+连通分量聚类+边界顶点提取+边界边连接性
- **输入**：`triangles`, `intersected_tri_ids`, `nozzleOrientation`, `intersected_ray_ids`
- **输出**：`removedFacetsIdx`, `removedFacetsCluster`, `raysCluster`, `boundaryVerticesCluster`, `C`
- **工具箱**：`containers.Map`、`graph`、`conncomp`、`uniquetol`、`ismembertol`

#### recursiveSubdivide.m
- **作用**：递归细分三角面（最长边二分）
- **工具箱**：纯 MATLAB

#### improveShortEdges.m
- **作用**：短边折叠改善网格质量（3 轮，保护边界顶点）
- **工具箱**：`containers.Map`

#### buildOctree.m
- **作用**：构建八叉树空间加速结构
- **工具箱**：纯 MATLAB

#### batchOctreeFilter.m
- **作用**：批量射线-AABB 八叉树遍历，返回每条射线的候选三角形
- **工具箱**：纯 MATLAB

#### createTriangulationFromMatrix.m
- **作用**：N×9 矩阵→MATLAB triangulation 对象
- **工具箱**：`triangulation`

#### createfigures.m
- **作用**：2×2 平铺图（网格+喷嘴锥+TCP路径+形貌演化）→保存 JPEG
- **工具箱**：`figure`、`tiledlayout`、`trisurf`、`quiver3`、`surf`、`fill3`、`colorbar`、`saveas`

#### createvideo.m
- **作用**：JPEG 序列→MPEG-4 视频（30fps）
- **工具箱**：`VideoWriter`

---

## 4. 完整调用图

### 4.1 路径规划管线调用图

```
STL 文件
  │
  ▼
read_stl_file.m                    triangles (N×12)
  │
  ▼
model_process.m                    all_triangles (N×15)
  │                                additive_cluster (1×1 cell)
  │── generateVertexKey()          repairing_clusters (1×K cell)
  │                                bbox (x_min,x_max,y_min,y_max)
  ▼
layer_slice.m                      additive_layerlist
  │── sliceLayers()                repairing_layerlist
  │    │── graph/conncomp/dfsearch  (每层含 [application,layertype,height,polygon])
  │    │── uniquetol/ismembertol
  │    └── bsxfun
  ▼
generate_path.m                    pointlist (N×6)
  │── generate_infill()              [x,y,z,nx,ny,nz]
  │    │── polybuffer()
  │    │── rotate_vertices()
  │    │── polyxpoly()
  │    │── sortrows() + flipud()
  │    └── rotate_vertices()
  │
  │── generate_edge()              velocitylist (N×1 string)
  │    │── boundary() / ishole()
  │    │── uniform_sampling_at_polyline()
  │    │    └── segment_normal_vector + tand(tilt_angle)
  │    └── 沿外/内边界均匀采样
  │
  │── generate_link()              zonelist (N×1 string)
  │    │── meshgrid() + isinterior()  (占据栅格)
  │    │── coordinate2index()
  │    │    └── adjustGoalIfOnEdge()
  │    │── aStarSearch.m ◄──────────────────────────┐
  │    │    │── dynamicWeight()                      │
  │    │    │── heuristic()                          │
  │    │    │── isValidNeighbor()                    │
  │    │    │── getMinFNode()                        │
  │    │    └── reconstructPath()                    │
  │    └── removeColinearPoints()                    │
  │                                                 │
  ▼                                                 │
point_interpretaion.m              moves_matrix (N×6) │
  │── cross() / dot() / norm()      [x,y,z,ax,ay,az] │
  └── atan2d() / cosd() / sind()    (reltool 欧拉角)  │
  │                                                 │
  ▼                                                 │
robot_command_output.m              sprayArea (2×3)   │
  └── fopen/fprintf → ABB Rapid 文件                 │
                                                    │
aStarSearch.m ◄──── 被 generate_path.m 调用 ────────┘
```

### 4.2 形貌预测管线调用图

```
STL 文件                    CFD Excel 文件
  │                              │
  ▼                              ▼
read_STLfile.m              particleFitting.m
  │ stlread()                  │ readmatrix()
  ▼                            │ histcounts2()
triangles (N×9)               │ fittype()/fit()  (Curve Fitting Toolbox)
  │                            ▼
  ▼                    rays_indices, rays_origins, rays_directions,
recursiveSubdivide.m     rays_speeds, rays_possiLengths, rays_Vcr,
  │ (最长边二分)          length_threshold, area_threshold
  ▼                            │
improveShortEdges.m            │
  │ (短边折叠)                 │
  ▼                            │
triangles (精化 N×9)           │
  │                            │
  ├────────────────────────────┘
  │
  │ pointlist.mat + velocitylist.mat (来自路径规划)
  ▼
spotInterp.m                        spotsList (M×7)
  │ containers.Map (速度→补偿系数)    [x,y,z,nx,ny,nz,coef]
  │ cumsum + 线性插值
  ▼
┌─────────────────────────────────────────────────────┐
│  逐步循环 (i = 1 .. steps)                           │
│  │                                                   │
│  ├─ rayMove.m                                       │
│  │   │ Rodrigues 旋转                                │
│  │   └─ moveRays_origins, moveRays_directions,       │
│  │      nozzleOrientation, Coef_THK                  │
│  │                                                   │
│  ├─ buildOctree.m                                   │
│  │   └─ trisOctree (八叉树结构)                       │
│  │                                                   │
│  ├─ batchOctreeFilter.m                             │
│  │   │ ray-AABB 相交测试                              │
│  │   └─ tri_candidates (每射线候选三角形)              │
│  │                                                   │
│  ├─ ray_triangle_intersection.m                     │
│  │   │ Möller-Trumbore 算法                          │
│  │   └─ intersected_ray_ids, intersected_tri_ids,    │
│  │      intersection_points                          │
│  │                                                   │
│  ├─ classifyRemovedTriangles.m                      │
│  │   │ graph + conncomp (连通分量聚类)                │
│  │   └─ removedFacetsIdx, raysCluster,               │
│  │      boundaryVerticesCluster, C                   │
│  │                                                   │
│  ├─ profilePredict.m ◄─────────────────────────┐    │
│  │   │── normalVector()                        │    │
│  │   │── projectPointToPlane()                 │    │
│  │   │── projectToBestPlane()  (PCA + eig)     │    │
│  │   │── adjustCoordinate()    (polyxpoly)     │    │
│  │   │   └── pointSymmetry2D()                 │    │
│  │   │── projectTo2DPlane()                    │    │
│  │   │── delaunayTriangulation() + isInterior()│    │
│  │   │── improveShortEdges.m ◄─────────────────┼────┼──┐
│  │   │   │── generateVertexKey()               │    │  │ (3 轮折叠)
│  │   │   │── labeled_accto_length_threshold()  │    │  │
│  │   │   │── edgeLengthCompare()               │    │  │
│  │   │   └── trianglesArea()                   │    │  │
│  │   └─ oldTriangles, newTriangles             │    │  │
│  │                                             │    │  │
│  ├─ createfigures.m (可选)                     │    │  │
│  │   └─ createTriangulationFromMatrix.m        │    │  │
│  │       └─ triangulation()                    │    │  │
│  │   └─ trisurf/quiver3/surf/fill3 → JPEG      │    │  │
│  │                                             │    │  │
│  └─ triangles = [oldTriangles; newTriangles]   │    │  │
│      (更新网格进入下一步)                         │    │  │
│                                                │    │  │
└────────────────────────────────────────────────┘    │  │
                                                      │  │
improveShortEdges.m ◄── 被 profilePredict.m 调用 ─────┘  │
  └── generateVertexKey/labeled_accto_length_threshold/ │
      edgeLengthCompare/trianglesArea ──────────────────┘
                                                      │
createTriangulationFromMatrix.m ◄── 被 createfigures.m │
  └─ triangulation()                                  │ 调用
                                                      │
createvideo.m                                         │
  └─ VideoWriter → MPEG-4                             │
```

### 4.3 两条管线的数据交接

```
路径规划管线                          形貌预测管线
─────────────                        ─────────────
                                     read_STLfile.m
                                          │
read_stl_file.m                            │
      │                                    │
      ▼                                    ▼
model_process → layer_slice          recursiveSubdivide
      │                              improveShortEdges
      ▼                                    │
generate_path                              │
      │                                    ▼
      ▼                              particleFitting
pointlist.mat ──────────────────►   spotInterp (加载 pointlist.mat)
velocitylist.mat ─────────────────►       │
      │                                    ▼
      ▼                              逐步循环:
point_interpretaion                   rayMove → octree → ray_trace
      │                              → classify → profilePredict
      ▼                                     │
robot_command_output                         ▼
(Rapid 文件)                            createfigures / createvideo
```

---

## 5. 函数调用关系矩阵

| 调用者 ↓ \ 被调用者 → | read_stl | model_process | layer_slice | generate_path | aStarSearch | point_interp | robot_output | read_STL | particleFitting | spotInterp | rayMove | ray_tri_int | classify | recursive | improveShort | buildOctree | batchFilter | createTRI | createfigures | createvideo | profilePredict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `形貌预测\main.m` | ✅ | ✅ | ✅ | ✅ | — | ✅ | ✅ | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `路径规划\main.m` | — | — | — | — | — | — | — | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| `generate_path.m` | — | — | — | — | ✅ | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |
| `profilePredict.m` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✅ | — | — | — | — | — | — |
| `createfigures.m` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | ✅ | — | — | — |
| `matlab_bridge_server.m` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — |

> `matlab_bridge_server.m` 不调用任何算法函数——它仅通过 `pyenv` 启动 Python 的 `MatlabAdapter`。

---

## 6. 工具箱依赖汇总

| 工具箱 | 依赖的函数 | 使用文件 |
|--------|-----------|---------|
| **Mapping Toolbox** | `polyshape`, `polybuffer`, `polyxpoly`, `regions`, `sortregions`, `boundary`, `ishole`, `isinterior` | `generate_path.m` |
| **Mapping Toolbox** | `polyxpoly` | `profilePredict.m` |
| **Curve Fitting Toolbox** | `fittype`, `fit`, `fitoptions`, `feval` | `particleFitting.m` |
| **Statistics & ML Toolbox** | `histcounts2` | `particleFitting.m` |
| MATLAB 基础 | `graph`, `conncomp`, `dfsearch`, `containers.Map`, `uniquetol`, `ismembertol`, `delaunayTriangulation`, `isInterior`, `triangulation`, `stlread` | 多个文件 |

---

## 7. 当前执行状态

```
matlab_bridge_server.m (生产入口)
  │
  └─► pyenv → Python MatlabAdapter.serve()
        │
        └─► _default_algorithm()
              │
              └─► repair_app.core.path_planner.plan_path_from_cloud()
                    │
                    └─► 纯 Python 计算（不调用任何 .m 文件）

所有 22 个 .m 算法文件：❌ 未执行
所有 12 个 matlab_server/ 文件：🗑️ 已弃用
```

**结论**：MATLAB 进程仅作为宿主运行 Python 代码。所有 `.m` 算法文件均不在生产调用链中。
