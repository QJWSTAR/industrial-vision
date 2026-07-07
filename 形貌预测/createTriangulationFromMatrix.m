function TR = createTriangulationFromMatrix(triangles)
% Create Delaunay triangulation from matrix

% Input
% triangles: coordinates of 3 vertices, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix
% Output
% TR: triangulation

% obtain the number of triangles
N = size(triangles, 1);

% reorder vertex data
vertices = reshape(triangles', 3, [])';

% create the connectivity list
indices = 1:3*N;
connectivity = reshape(indices, 3, [])';

% create triangulation object
TR = triangulation(connectivity, vertices);
end