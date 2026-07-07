function [intersected_ray_ids, intersected_tri_ids, intersection_points] = ray_triangle_intersection(...
    rays_indices, rays_origins, rays_directions, triangles, tri_candidates)
% Calculate the intersention point between the ray and the possible intersected triagnles

% Input
% rays_indices: indices of rays, N*1 matrix
% rays_origins: coordinates of rays origins, N*3 matrix, [x, y, z], N*3 matrix 
% rays_directions: directions of rays, [nx, ny, nz], N*3 matrix
% triangles: coordinates of 3 vertices, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix
% tri_candidates: triangle indices that each ray may collide with, N*1 cell, 1*N row vector for each cell
% Output
% intersected_ray_ids: indices of rays that intersected with the triangles, N*1 column vector, NaN stands for not intersected
% intersected_tri_ids: indices of triangles that rays hit, N*1 column vector, NaN stands for not intersected
% intersection_points: intersection points of rays and triangles, N*3 matrix, NaN stands for not intersected

% pre_allocate storage space
num_rays = size(rays_origins,1);
intersected_tri_ids = nan(num_rays, 1);
intersection_points = nan(num_rays, 3);

% intersection detection
for i = 1:num_rays
    % extract a single ray
    ray_origin = rays_origins(i,:);
    ray_direction = rays_directions(i,:);
    candidate_ids = tri_candidates{i};

    % initialization of intersection solution
    min_t = inf;
    best_tri_id = 0;

    for tri_id = candidate_ids
        % extract the vertices of triangle
        tri = triangles(tri_id, :);
        v0 = tri(1:3); v1 = tri(4:6); v2 = tri(7:9);

        % fast intersection detection, Möller–Trumbore algorithm
        edge1 = v1 - v0;
        edge2 = v2 - v0;
        P = cross(ray_direction, edge2);
        det = dot(edge1, P);

        if abs(det) < 1e-8
            continue; % parellel
        end

        % intersection condition: t > 0; 0 <= u,v <= 1; u+v <= 1
        inv_det = 1/det;
        T = ray_origin - v0;
        u = dot(T, P) * inv_det;

        if u < 0 || u > 1
            continue; % outside the triangle
        end

        Q = cross(T, edge1);
        v = dot(ray_direction, Q) * inv_det;

        if v < 0 || u + v > 1
            continue; % outside the triangle
        end

        t = dot(edge2, Q) * inv_det;

        % update t
        if t > 1e-8 && t < min_t
            min_t = t;
            best_tri_id = tri_id;
        end
    end

    if best_tri_id > 0
        intersected_tri_ids(i) = best_tri_id;
        intersection_points(i, :) = ray_origin + min_t * ray_direction;
    end
end

intersection = isnan(intersected_tri_ids);
intersected_ray_ids = rays_indices;
intersected_ray_ids(intersection) = NaN;
end