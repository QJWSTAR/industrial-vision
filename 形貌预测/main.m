%% Read STL File
tic
stlfilename = 'substrate.stl';         % CHECK
triangles = read_STLfile(stlfilename); % CHECK
substrate_triangles = triangles;
triangles = recursiveSubdivide(triangles, 5);
triangles = improveShortEdges(triangles, [], 1.5);
timersf = toc;
fprintf('Read stl file done, %.4f sec elapsed\n',timersf);

%% Generate Rays
tic
excelFile = 'substrate-surface.xlsx'; % CHECK
SoD = 30;                             % CHECK
[rays_indices, rays_origins, rays_directions, rays_speeds, rays_possiLengths, rays_Vcr,...
    length_threshold, ~] = particleFitting(excelFile, SoD);
timegr = toc;
fprintf('Generate rays done, %.4f sec elapsed\n',timegr);

%% Intercept Spots
tic
load('pointlist.mat');
load('velocitylist.mat');
spot_step_size = 2;             % CHECK
ReferencePoint = [0,0,0,0,0,0]; % CHECK
spotsList = spotInterp(ReferencePoint, pointlist, velocitylist, spot_step_size);
timeis = toc;
fprintf('Intercept spots done, %.4f sec elapsed\n',timeis);

%% Predict Profile
tic
path = '../Matlab图片保存/'; % Relative path from 形貌预测/ to project root image dir
savefigure = false;                                          % CHECK
f = waitbar(0,'Please wait...','Name','Profile Predict');
pause(.8)
steps = size(spotsList, 1);
for i = 1:steps
    waitbar(i/steps,f,sprintf('Processing: i = %d (%d%% completed)', i, min(round((i-1)/steps*100), 99)));
    [moveRays_origins, moveRays_directions, nozzleOrientation, Coef_THK] = rayMove(spotsList(i, :), rays_origins, rays_directions);
    trisOctree = buildOctree(triangles, 6, 8);
    tri_candidates = batchOctreeFilter(trisOctree, moveRays_origins, moveRays_directions);
    [intersected_ray_ids, intersected_tri_ids, intersection_points] = ...
        ray_triangle_intersection(rays_indices, moveRays_origins, moveRays_directions, triangles, tri_candidates);
    [removedFacetsIdx, ~, raysCluster, boundaryVerticesCluster, C] = ...
        classifyRemovedTriangles(triangles, intersected_tri_ids, nozzleOrientation, intersected_ray_ids);
    [oldTriangles, newTriangles] = profilePredict(triangles, removedFacetsIdx, raysCluster, intersected_tri_ids, intersection_points,...
        boundaryVerticesCluster, nozzleOrientation, moveRays_origins, moveRays_directions, rays_speeds, rays_possiLengths, rays_Vcr, Coef_THK, C,...
        length_threshold);
    createfigures(savefigure, i, oldTriangles, newTriangles, moveRays_origins, nozzleOrientation, substrate_triangles, spotsList(max(i-100, 1):i, 1:3), path);
    triangles = [oldTriangles; newTriangles];
end
waitbar(i/steps,f,'100% finishing');
pause(.8)
close(f)
timepp= toc;
fprintf('Predict profile done, %.4f sec elapsed\n',timepp);

%% View the triangles
figure;
TR = createTriangulationFromMatrix(triangles);
trisurf(TR);
axis equal;

%% View the new triangles
figure;
TR = createTriangulationFromMatrix(newTriangles);
trisurf(TR);
axis equal;

%% Create video
savevideo = false; % CHECK
createvideo(savevideo, path, steps);