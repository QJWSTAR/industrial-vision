function node = buildOctree(triangles, max_depth, max_tri_per_node)
% Simplified version of octree construction - adapted to N*9 format

% Input
% triangles: coordinates of 3 vertices, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix
% max_depth: maximum recursion depth, 1*1 double
% max_tri_per_node: threshold for the number of triangles within a node, 1*1 double
% Output
% node: triangles data after octree processing
% node.min_bound: the minimum coordinates of the bounding box, 1*3 row vector
% node.max_bound: the maximum coordinates of the bounding box, 1*3 row vector
% node.tri_indices: triangles indices in this node, 1*N row vector
% node.children: node in the next deep
% node.is_leaf: is it the deepest leaf node? 1*1 logical

% calculate the bounding box
all_verts = [triangles(:, 1:3); triangles(:, 4:6); triangles(:, 7:9)];
min_bound = min(all_verts);
max_bound = max(all_verts);

% expand the bounding box
padding = 0.01 * (max_bound - min_bound);
min_bound = min_bound - padding;
max_bound = max_bound + padding;

% calculate all the triangle indices
tri_indices = 1:size(triangles, 1);

% recursive construction
node = buildNode(triangles, min_bound, max_bound, tri_indices, 1, max_depth, max_tri_per_node);
end

%% Auxiliary Functions
function node = buildNode(triangles, min_b, max_b, tri_indices, depth, max_depth, max_tri)
% Construct the recursive nodes

% Input
% triangles: coordinates of 3 vertices, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix
% min_b: the minimum coordinates of the bounding box, 1*3 row vector
% max_b: the maximum coordinates of the bounding box, 1*3 row vector
% tri_indices: triangles indices in this node, 1*N row vector
% depth: the deepth of this mode, 1*1 double
% max_depth: maximum recursion depth, 1*1 double
% max_tri: threshold for the number of triangles within a node, 1*1 double
% Output
% node: triangles data after octree processing
% node.min_bound: the minimum coordinates of the bounding box, 1*3 row vector
% node.max_bound: the maximum coordinates of the bounding box, 1*3 row vector
% node.tri_indices: triangles indices in this node, 1*N row vector
% node.children: node in the next deep
% node.is_leaf: is it the deepest leaf node? 1*1 logical

node = struct();
node.min_bound = min_b;
node.max_bound = max_b;
node.tri_indices = tri_indices;
node.children = [];
node.is_leaf = true;

% termination condition: reach the maximum depth or the number of triangles is sufficiently small
if depth >= max_depth || length(tri_indices) <= max_tri
    return;
end

% calculate the center point
center = (min_b + max_b) / 2;

% allocate triangles for 8 child nodes
child_tris = cell(1, 8);
for octant = 1:8
    % calculate the bounding box of the child nodes
    [child_min, child_max] = getChildBounds(min_b, max_b, center, octant);
    child_tris{octant} = [];

    for i = 1:length(tri_indices)
        tri_idx = tri_indices(i);
        tri_verts = reshape(triangles(tri_idx, :), 3, 3)';
        % simple AABB overlap detection
        if simpleAABBOverlap(tri_verts, child_min, child_max)
            child_tris{octant} = [child_tris{octant}, tri_idx];
        end
    end
end

% build child nodes
for octant = 1:8
    if ~isempty(child_tris{octant})
        [child_min, child_max] = getChildBounds(min_b, max_b, center, octant);
        child_node = buildNode(triangles, child_min, child_max, ...
            child_tris{octant}, depth+1, max_depth, max_tri);
        node.children = [node.children, child_node];
    end
end

node.is_leaf = isempty(node.children);
end

function [child_min, child_max] = getChildBounds(parent_min, parent_max, center, octant)
% Obtain the bounding box of the child nodes

% Input
% parent_min: the minimum coordinates of the parent bounding box, 1*3 row vector
% parent_max: the maximum coordinates of the parent bounding box, 1*3 row vector
% center: the center coordinates of the parent bounding box, 1*3 row vector
% octant: index of the child node among the 8 nodes, 1*1 double 
% Output
% child_min: the minimum coordinates of the child bounding box, 1*3 row vector
% child_max: the maximum coordinates of the child bounding box, 1*3 row vector

child_min = parent_min;
child_max = parent_max;

% adjust the bouding box according to the octant number.
if bitget(octant-1, 1)  % x axis
    child_min(1) = center(1);
else
    child_max(1) = center(1);
end

if bitget(octant-1, 2)  % y axis
    child_min(2) = center(2);
else
    child_max(2) = center(2);
end

if bitget(octant-1, 3)  % z axis
    child_min(3) = center(3);
else
    child_max(3) = center(3);
end
end

function overlap = simpleAABBOverlap(tri_verts, min_b, max_b)
% Simplified triangle-AABB overlap detection

% Input
% tri_verts: coordinates of 3 vertices of a triangle, 3*3 matrix
% min_b: the minimum coordinates of the bounding box, 1*3 row vector
% max_b: the maximum coordinates of the bounding box, 1*3 row vector
% Output
% overlap: do the triangle and the bounding box overlap? 1*1 logical

tri_min = min(tri_verts);
tri_max = max(tri_verts);

% simple AABB overlap detection
overlap = all(tri_min <= max_b) && all(tri_max >= min_b);
end