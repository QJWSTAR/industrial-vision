function [oldTriangles, newTriangles] = profilePredict(triangles, removedFacetsIdx, raysCluster, intersected_tri_ids, intersection_points,...
    boundaryVerticesCluster, nozzleOrientation, moveRays_origins, moveRays_directions, rays_speeds, rays_possiLengths, rays_Vcr, Coef_THK, C,...
    length_threshold)
% Profile predict of the deposits

% Input
% triangles: coordinates of 3 vertices, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix
% removedFacetsIdx: indices of triangles that need to be removed and updated without NaN, N*1 matrix
% raysCluster: indices of rays that collide with connected triangles, 1*N cell, 1*N matrix for each cell
% intersected_tri_ids: indices of triangles that rays hit, N*1 column vector, NaN stands for not intersected
% intersection_points: intersection points of rays and triangles, N*3 matrix, NaN stands for not intersected
% boundaryVerticesCluster: coordinated of the boundary points of connected triangles, 1*N cell, N*3 matrix for each cell
% nozzleOrientation: orientation of the nozzle in this move, [nx, ny, nz], 1*3 matrix
% moveRays_origins: origins of rays after each move, [x, y, z], N*3 matrix
% moveRays_directions: directions of rays after each move, [nx, ny, nz], N*3 matrix
% rays_speeds: speed values of rays, N*3 matrix
% rays_possiLengths: length distribution of rays, N*1 matrix
% rays_Vcr: critical velocity of rays, N*1 matrix
% Coef_THK: coefficent of the thickness, 1*1 double
% C: indices of boundary edges based on boundary points, 1*N cell, N*2 matrix for each cell
% length_threshold: minimum distance of each rays, 1*1 double

% Output
% oldTriangles: triangles not need to be updated, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix
% newTriangles: updated triangles to replace the removed triangles, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix

Coef_VComp = 1;
Parti_QTY = 10;
Parti_THK = 1;
oldTriangles = triangles;
newTriangles = [];

for i = 1:length(raysCluster)
    % calculate the deposits height
    profileSet3D = NaN(length(raysCluster{i}),3);
    for j = 1:length(raysCluster{i})
        n_Facet = normalVector(triangles(intersected_tri_ids(raysCluster{i}(j)), :));
        if abs(dot(n_Facet, rays_speeds(raysCluster{i}(j))*moveRays_directions(raysCluster{i}(j), :))) >= rays_Vcr(raysCluster{i}(j))
            % exceed the critical velocity
            profileSet3D(j, :) = intersection_points(raysCluster{i}(j), :) - ...
                Coef_VComp*moveRays_directions(raysCluster{i}(j), :)*rays_possiLengths(raysCluster{i}(j))*Parti_QTY*Parti_THK*Coef_THK;
        else
            % lower than the critical velocity
            % 100% DE for trial
            profileSet3D(j, :) = intersection_points(raysCluster{i}(j), :) - ...
                Coef_VComp*moveRays_directions(raysCluster{i}(j), :)*rays_possiLengths(raysCluster{i}(j))*Parti_QTY*Parti_THK*Coef_THK;
            % profileSet3D(j, :) = intersection_points(rayCluster{i}(j), :);
        end
    end

    % process the boundary vertices
    nozzleExitCentre = mean(moveRays_origins);
    projectedBoundaryVertices3D = projectPointToPlane(boundaryVerticesCluster{i}, nozzleExitCentre, nozzleOrientation); % project boundary vertices to nozzle exit plane, 3D coordinate 
    [projectedBoundaryVertices2D, T] = projectToBestPlane(projectedBoundaryVertices3D); % project boundary vertices to the best 2D plane, 2D coordinate
    adjusted_projectedBoundaryVertices2D = adjustCoordinate(projectedBoundaryVertices2D, boundaryVerticesCluster{i}, C{i},...
        nozzleExitCentre, nozzleOrientation); % remove the obstructions of upper edges to the lower one
    
    % process the profile vertices
    projectedProfileSet3D = projectPointToPlane(profileSet3D, nozzleExitCentre, nozzleOrientation); % project the profile to nozzle exit plane, 3D coordinate
    projectedProfileSet2D = projectTo2DPlane(projectedProfileSet3D, T); % project the profile to the previous 2D plane, 2D coordinate

    % obtain the connectivity list
    profileVertices2D = [adjusted_projectedBoundaryVertices2D; projectedProfileSet2D]; % merge
    [profileVertices2D, uniqueIdx, ~] = unique(profileVertices2D, 'rows', 'stable'); % duplicate removal
    DT = delaunayTriangulation(profileVertices2D, C{i});
    TF = isInterior(DT);
    eff_ConnectivityList = DT.ConnectivityList(TF, :);

    % 3D connect of both boundary vertices and profile vertices
    profileVertices3D = [boundaryVerticesCluster{i}; profileSet3D];
    profileVertices3D = profileVertices3D(uniqueIdx, :);
    newTriangles_temp = [profileVertices3D(eff_ConnectivityList(:,1),:),...
                         profileVertices3D(eff_ConnectivityList(:,2),:),...
                         profileVertices3D(eff_ConnectivityList(:,3),:)];
    newTriangles_temp = improveShortEdges(newTriangles_temp, boundaryVerticesCluster{i}, length_threshold); % newTriangles optimization
    newTriangles = [newTriangles; newTriangles_temp];
end
oldTriangles(removedFacetsIdx, :) = [];
end

%% Auxiliary Functions
function n_Facet = normalVector(vertices)
% Calculate the normal vector of the triangle facet

% Input
% vertices: coordinates of 3 vertices, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix
% Output
% n_Facet: normal vector, 1*3 row vector

v1 = vertices(4:6) - vertices(1:3);
v2 = vertices(7:9) - vertices(1:3);
n_Facet = cross(v1, v2)/vecnorm(cross(v1, v2));
end

function P = projectPointToPlane(Q, P0, n)
% Calculate the projection of the point on the plane
% Input
% Q: the point to be projected,[x, y, z], N*3 matrix
% P0: a point on a plane, [x0, y0, z0], 1*3 matrix
% n: plane normal vector, [nx, ny, nz], 1*3 matrix
% Output
% P: projected point coordinates [x, y, z], N*3 matrix

P = NaN(size(Q));
for i = 1:size(Q, 1)
    % calculate parameter t
    t = dot(n, Q(i, :) - P0) / dot(n, n);
    % calculate the projection point
    P(i, :) = Q(i, :) - t * n;
end
end

function [proj_points, T] = projectToBestPlane(points)
% Calculate the projection of the point to the best 2D plane

% Input
% points: the point to be projected,[x, y, z], N*3 matrix
% Output
% proj_points: projected point coordinates [x, y, z], N*3 matrix
% T: transformation information, 1*1 structure

% decentralization
centroid = mean(points, 1);
centered = points - centroid;

% calculate the covariance matrix
C = cov(centered);

% calculate eigenvalues and eigenvectors
[V, D] = eig(C);

% sort the eigenvalues in descending order
[eigvals, idx] = sort(diag(D), 'descend');

% the corresponding eigenvector
V_sorted = V(:, idx);

% the eigenvector corresponding to the smallest eigenvalue is the direction of the normal vector.
normal = V_sorted(:, 3)';  % normal vector

% project onto the main plane (the directions of the first two principal components)
basis1 = V_sorted(:, 1)';
basis2 = V_sorted(:, 2)';

% calculate the projection coordinates of the point on the main plane
proj_points_2d = [centered * basis1', centered * basis2'];

% return to the results
proj_points = proj_points_2d;

% (optional) return to the transformation information
T.basis = [basis1; basis2; normal];
T.centroid = centroid;
T.eigvals = eigvals;
end

function adjustedPoints2D = adjustCoordinate(points2D, points3D, segmentIndices, planePoint, planeNormal)
% Adjust the coordinated of the lower edges to avoid the intersection of boundary edges

% Input
% points2D: 2D coordinates of boundary points, N*2 matrix
% points3D: 3D coordinates of boundary points, N*3 matrix
% segmentIndices: the order of connection of boundary edges, N*2 matrix
% planePoint: point on a plane, [x0, y0, z0], 1*3 matrix
% planeNormal: plane normal vector, [nx, ny, nz], 1*3 matrix
% Output
% adjustedPoints2D: adjusted 2D coordinates of boundary points, N*2 matrix

adjustedPoints2D = points2D;
[C, ~, ic] = unique(adjustedPoints2D, 'rows');
for k = 1:length(C)
    idx = find(ic == k);
    if numel(idx) > 1
        adjustedPoints2D(idx(2:end), :) = adjustedPoints2D(idx(2:end), :) + 1e-4;
    end
end

% pairwise testing of all boundary edges
for i = 1:size(segmentIndices, 1)-1
    for j = i+1:size(segmentIndices, 1)
        % boundary edge 1
        seg1_2D = [adjustedPoints2D(segmentIndices(i, 1), :); adjustedPoints2D(segmentIndices(i, 2), :)];
        seg1_3D = [points3D(segmentIndices(i, 1), :); points3D(segmentIndices(i, 2), :)];
        % boundary edge 2
        seg2_2D = [adjustedPoints2D(segmentIndices(j, 1), :); adjustedPoints2D(segmentIndices(j, 2), :)];
        seg2_3D = [points3D(segmentIndices(j, 1), :); points3D(segmentIndices(j, 2), :)];
        % intersection detection
        [x_int, y_int] = polyxpoly(seg1_2D(:, 1), seg1_2D(:, 2), seg2_2D(:, 1), seg2_2D(:, 2));
        if isempty(x_int)
            intersection_2D = [];  % no intersection
        else
            intersection_2D = [x_int(1), y_int(1)]; % intersection
        end

        if ~isempty(intersection_2D)
            % select the boundary edge below
            R1 = (intersection_2D-seg1_2D(1, :))/(seg1_2D(2, :)-seg1_2D(1, :)); % ratio of boundary edge 1
            intersection_3D_seg1 = R1*(seg1_3D(2,:)-seg1_3D(1,:))+seg1_3D(1,:);
            d1_3D = abs(dot(intersection_3D_seg1-planePoint, planeNormal)); % distance from a edge 1 to plane

            R2 = (intersection_2D-seg2_2D(1, :))/(seg2_2D(2, :)-seg2_2D(1, :)); % ratio of boundary edge 2
            intersection_3D_seg2 = R2*(seg2_3D(2,:)-seg2_3D(1,:))+seg2_3D(1,:); 
            d2_3D = abs(dot(intersection_3D_seg2-planePoint, planeNormal));% distance from a edge 2 to plane

            % select the indices of far one the close one 
            if abs(d1_3D-d2_3D) > 1e-8
                furtherIndex = [1,2]*[d1_3D > d2_3D,d1_3D < d2_3D]'; % far edge
                symmetryIndex = [1,2]*[d1_3D < d2_3D,d1_3D > d2_3D]'; % close edge
            else
                furtherIndex = 0;
                symmetryIndex = 0;
            end

            if furtherIndex ~= 0 && symmetryIndex ~= 0
                % choose the nearer endpoint of far edge
                segCombo_2D = {seg1_2D, seg2_2D};
                furtherSeg_2D = segCombo_2D{furtherIndex};
                d1_2D = norm(furtherSeg_2D(1, :) - intersection_2D);
                d2_2D = norm(furtherSeg_2D(2, :) - intersection_2D);
                nearerIndex = [1,2]*[d1_2D<d2_2D,d1_2D>d2_2D]';

                % reflect the points across the symmetry axis
                nearPoint_2D = furtherSeg_2D(nearerIndex, :);
                symmetry_2D = segCombo_2D{symmetryIndex};
                symmetry_2D_P1 = symmetry_2D(1, :);
                symmetry_2D_P2 = symmetry_2D(2, :);
                P_sym2D = pointSymmetry2D(nearPoint_2D, symmetry_2D_P1, symmetry_2D_P2);

                % update the 2D coordinates
                indicesCombo = {segmentIndices(i, :), segmentIndices(j, :)};
                adjustedIndex = indicesCombo{furtherIndex}(nearerIndex);
                adjustedPoints2D(adjustedIndex, :) = P_sym2D;
            end
        end
    end
end
end

function P_sym = pointSymmetry2D(P, A, B)
% Calculate the symmetrical point of a point on a two-dimensional plane with respect to a straight line

% Input
% P: the point to be symmetrized, [x, y], 1*2 matrix
% A: point to determine a straight line, [x, y], 1*2 matrix
% B: point to determine a straight line, [x, y], 1*2 matrix
% Output
% P_sym: the symmetrical point of point P with respect to the straight line AB

% calculate the direction vector of the straight line
dir_vec = B - A;

% calculate the foot of the perpendicular line H
AP = P - A;
t = dot(AP, dir_vec) / dot(dir_vec, dir_vec);
H = A + t * dir_vec;

% calculate the symmetry point
P_sym = 2 * H - P;
end

function points2D = projectTo2DPlane(points3D, T)
% Project the 3D points to a certain 2D plane

% Input
% points3D: 3D coordinates of points, N*3 matrix
% T: transformation information, 1*1 structure
% Output
% points2D: 2D coordinates of points, N*3 matrix

basis1 = T.basis(1, :);
basis2 = T.basis(2, :);

centroid = T.centroid;
centered = points3D - centroid;

points2D = [centered * basis1', centered * basis2'];
end