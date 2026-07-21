function [pointlist, velocitylist, zonelist] = generate_path(additive_layerlist, repairing_layerlist,...
    buffer_additive, buffer_repairing, scanning_angle, scanning_step,...
    edge_step_size, tilt_angle, x_min, x_max, y_min, y_max, linkPath_freeDistance, resolution)
% Generate the additive and repairing paths based on the polygon cell in layerlist

% Input
% additive_layerlist: layerlist of triangles above the base plane, 1*1 cell, N*4 cell for the cell,...
%                     [application, slicing method, height, polygon], including empty matrix ([])
% repairing_layerlist: layerlist of triangles below the base plane, 1*N cell, N*4 cell for each cell,...
%                      [application, slicing method, height, polygon], including empty matrix ([])
% buffer_additive: buffering distance for the additive polygon above the base plane to generate infill path, 1*1 double
% buffer_repairing: buffering distance for the repairing polygon below the base plane to generate infill path, 1*1 double
% scanning_angle: direction of Zig-Zag infill path, in degree system, 1*1 double
% scanning_step: distance between scanning lines of Zig-Zag infill path, 1*1 double
% edge_step_size: step size of edge compensation inclined spraying between neighbouring spots, 1*1 double
% tilt_angle: angle of edge compensation inclined spraying, 1*1 double
% x_min: the minimum coordinates along X axis of the triangles, 1*1 double
% x_max: the maximum coordinates along X axis of the triangles, 1*1 double
% y_min: the minimum coordinates along Y axis of the triangles, 1*1 double
% y_max: the maximum coordinates along Y axis of the triangles, 1*1 double
% linkPath_freeDistance: the activity range of link path relative to the range of model, 1*1 double
% resolution: the resolution of the substrate obstacle map, 1*1 double
% Output
% pointlist: planned spray spots in ABB reltool moving instructions before interpolation for profile prediction, [x,y,z,nx,ny,nz], N*6 matrix
% velocitylist: name of speeddata in ABB moving instructions, N*1 string
% zonelist: name of zonedata in ABB moving instructions, N*1 string

% initialize
pointlist = [];
velocitylist = strings(0,0);
zonelist = strings(0,0);

layerlist = [vertcat(repairing_layerlist{:}); vertcat(additive_layerlist{:})];
demarcation = size(vertcat(repairing_layerlist{:}), 1); % index for dividing additive and repairing

warning('off','MATLAB:polyshape:repairedBySimplify');
for i = 1:size(layerlist,1)
    % generate polygons
    polygon_in = polyshape(layerlist{i,4},'Simplify',true);
    polygon_out = regions(sortregions(polygon_in, "centroid", "ascend", "ReferencePoint", [0,0])); % Divide into different regions, N*1 polyshape
    
    % Loop of regions
    regionCounter = 0; % region counter
    for j = (mod(i, 2) == 1)*(1:length(polygon_out)) + (mod(i, 2) == 0)*(length(polygon_out):-1:1)
        regionCounter = regionCounter + 1;
        if i <= demarcation % repairing
            [infill_points, infill_velocity, infill_zone] = generate_infill(polygon_out(j), buffer_repairing, scanning_angle, scanning_step, i, layerlist{i,3});
            [edge_points, edge_velocity, edge_zone] = deal([]);
            [link_points, link_velocity, link_zone] = deal([]);
        else % additive
            [infill_points, infill_velocity, infill_zone] = generate_infill(polygon_out(j), buffer_additive, scanning_angle, scanning_step, i, layerlist{i,3});
            [edge_points, edge_velocity, edge_zone] = generate_edge(infill_points, polygon_out(j), buffer_additive, edge_step_size, layerlist{i,3}, tilt_angle);
            [link_points, link_velocity, link_zone] = generate_link(regionCounter, x_min, x_max, y_min, y_max, linkPath_freeDistance, resolution,...
                polygon_out, pointlist, infill_points, layerlist{i,3});
        end

        % Update the list
        pointlist = [pointlist; link_points; infill_points; edge_points];
        velocitylist = [velocitylist; link_velocity; infill_velocity; edge_velocity];
        zonelist = [zonelist; link_zone; infill_zone; edge_zone];
    end
end
warning('on','MATLAB:polyshape:repairedBySimplify');
end

%% Auxiliary Functions
function [infill_points, infill_velocity, infill_zone] = generate_infill(polygon, buffer_distance, scanning_angle, scanning_step, layerID, z_slice)
% Generate the infill path

% Input
% polygon: the closed polygon shape, 1*1 polyshape
% buffer_distance: buffering distance for the polygon to generate infill path, 1*1 double
% scanning_angle: direction of Zig-Zag infill path, in degree system, 1*1 double
% scanning_step: distance between scanning lines of Zig-Zag infill path, 1*1 double
% layerID: index of the laylist, 1*1 double
% z_slice: slice height, 1*1 double
% Output
% infill_points: points of infill path, [x,y,z,nx,ny,nz], N*6 matrix
% infill_velocity: name of speeddata of infill path, N*1 string
% infill_zone: name of zonedata of infill path, N*1 string

% Create the buffer
polygon_infill = polybuffer(polygon,-buffer_distance,'JointType','miter','MiterLimit',3);
polygon_infill.Vertices= rotate_vertices(polygon_infill.Vertices,-scanning_angle);
min_x_polygon_infill = min(polygon_infill.Vertices(:,1));
max_x_polygon_infill = max(polygon_infill.Vertices(:,1));
min_y_polygon_infill = min(polygon_infill.Vertices(:,2));
max_y_polygon_infill = max(polygon_infill.Vertices(:,2));

% Create the scanning lines
scan_lines = min_y_polygon_infill:scanning_step:max_y_polygon_infill;
scan_lines = scan_lines + 1/2*(max_y_polygon_infill-scan_lines(end));
scanning_points = zeros(2*size(scan_lines,2),2);
for i = 1:size(scanning_points,1)
    if mod(i,4) == 1
        scanning_points(i,1) = min_x_polygon_infill-5;
    elseif mod(i,4) == 2
        scanning_points(i,1) = max_x_polygon_infill+5;
    elseif mod(i,4) == 3
        scanning_points(i,1) = max_x_polygon_infill+5;
    else
        scanning_points(i,1) = min_x_polygon_infill-5;
    end
    scanning_points(i,2) = scan_lines(1,ceil(i/2));
end

% Calculate the infill points
infill_points = []; % initialize after every iteration
[infill_points(:,1),infill_points(:,2)] = polyxpoly(scanning_points(:,1),scanning_points(:,2),...
    polygon_infill.Vertices([1:end,1],1),polygon_infill.Vertices([1:end,1],2),'unique'); % need ranking
% First rank by y and then second by x (odd rows in ascending order, even rows in descending order)
infill_points = sortrows(round(infill_points,4),[2,1]); % first y, then x
% Reverse the x order for even rows
[~,infill_idx] = unique(infill_points(:,2)); % find the starting index of each row
for m = 2:2:length(infill_idx)
    infill_start_idx = infill_idx(m);
    if m < length(infill_idx)
        infill_end_idx = infill_idx(m+1)-1;
    else
        infill_end_idx = size(infill_points,1);
    end
    infill_points(infill_start_idx:infill_end_idx,:) = flipud(infill_points(infill_start_idx:infill_end_idx,:));
end

% Add the layer height and the normal vector
infill_points = rotate_vertices(infill_points,scanning_angle);
if mod(layerID, 2) == 0
    infill_points = flipud(infill_points); % reduce regional crossing
end
infill_points = [infill_points,ones(size(infill_points,1),1)*z_slice,...
    zeros(size(infill_points,1),2),ones(size(infill_points,1),1)];
infill_velocity = repmat("velocity_infill", [size(infill_points,1),1]);
infill_zone = repmat("zone_infill", [size(infill_points,1),1]);
end

function [polygon_vertices_rotated] = rotate_vertices(polygon_vertices, scanning_angle)
% Rotate the vertices of polygon around [0,0]

% Input
% polygon_vertices: vertices of the polygon, N*2 matrix
% scanning_angle: direction of Zig-Zag infill path, in degree system, 1*1 double
% Output
% polygon_vertices_rotated: rotated vertices of the polygon, N*2 matrix

% Rotate the point around [0,0] by degree
R_forward = [cosd(scanning_angle), sind(scanning_angle); -sind(scanning_angle), cosd(scanning_angle)];
polygon_vertices_rotated = polygon_vertices*R_forward;
end

function [edge_points, edge_velocity, edge_zone] = generate_edge(infill_points, polygon, buffer_distance, edge_step_size, z_slice, tilt_angle)
% Generate the edge path

% Input
% infill_points: points of infill path, [x,y,z,nx,ny,nz], N*6 matrix
% polygon: the closed polygon shape, 1*1 polyshape
% buffer_distance: buffering distance for the polygon to generate infill path, 1*1 double
% edge_step_size: step size of edge compensation inclined spraying between neighbouring spots, 1*1 double
% z_slice: slice height, 1*1 double
% tilt_angle: angle of edge compensation inclined spraying, 1*1 double
% Output
% edge_points: points of edge path, [x,y,z,nx,ny,nz], N*6 matrix
% edge_velocity: name of speeddata of edge path, N*1 string
% edge_zone: name of zonedata of edge path, N*1 string

% Calculate the edge points
infill_end_point = infill_points(end,1:2);% Extract the ending coordinates
polygon_contour_outer = [];
polygon_contour_inner = [];
[polygon_contour_outer(:,1), polygon_contour_outer(:,2)] = boundary(polygon, find(ishole(polygon) == 0,1)); % outer boundary vertices
polygon_contour_outer = polygon_contour_outer(1:end-1,:);
if ~isempty(find(ishole(polygon) == 1,1))
    [polygon_contour_inner(:,1), polygon_contour_inner(:,2)] = boundary(polygon, find(ishole(polygon) == 1,1)); % inner boundary vertices
    polygon_contour_inner = polygon_contour_inner(1:end-1,:);
end

% Find the nearest points both on inner and outer boundaries
polygon_contour_outer_filtered = polygon_contour_outer...
    (abs(polygon_contour_outer(:, 1) - infill_end_point(1, 1)) <= 3*buffer_distance |...
    abs(polygon_contour_outer(:, 2) - infill_end_point(1, 2)) <= 3*buffer_distance,:);% radius scanning
[~, row_outer_filtered_idx] = min(vecnorm(polygon_contour_outer_filtered - infill_end_point, 2, 2), [], 1, 'linear');
polygon_contour_outer_start = polygon_contour_outer_filtered(row_outer_filtered_idx, :);
[row_outer_idx, ~] = find(all(polygon_contour_outer == polygon_contour_outer_start, 2));
polygon_contour_outer = polygon_contour_outer([row_outer_idx:end,1:row_outer_idx-1], :);
polygon_contour_outer = polygon_contour_outer([1:end, 1], :);

if isempty(polygon_contour_inner)
    polygon_contour_inner = [];% there may not be a hole
else
    polygon_contour_inner_filtered = polygon_contour_inner...
        (abs(polygon_contour_inner(:, 1) - infill_end_point(1, 1)) <= 3*buffer_distance |...
        abs(polygon_contour_inner(:, 2)-infill_end_point(1, 2)) <= 3*buffer_distance,:); % radius scanning
    [~, row_inner_filtered_idx] = min(vecnorm(polygon_contour_inner_filtered-infill_end_point, 2, 2), [], 1, 'linear');
    polygon_contour_inner_start = polygon_contour_inner_filtered(row_inner_filtered_idx, :);
    [row_inner_idx, ~] = find(all(polygon_contour_inner == polygon_contour_inner_start, 2));
    polygon_contour_inner = polygon_contour_inner([row_inner_idx:end, 1:row_inner_idx-1], :);
    polygon_contour_inner = polygon_contour_inner([1:end,1], :);
end

% Calculate the coordinates and vectors by the step size and inclined spraying angle.
edge_points = [uniform_sampling_at_polyline(polygon_contour_outer, edge_step_size, z_slice, tilt_angle);...
    uniform_sampling_at_polyline(polygon_contour_inner, edge_step_size, z_slice, tilt_angle)];
edge_velocity = repmat("velocity_edge", [size(edge_points, 1), 1]);
edge_zone = repmat("zone_edge", [size(edge_points, 1), 1]);
end

function edge_points = uniform_sampling_at_polyline(polyline, edge_step_size, layer_height, tilt_angle)
% Interpolate the uneven distributed points on the polyline to uniform sampling points

% Input
% polyline: coordinates of polyline, N*0 or N*2 or N*3 matrix
% edge_step_size: step size of edge compensation inclined spraying between neighbouring spots, 1*1 double
% layer_height: slice height, 1*1 double
% tilt_angle: angle of edge compensation inclined spraying, 1*1 double
% Output
% edge_points: points of edge path, [x,y,z,nx,ny,nz], N*6 matrix

% Input check
if nargin ~= 4
    error('polyline and layer_height are required!');
end

% Make sure polyline is Nx2 or Nx3 matrix
if size(polyline, 2) ~= 0 && size(polyline, 2) ~= 2 && size(polyline, 2) ~= 3
    error('polyline must be Nx2 or Nx3 matrix!');
end

if isempty(polyline)
    edge_points = [];
else
    % Calculate the length of each line segment and accumulative length.
    segments = diff(polyline, 1, 1); % Line segment vector
    segment_normal_vector = [-segments(:,2),segments(:,1),zeros(size(segments,1),1)];
    segment_lengths = vecnorm(segments, 2, 2); % length of each line segment
    cumulative_distances = [0; cumsum(segment_lengths)]; % accumulative length
    
    total_length = cumulative_distances(end); % total length of polyline
    
    % calculate the serial distance of sampling points.
    sample_distances = unique([0:edge_step_size:total_length, total_length],'stable');
    
    % Initialize the sampling points matrix.
    edge_points = zeros(length(sample_distances), size(polyline, 2)+4);
    
    % Traverse each sampling distance and calculate the coordinates by inerpolation
    for ii = 1:length(sample_distances)
        dist = sample_distances(ii);
        
        % Find the line segments where the current sampling distance locate.
        seg_idx = find(cumulative_distances <= dist, 1, 'last');
        if seg_idx == length(cumulative_distances)
            seg_idx = seg_idx - 1; % avoid exceeding the index
        end
        
        % Calculate the ratio of line segments.
        seg_start_dist = cumulative_distances(seg_idx);
        seg_end_dist = cumulative_distances(seg_idx + 1);
        ratio = (dist - seg_start_dist) / (seg_end_dist - seg_start_dist);
        
        % Calculate coordinates by linear interpolation
        seg_start_point = polyline(seg_idx, :);
        seg_end_point = polyline(seg_idx + 1, :);
        edge_points(ii, 1:2) = seg_start_point + ratio * (seg_end_point - seg_start_point);
        edge_points(ii, 3) =  layer_height;
        edge_points(ii, 4:6) = segment_normal_vector(seg_idx,:)+...
            norm(segment_normal_vector(seg_idx,:))*tand(tilt_angle)*[0,0,1];
        edge_points(ii, 4:6) = edge_points(ii, 4:6)/norm(edge_points(ii, 4:6));
    end
end
end

function [link_points, link_velocity, link_zone] = generate_link(regionCounter, x_min, x_max, y_min, y_max, linkPath_freeDistance, resolution,...
            polygon, pointlist, infill_points, z_slice)
% Generate the link path

% Input
% regionCounter: index of polygon in one layerlist, 1*1 double
% x_min: the minimum coordinates along X axis of the triangles, 1*1 double
% x_max: the maximum coordinates along X axis of the triangles, 1*1 double
% y_min: the minimum coordinates along Y axis of the triangles, 1*1 double
% y_max: the maximum coordinates along Y axis of the triangles, 1*1 double
% linkPath_freeDistance: the activity range of link path relative to the range of model, 1*1 double
% resolution: the resolution of the substrate obstacle map, 1*1 double
% polygon: the closed polygon shape, 1*1 polyshape
% pointlist: planned spray spots in ABB reltool moving instructions before interpolation for profile prediction, [x,y,z,nx,ny,nz], N*6 matrix
% infill_points: points of infill path, [x,y,z,nx,ny,nz], N*6 matrix
% z_slice: slice height, 1*1 double
% Output
% link_points: points of link path, [x,y,z,nx,ny,nz], N*6 matrix
% link_velocity: name of speeddata of link path, N*1 string
% link_zone: name of zonedata of link path, N*1 string

if regionCounter == 1
    link_points = [];
else
    % Create the substrate map
    xGrid = x_min-linkPath_freeDistance:resolution:x_max+linkPath_freeDistance;
    yGrid = y_min-linkPath_freeDistance:resolution:y_max+linkPath_freeDistance;
    [X, Y] = meshgrid(xGrid, yGrid);
    obstacles = polygon;
    % Create the binary occupancy map for link points
    occupancyMap = false(length(yGrid), length(xGrid)); % logical matrix,falses stands for free
    % Mark the interior of the obstacle as "occupied" (true)
    for i = 1:numel(obstacles)
        % Check whether each grid point is inside the obstacles
        inPoly = isinterior(obstacles(i), X(:), Y(:));
        inPoly = reshape(inPoly, size(X));
        % Label the grid points inside the obstacles in the  % occupancyMap as true
        occupancyMap = occupancyMap | inPoly;
    end

    StartPoint = pointlist(end,1:2);
    OriginalGoalPoint = infill_points(1,1:2);
    [StartNode, OriginalgoalNode, GoalNode] = coordinate2index(xGrid, yGrid, StartPoint, OriginalGoalPoint, occupancyMap);
    [link_points_X, link_points_Y] = aStarSearch(xGrid, yGrid, occupancyMap, StartNode, OriginalgoalNode, GoalNode, '8-connected');
    link_points = [link_points_X;link_points_Y]';
    link_points = removeColinearPoints(link_points);
    link_points = [link_points, ones(size(link_points,1),1)*z_slice, ...
        zeros(size(link_points,1),2), ones(size(link_points,1),1)];
end
link_velocity = repmat("velocity_link", [size(link_points,1),1]);
link_zone = repmat("zone_link", [size(link_points,1),1]);
end

function [StartNode, OriginalGoalNode, GoalNode] = coordinate2index(xGrid, yGrid, StartPoint, OriginalGoalPoint, occupancyMap)
% Change the coordinates of the points into Indices

% Input
% xGrid: the grid along X axis, N1*N2 matrix
% yGrid: the grid along Y axis, N1*N2 matrix
% StartPoint: coordinate of Startpoint, 1*2 matrix
% OriginalGoalPoint: coordinate of OriginalGoalPoint, 1*2 matrix 
% occupancyMap: logical grid of the substrate, N1*N2 logical matrix, true for obstacle, false for free
% Output
% StartNode: index of OriginalGoalPoint, 1*2 matrix 
% OriginalGoalNode: index of OriginalGoalPoint, 1*2 matrix 
% GoalNode: index of GoalNode, 1*2 matrix

% Convert the start point and the goal point to grid indexes
startIdxX = find(xGrid >= StartPoint(1), 1);
startIdxY = find(yGrid >= StartPoint(2), 1);
StartNode = [startIdxY, startIdxX]; % Y is row and X is col in MATLAB

originalgoalIdxX = find(xGrid >= OriginalGoalPoint(1), 1);
originalgoalIdxY = find(yGrid >= OriginalGoalPoint(2), 1);
OriginalGoalNode = [originalgoalIdxY, originalgoalIdxX];
GoalNode = adjustGoalIfOnEdge(OriginalGoalNode, occupancyMap, 3);
end

function GoalNode = adjustGoalIfOnEdge(OriginalGoalNode, occupancyMap, searchRadius)
% If the goal node is on an obstacle, search for the nearest passable node around

% Input
% OriginalGoalNode: index of OriginalGoalPoint, 1*2 matrix 
% occupancyMap: logical grid of the substrate, N1*N2 logical matrix, true for obstacle, false for free
% searchRadius: how many grids for the search 
% Output
% GoalNode: index of GoalNode, 1*2 matrix

if nargin < 3
    searchRadius = 3;
end

[rows, cols] = size(occupancyMap);
goalRow = OriginalGoalNode(1);
goalCol = OriginalGoalNode(2);

% If the original goal node itself is passable, return directly
if ~occupancyMap(goalRow, goalCol)
    GoalNode = OriginalGoalNode;
    return;
end

% Search for possible points around
minDistance = inf;
GoalNode = OriginalGoalNode;

for r = max(1, goalRow-searchRadius):min(rows, goalRow+searchRadius)
    for c = max(1, goalCol-searchRadius):min(cols, goalCol+searchRadius)
        if ~occupancyMap(r, c)
            distance = sqrt((r - goalRow)^2 + (c - goalCol)^2);
            if distance < minDistance
                minDistance = distance;
                GoalNode = [r, c];
            end
        end
    end
end
end

function simplifiedPoints = removeColinearPoints(points)
% Eliminate the collinear points

% Input
% points: points before simplification, N*2 matrix
% Output
% simplifiedPoints: points after simplification, N*2 matrix

if size(points, 1) < 3
    simplifiedPoints = points;
    return;
end

% Initialize the result, including the first two points
simplifiedPoints = points(1:2, :);

for i = 3:size(points, 1)
    p1 = simplifiedPoints(end-1, :);  % the previous reserved point
    p2 = simplifiedPoints(end, :);    % the last reserved point
    p3 = points(i, :);                % the current reserved point

    % Calculate the vectors
    vec1 = p2 - p1;
    vec2 = p3 - p2;

    % Calculate the cross product(suitable for 2D/3D)
    crossProd = vec1(1)*vec2(2) - vec1(2)*vec2(1);

    if abs(crossProd) > 1e-10
        % If the cross product is not zero (considering floating-point errors), the point is reserved
        simplifiedPoints = [simplifiedPoints; p3];
    else
        % If the vectors are collinear, replace the last point (keep the latest point)
        simplifiedPoints(end, :) = p3;
    end
end
end