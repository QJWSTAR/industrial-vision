function tri_candidates = batchOctreeFilter(octree, rays_origins, rays_directions)
% Roughly select the triangles that may collide with the rays

% Input
% octree: triangles data after octree processing
% octree.min_bound: the minimum coordinates of the bounding box, 1*3 row vector
% octree.max_bound: the maximum coordinates of the bounding box, 1*3 row vector
% octree.tri_indices: triangles indices in this node, 1*N row vector
% octree.children: node in the next deep
% octree.is_leaf: is it the deepest node? 1*1 logical
% rays_origins: coordinates of ray origins, N*3 matrix, [x, y, z], N*3 matrix 
% rays_directions: directions of rays, [nx, ny, nz], N*3 matrix
% Output
% tri_candidates: triangle indices that each ray may collide with, N*1 cell, 1*N row vector for each cell

% pre_allocate the result cell array
num_rays = size(rays_origins, 1);
tri_candidates = cell(num_rays, 1);

% process each ray in batches
for i = 1:num_rays
    tri_candidates{i} = traverseOctree(octree, rays_origins(i, :), rays_directions(i, :));
end
end

%% Auxiliary Functions
function candidate = traverseOctree(octree, ray_origin, ray_direction)
% Perform an octree traversal for each ray

% Input
% octree: triangles data after octree processing
% ray_origin: coordinates of one ray origin, N*3 matrix, [x, y, z], 1*3 row vector 
% ray_direction: directions of one ray, [nx, ny, nz], 1*3 row vector
% Output
% candidate: triangle indices that this ray may collide with, 1*N row vector

candidate = [];

% check whether this ray intersect with the node
if ~rayHitsAABB(ray_origin, ray_direction, octree.min_bound, octree.max_bound)
    return;
end

if octree.is_leaf
    % leaf node: return to all triangles
    candidate = octree.tri_indices;
else
    % internal node: traverse all child nodes
    for i = 1:length(octree.children)
        child_candidates = traverseOctree(octree.children(i), ray_origin, ray_direction);
        candidate = [candidate, child_candidates];
    end
end

% duplicate removal
candidate = unique(candidate);
end

function hit = rayHitsAABB(ray_origin, ray_direction, min_b, max_b)
% check whether this ray intersect with the node

% Input
% ray_origin: coordinates of one ray origin, N*3 matrix, [x, y, z], 1*3 row vector 
% ray_direction: directions of one ray, [nx, ny, nz], 1*3 row vector
% min_b: the minimum coordinates of the bounding box, 1*3 row vector
% max_b: the maximum coordinates of the bounding box, 1*3 row vector
% Output
% hit: do the ray hit the bounding box? 1*1 logical

% Initialize the intersection interval to the entire range of real numbers.
t_min = -inf;  % The minimum parameter t that may intersect
t_max = inf;   % The maximum parameter t that may intersect

% process each coordinate axis
for axis = 1:3
    if abs(ray_direction(axis)) < 1e-8
        %tThe ray is parallel to the current axis plane.
        if ray_origin(axis) < min_b(axis) || ray_origin(axis) > max_b(axis)
            hit = false;  % the ray is outside AABB and parallel.
            return;
        end
        % if the ray is within or on the boundary of AABB, continue to check the other axes.
    else
        % calculate the parameter t of the intersection point with the two parallel planes
        inv_d = 1.0 / ray_direction(axis);  % reversal calculation to avoid division by zero
        t1 = (min_b(axis) - ray_origin(axis)) * inv_d;
        t2 = (max_b(axis) - ray_origin(axis)) * inv_d;

        % make sure that t1 is the close point and t2 is the far point.
        if t1 > t2
            temp = t1; t1 = t2; t2 = temp;
        end

        % update the intersecting interval (find the intersection)
        t_min = max(t_min, t1);
        t_max = min(t_max, t2);

        % check whether the interval is valid
        if t_min > t_max
            hit = false;
            return;
        end
    end
end

% final check: whether the intersection interval is valid and t >= 0 (along the ray direction)
hit = t_max >= max(t_min, 0);
end