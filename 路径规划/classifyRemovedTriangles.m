function [removedFacetsIdx, removedFacetsCluster, raysCluster, boundaryVerticesCluster, C] = ...
    classifyRemovedTriangles(triangles, intersected_tri_ids, nozzleOrientation, intersected_ray_ids)
% Extraction of contour points efficiently using hash tables
% Calculate vertex connectivity using an undirected graph

% Input
% triangles: coordinates of 3 vertices, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix
% intersected_tri_ids: indices of triangles that rays hit, N*1 column vector, NaN stands for not intersected
% nozzleOrientation: orientation of the nozzle in this move, [nx, ny, nz], 1*3 matrix
% intersected_ray_ids: indices of rays that intersected with the triangles, N*1 column vector, NaN stands for not intersected
% Output
% removedFacetsIdx: indices of triangles that need to be removed and updated without NaN, N*1 matrix
% removedFacetsCluster: indices of triangles that connect together, 1*N cell, 1*N matrix for each cell
% raysCluster: indices of rays that collide with connected triangles, 1*N cell, 1*N matrix for each cell
% boundaryVerticesCluster: coordinated of the boundary points of connected triangles, 1*N cell, N*3 matrix for each cell
% C: indices of boundary edges based on boundary points, 1*N cell, N*2 matrix for each cell

% no intersecting output
if isempty(intersected_tri_ids)
    removedFacetsIdx = [];
    removedFacetsCluster = {};
    raysCluster = {};
    boundaryVerticesCluster = {};
    return;
end

%% Select the triangles intersected by the rays and the triangles between rays gap
% extract the triangles that rays hit
removedFacetsIdx = unique(intersected_tri_ids(~isnan(intersected_tri_ids)));
removed_triangles = triangles(removedFacetsIdx,:);

% create the map of vertices of triangles that rays hit
removedVerticesMap = containers.Map();
for triIdx = 1:size(removed_triangles, 1)
    removedVertices = reshape(removed_triangles(triIdx, :), 3, 3)';
    for lex = 1:3
        removedVertex = removedVertices(lex,:);
        removedVertexKey = generateVertexKey(removedVertex);
        if ~isKey(removedVerticesMap, removedVertexKey)
            removedVerticesMap(removedVertexKey) = removedVertex;
        end
    end
end

% globally search the triangles between the gap of rays
removedVerticesCounter = zeros(size(triangles,1),1);
for triIdx = 1:size(triangles, 1)
    vertices = reshape(triangles(triIdx, :), 3, 3)';
    for lex = 1:3
        vertex = vertices(lex,:);
        vertexKey = generateVertexKey(vertex);
        if isKey(removedVerticesMap, vertexKey)
            removedVerticesCounter(triIdx) = removedVerticesCounter(triIdx) + 1;
        end
    end
end
[rows, ~] = find(removedVerticesCounter > 1); % If there is even one point of intersection, it is considered as such.
removedFacetsIdx = rows;

% elimilate the impossible triangles for deposition
i = 1;
while i <= length(removedFacetsIdx)
    % if abs(dot(normalVector(triangles(removedFacetsIdx(i), :)), nozzleOrientation)) <= sind(30) % real filtre condition
    if abs(dot(normalVector(triangles(removedFacetsIdx(i), :)), nozzleOrientation)) <= 1e-4 ||...
            abs(dot(normalVector(triangles(removedFacetsIdx(i), :)), [0, 0, 1])) <= 1e-4 % for trial condition
        removedFacetsIdx(i) = [];
    else
        i = i + 1;
    end
end
removed_triangles = triangles(removedFacetsIdx,:);

%% Classify the triangles into different clusters based on the connectivity of edges
% create the map of vertices of all triangles that rays hit and between rays gap,
removedVerticesMap = containers.Map();
for triIdx = 1:size(removed_triangles, 1)
    vertices = reshape(removed_triangles(triIdx, :), 3, 3)';
    for lex = 1:3
        removedVertex = vertices(lex,:);
        removedVertexKey = generateVertexKey(removedVertex);
        if isKey(removedVerticesMap, removedVertexKey)
            removedVertexData = removedVerticesMap(removedVertexKey);
            removedVertexData.triangles = [removedVertexData.triangles, removedFacetsIdx(triIdx)];
            removedVerticesMap(removedVertexKey) = removedVertexData;
        else
            removedVertexData = struct();
            removedVertexData.vertex = removedVertex;
            removedVertexData.triangles = removedFacetsIdx(triIdx);
            removedVerticesMap(removedVertexKey) = removedVertexData;
        end
    end
end

% extract edges
edges = removed_triangles(:, [1:3,4:6,4:6,7:9,7:9,1:3])';
edges = reshape(edges,6,[])';

% extract the edge nodes then sort
start_nodes = edges(:,1:3);
end_nodes = edges(:,4:6);
nodes = [start_nodes; end_nodes];
nodes = uniquetol(nodes,1e-8,'ByRows',true);
nodes = sortrows(nodes,[1 2]);

% extract the indices of 2 nodes of each edge
[~, n1] = ismembertol(start_nodes, nodes, 1e-8, 'ByRows',true);
[~, n2] = ismembertol(end_nodes, nodes, 1e-8, 'ByRows',true);
conn = [n1, n2];

% create the undirected connected graph then calculate every connected component
G = graph(conn(:,1),conn(:,2));
bins = conncomp(G,'OutputForm','cell');

% calculate the indices of conncected triangles
removedFacetsCluster = cell(size(bins));
raysCluster = cell(size(bins));
for i = 1:length(bins)
    for j = 1:length(bins{i})
        vertexKey = generateVertexKey(nodes(bins{i}(j), :));
        removedFacetsCluster{i} = [removedFacetsCluster{i}, removedVerticesMap(vertexKey).triangles];
        removedFacetsCluster{i} = unique(removedFacetsCluster{i});
        raysCluster{i} = intersected_ray_ids(ismember(intersected_tri_ids,removedFacetsCluster{i}))';
    end
end

% calculate the boundary point indices of each conncected triangles
boundaryVerticesCluster = cell(size(removedFacetsCluster)); % pre_allocate storage space
C = cell(size(removedFacetsCluster)); % pre_allocate storage space
for i = 1:length(removedFacetsCluster)
    if isempty(removedFacetsCluster{i})
        boundaryVerticesCluster{i} = [];
        C{i} = [];
    end
    
    % create the edge map
    localEdgesMap = containers.Map();
    for j = 1:length(removedFacetsCluster{i})
        tri = reshape(triangles(removedFacetsCluster{i}(j), :), 3, 3)';
        localEdges = {...
            [tri(1, :); tri(2, :)], ...
            [tri(2, :); tri(3, :)], ...
            [tri(3, :); tri(1, :)]...
            };

        for lex = 1:3
            [localEdges{lex}(1,:), localEdges{lex}(2,:)] = lex_compare(localEdges{lex}(1,:), localEdges{lex}(2,:)); % sort the points in order
        end

        % count the number of occurrences of edges
        for k = 1:3
            localEdge = localEdges{k};
            localEdgeKey = generateEdgeKey(localEdge);

            if isKey(localEdgesMap, localEdgeKey)
                edgeData = localEdgesMap(localEdgeKey);
                edgeData.count = edgeData.count + 1;
                localEdgesMap(localEdgeKey) = edgeData;
            else
                edgeData = struct();
                edgeData.edge = localEdge;
                edgeData.count = 1;
                localEdgesMap(localEdgeKey) = edgeData;
            end
        end
    end

    % search for edges that occur exactly once
    localEdgesKeys = keys(localEdgesMap);
    for key = 1:length(localEdgesKeys)
        edgeData = localEdgesMap(localEdgesKeys{key});
        if edgeData.count == 1
            boundaryVerticesCluster{i} = [boundaryVerticesCluster{i}; edgeData.edge];
        end
    end

    % calculate the indices of boundary edges
    C{i} = boundaryVerticesCluster{i};
    boundaryVerticesCluster{i} = uniquetol(boundaryVerticesCluster{i},1e-8,'ByRows',true);
    [~, n] = ismembertol(C{i}, boundaryVerticesCluster{i}, 1e-8, 'ByRows',true);
    C{i} = reshape(n, 2, [])';
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

function [v1, v2] = lex_compare(v1, v2)
% Compare two vectors in lexicographical order

% Input
% v1: coordinate of the vertex, 1*3 matrix
% v2: coordinate of the vertex, 1*3 matrix
% Output
% v1: updated coordinate of the vertex, 1*3 matrix
% v2: updated coordinate of the vertex, 1*3 matrix

result = 0; % v1 is the same as v2
for k = 1:3
    if v1(k) < v2(k)
        result = -1;
        break;
    elseif v1(k) > v2(k)
        result = 1;
        break;
    end
end
if result == 1
    temp = v1;
    v1 = v2;
    v2 = temp; % v1 is small,v2 is large
end
end

function key = generateEdgeKey(edge)
% Generate the unique key for the edge

% Input
% edge: coordinate of the 2 vertices on the edge, 2*3 matrix
% Output
% key: key of the edge, 1*N character vector

roundedEdge = round(edge / 1e-8) * 1e-8;
key = sprintf('%.8f,%.8f,%.8f-%.8f,%.8f,%.f', ...
    roundedEdge(1,1), roundedEdge(1,2), roundedEdge(1,3), ...
    roundedEdge(2,1), roundedEdge(2,2), roundedEdge(2,3));
end