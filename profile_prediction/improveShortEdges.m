function triangles = improveShortEdges(triangles, boundary_vertices, length_threshold)
% Improve triangles with short edges

% Input
% triangles: coordinates of triangles to be improved, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix
% boundary_vertices: coordinated of the boundary points, N*3 matrix
% length_threshold: minimum distance, 1*1 double
% Output
% triangles: coordinates of triangles after improvement, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix

for loop  = 1:3
    % Create the vertex map
    newTriangles_keys = cell(size(triangles, 1), 3);
    vertex_map = containers.Map('KeyType', 'char', 'ValueType', 'any');
    if isempty(boundary_vertices)
        for i = 1:size(triangles, 1)
            for ii = 1:3
                vertex = triangles(i, (ii-1)*3+1:(ii-1)*3+3);
                vertex_key = generateVertexKey(vertex);
                newTriangles_keys{i, ii} = vertex_key;
                if ~isKey(vertex_map, vertex_key)
                    vertex_info = struct();
                    vertex_info.value = vertex;
                    vertex_info.isboundary = false;
                    vertex_info.isprocessed = false;
                    vertex_map(vertex_key) = vertex_info;
                end
            end
        end
    else
        for i = 1:size(triangles, 1)
            for ii = 1:3
                vertex = triangles(i, (ii-1)*3+1:(ii-1)*3+3);
                vertex_key = generateVertexKey(vertex);
                newTriangles_keys{i, ii} = vertex_key;
                if ~isKey(vertex_map, vertex_key)
                    vertex_info = struct();
                    vertex_info.value = vertex;
                    vertex_info.isboundary = ismember(vertex, boundary_vertices, 'rows');
                    vertex_info.isprocessed = false;
                    vertex_map(vertex_key) = vertex_info;
                end
            end
        end
    end

    % Label the triangles with short edges
    Llabels = labeled_accto_length_threshold(triangles, length_threshold);
    selectedTriangles = triangles(Llabels, :);

    % Improve the triangles with short edges
    for j = 1:size(selectedTriangles, 1)
        [v1, v2] = edgeLengthCompare(selectedTriangles(j, :));
        vertex1_key = generateVertexKey(v1);
        vertex2_key = generateVertexKey(v2);
        if ~vertex_map(vertex1_key).isprocessed && ~vertex_map(vertex2_key).isprocessed

            % neither is boundary vertex
            if ~vertex_map(vertex1_key).isboundary && ~vertex_map(vertex2_key).isboundary
                % vertex 1
                vertex_info1 = vertex_map(vertex1_key);
                vertex_info1.value = (v1+v2)/2;
                vertex_info1.isprocessed = true;
                vertex_map(vertex1_key) = vertex_info1;
                % vertex 2
                vertex_info2 = vertex_map(vertex2_key);
                vertex_info2.value = (v1+v2)/2;
                vertex_info2.isprocessed = true;
                vertex_map(vertex2_key) = vertex_info2;

            % v2 is boundary vertex
            elseif ~vertex_map(vertex1_key).isboundary && vertex_map(vertex2_key).isboundary
                % vertex 1
                vertex_info1 = vertex_map(vertex1_key);
                vertex_info1.value = v2;
                vertex_info1.isprocessed = true;
                vertex_map(vertex1_key) = vertex_info1;

            % v1 is boundary vertex
            elseif vertex_map(vertex1_key).isboundary && ~vertex_map(vertex2_key).isboundary
                % vertex 2
                vertex_info2 = vertex_map(vertex2_key);
                vertex_info2.value = v1;
                vertex_info2.isprocessed = true;
                vertex_map(vertex2_key) = vertex_info2;
            end
        end
    end

    % Restore the improved thin triangles
    for k = 1:size(triangles, 1)
        for kk = 1:3
            triangles(k, (kk-1)*3+1:(kk-1)*3+3) = vertex_map(newTriangles_keys{k, kk}).value;
        end
    end

    % Eliminate the degenerate triangles (area of zero)
    areas = trianglesArea(triangles);
    isdegenerate = areas < 1e-8;
    triangles = triangles(~isdegenerate, :);
end
end

%% Auxiliary Functions
function key = generateVertexKey(vertex)
% Generate the unique key for the vertex

% Input
% vertex: coordinate of the vertex, 1*3 matrix
% Output
% key: key of the vertex, 1*N character vector

roundedVertex = round(vertex / 1e-8) * 1e-8;
key = sprintf('%.8f,%.8f,%.8f', ...
    roundedVertex(1,1), roundedVertex(1,2), roundedVertex(1,3));
end

function Llabels = labeled_accto_length_threshold(triangles, length_threshold)
% Label the triangles that have short edges.

% Input
% triangles: coordinates of 3 vertices, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix
% length_threshold: minimum length of edge, 1*1 double
% Output
% Llabels: is triangle with short edge? N*1 logical matrix

n_tris = size(triangles, 1);
Llabels = zeros(n_tris, 1, 'logical');
for i = 1:n_tris
    % extract three vertices
    v1 = triangles(i, 1:3);
    v2 = triangles(i, 4:6);
    v3 = triangles(i, 7:9);

    % calculate edge lengths
    e1 = norm(v2 - v1);
    e2 = norm(v3 - v2);
    e3 = norm(v1 - v3);

    % label the triangles
    is_short = e1 < length_threshold || e2 < length_threshold || e3 < length_threshold;
    if is_short
        Llabels(i) = true;
    else
        Llabels(i) = false;
    end
end
end

function [v1, v2] = edgeLengthCompare(triangle)
% Select the 2 vertices of the shortest edge in an triangle

% Input
% triangle: coordinates of 3 vertices, [x1, y1, z1, x2, y2, z2, x3, y3, z3], 1*9 matrix
% Output
% v1: coordinate of one vertex of the shortest edge, 1*3 matrix
% v2: coordinate of another vertex of the shortest edge, 1*3 matrix

% extract three vertices
v1 = triangle(1, 1:3);
v2 = triangle(1, 4:6);
v3 = triangle(1, 7:9);

% calculate edge lengths
edge1_length = norm(v2-v1);
edge2_length = norm(v3-v2);
edge3_length = norm(v1-v3);

% select the 2 vertices
verticeCombo = {[v1; v2]; [v2; v3]; [v3; v1]};
[~, idxMinLengh] = min([edge1_length; edge2_length; edge3_length]);
selectedVertices = verticeCombo{idxMinLengh};
v1 = selectedVertices(1, :);
v2 = selectedVertices(2, :);
end

function areas = trianglesArea(triangles)
% Calculate the areas of triangles

% Input
% triangles: coordinates of 3 vertices, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix
% Output
% areas: areas of the triangles, N*1 matrix

% extract three vertices
p1 = triangles(:, 1:3);
p2 = triangles(:, 4:6);
p3 = triangles(:, 7:9);

% calculate the two edge vectors
v1 = p2 - p1;
v2 = p3 - p1;

% calculate the magnitude of the cross product (twice the area of the triangle)
cross_prod = cross(v1, v2, 2);
areas = 0.5 * sqrt(sum(cross_prod.^2, 2));
end