function spotsList = spotInterp(ReferencePoint, pointlist, velocitylist, spot_step_size)
% Calculate the coordinates of interpolated points based on the sampling distance

% Input
% pointlist: planned spray spots in ABB reltool moving instructions before interpolation for profile prediction, [x,y,z,nx,ny,nz], N*6 matrix
% % velocitylist: name of speeddata in ABB moving instructions, N*1 string
% spot_step_size: the distance between neighbouring spots, 1*1 double
% Output
% spotList: information of interpolated points, [x,y,z,nx,ny,nz, velocity compensation coefficient], N*7 matrix

if isempty(pointlist) || isempty(velocitylist)
    spotsList = [];
    return
else
    pointlist = pointlist + ReferencePoint;
end

% velocity database
velocityKeySet = ["velocity_infill", "velocity_edge", "velocity_link"];
compensationValueSet = [1 2 1];
Coef_VCompMap = containers.Map(velocityKeySet, compensationValueSet);

% calculate the length of each line segment and accumulative length
segments = diff(pointlist(:, 1:3), 1, 1); % Line segment vector
segment_lengths = vecnorm(segments, 2, 2); % length of each line segment
cumulative_distances = [0; cumsum(segment_lengths)]; % accumulative length
total_length = cumulative_distances(end); % total length of polyline

% calculate the serial distance of sampling points
spot_distances = 0: total_length/round(total_length/spot_step_size): total_length;

% Initialize the sampling points matrix
spotsList = zeros(length(spot_distances), 7);

% Traverse each sampling distance and calculate the coordinates by inerpolation
for i = 1:length(spot_distances)
    dist = spot_distances(i);

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
    seg_start_point = pointlist(seg_idx, :);
    seg_end_point = pointlist(seg_idx + 1, :);
    spotsList(i, 1:6) = seg_start_point + ratio * (seg_end_point - seg_start_point);
    spotsList(i, 4:6) = spotsList(i, 4:6)/norm(spotsList(i, 4:6));

    % Calculate the velocity compensation coefficient
    spotsList(i, 7) = Coef_VCompMap(velocitylist(seg_idx + 1));
end
end