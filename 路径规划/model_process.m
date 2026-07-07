function [all_triangles, addtive_triangles_cluster, repairing_triangles_cluster, x_min,x_max,y_min,y_max] = model_process(triangles, model_scale, tol, base_plane)
% Furthermore calculate the attributes of the triangles after removing the parallel triangles and then classify into of addtive and repairing clusters

% Input
% triangles: attributes of triangle facets, [x1, y1, z1, x2, y2, z2, x3, y3, z3, nx, ny, nz], N*12 matrix
% model_scale: zoom in model, 1*1 double
% tol: tolerance, 1*1 double
% base_plane: height of the reference plane, 1*1 double
% Output
% all_triangles: further attributes of triangle facets, [x1, y1, z1, x2, y2, z2, x3, y3, z3, nx, ny, nz, minz, maxz, angle], N*15 matrix
% addtive_triangles_cluster: the clusters of addtive triangles above the base plane, 1*1 cell, N*15 matrix for the cell
% repairing_triangles_cluster: the clusters of repairing triangles below the base plane, 1*N cell, N*15 matrix for each cell
% x_min: the minimum coordinates along X axis of the triangles, 1*1 double
% x_max: the maximum coordinates along X axis of the triangles, 1*1 double
% y_min: the minimum coordinates along Y axis of the triangles, 1*1 double
% y_max: the maximum coordinates along Y axis of the triangles, 1*1 double

%% Model Data Processing
% zoom model
if model_scale~=1
    triangles=triangles*model_scale;
end

% Caculate min_z and max_z for each mesh
triangles = [triangles(:,1:12),min(triangles(:,[3 6 9]),[],2), max(triangles(:,[ 3 6 9]),[],2)];
% Remove the triangles parallel to the slicing plane
triangle_parallel_index = triangles(:,14)-triangles(:,13) <= tol;
triangles(triangle_parallel_index,:) = [];
% Caculate angle for each mesh(not the normal)
all_triangles = [triangles,atand(sqrt(triangles(:,10).^2+triangles(:,11).^2)./triangles(:,12))];
% Caculate model x_min x_max y_min y_max for whole model
x_min=min(min(triangles(:,1:3:9)));
x_max=max(max(triangles(:,1:3:9)));
y_min=min(min(triangles(:,2:3:9)));
y_max=max(max(triangles(:,2:3:9)));

% select the additive and repairing triangles
addtive_indices = false(size(all_triangles,1), 1);
repairing_indices = false(size(all_triangles,1), 1);
for i = 1:size(all_triangles,1)
    if all_triangles(i, 14) >= base_plane
        addtive_indices(i) = true;
    end
    if all_triangles(i, 13) <= base_plane
        repairing_indices(i) = true;
    end
end
addtive_triangles = all_triangles(addtive_indices, :);
repairing_triangles = all_triangles(repairing_indices, :);

%% Classify the triangles into different clusters based on the connectivity of edges
% repairing_triangles_cluster
% create the map of vertices of all triangles
repairing_triangles_map = containers.Map();
for triIdx = 1:size(repairing_triangles, 1)
    vertices = reshape(repairing_triangles(triIdx, 1:9), 3, 3)';
    for lex = 1:3
        repairingVertex = vertices(lex,:);
        repairingVertexKey = generateVertexKey(repairingVertex);
        if isKey(repairing_triangles_map, repairingVertexKey)
            repairingVertexData = repairing_triangles_map(repairingVertexKey);
            repairingVertexData.triIDX = [repairingVertexData.triIDX, triIdx];
            repairing_triangles_map(repairingVertexKey) = repairingVertexData;
        else
            repairingVertexData = struct();
            repairingVertexData.vertex = repairingVertex;
            repairingVertexData.triIDX = triIdx;
            repairing_triangles_map(repairingVertexKey) = repairingVertexData;
        end
    end
end

% extract edges
edges = repairing_triangles(:, [1:3,4:6,4:6,7:9,7:9,1:3])';
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
repairing_triangles_IDXcluster = cell(size(bins));
for i = 1:length(bins)
    for j = 1:length(bins{i})
        vertexKey = generateVertexKey(nodes(bins{i}(j), :));
        repairing_triangles_IDXcluster{i} = [repairing_triangles_IDXcluster{i}, repairing_triangles_map(vertexKey).triIDX];
        repairing_triangles_IDXcluster{i} = unique(repairing_triangles_IDXcluster{i});
    end
end
repairing_triangles_cluster = cell(size(repairing_triangles_IDXcluster));
for i = 1:length(cell(size(repairing_triangles_IDXcluster)))
    repairing_triangles_cluster{i} = repairing_triangles(repairing_triangles_IDXcluster{i}, :);
end

% repairing_triangles_cluster
addtive_triangles_cluster{1} = addtive_triangles;
end

%% Auxiliary Function
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