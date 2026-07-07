function moves_matrix = point_interpretaion(pointlist, nozzle_normal_vector, tol)
% To interpret the pointlist from vector into the degree

% Input
% pointlist: planned spray spots in ABB reltool moving instructions before interpolation for profile prediction, [x,y,z,nx,ny,nz], N*6 matrix
% nozzle_normal_vector: the orientation of the nozzle in workpiece coordinate system, 1*3 matrix
% tol: tolerance, 1*1 double
% Output
% moves_matrix: values of reltool instruction, [x, y, z, ax, ay, az], N*6 matrix

moves_matrix = zeros(size(pointlist)); % Pre-open up space

for i = 1:size(pointlist,1)
    % Calculate the position
    moves_matrix(i,1:3) = pointlist(i,1:3);
    
    % Calculate the reltool degree
    % The reltool move of nozzle can be processed as the negative degree of calculated vector rotating to nozzle orientation.
    
    % X axis
    n_point = pointlist(i,4:6);
    nx = [0,n_point(2),n_point(3)];
    n_start = [0,nozzle_normal_vector(2),nozzle_normal_vector(3)];
    x_rotaxis = cross(nx,n_start); % calculate rotation axis (maybe positive or negative)
    if isequal(x_rotaxis,[0,0,0]) % in case of  parallel vectors
        x_dir = 1;
    else
        x_dir = x_rotaxis(1)/abs(x_rotaxis(1)); % determine if it is along x positive direction
    end
    x_deg = x_dir*atan2d(norm(x_rotaxis),dot(nx,n_start));
    
    % Y axis
    n_point = [n_point(1),n_point(2)*cosd(x_deg)-n_point(3)*sind(x_deg),n_point(2)*sind(x_deg)+n_point(3)*cosd(x_deg)];
    % update the vectors after rotation along x axis
    ny = [n_point(1),0,n_point(3)];
    n_start = [nozzle_normal_vector(1),0,nozzle_normal_vector(3)];
    y_rotaxis = cross(ny,n_start); % calculate rotation axis (maybe positive or negative)
    if isequal(y_rotaxis,[0,0,0]) % in case of  parallel vectors
        y_dir = 1;
    else
        y_dir = y_rotaxis(2)/abs(y_rotaxis(2)); % determine if it is along y positive direction
    end
    y_deg = y_dir*atan2d(norm(y_rotaxis),dot(ny,n_start));
    
    % Z axis
    n_point = [n_point(1)*cosd(y_deg)+n_point(3)*sind(y_deg),n_point(2),-n_point(1)*sind(y_deg)+n_point(3)*cosd(y_deg)];
    % update the vectors after rotation along y axis
    nz = [n_point(1),n_point(2),0];
    n_start = [nozzle_normal_vector(1),nozzle_normal_vector(2),0];
    z_rotaxis = cross(nz,n_start); % calculate rotation axis (maybe positive or negative)
    if isequal(z_rotaxis,[0,0,0]) % in case of  parallel vectors
        z_dir = 1;
    else
        z_dir = y_rotaxis(3)/abs(y_rotaxis(3)); % determine if it is along z positive direction
    end
    z_deg = z_dir*atan2d(norm(z_rotaxis),dot(nz,n_start));
    
    n_point = [n_point(1)*cosd(z_deg)-n_point(2)*sind(z_deg),n_point(1)*sind(z_deg)+n_point(2)*cosd(z_deg),n_point(3)];
    % update the vectors after rotation along z axis
    if norm(n_point - nozzle_normal_vector(:,1:3),1) > tol % determing whether it is correct after rotation for reltool
        error('Rotation error')
    end
    
    moves_matrix(i,4:6) = [-x_deg,-y_deg,-z_deg]; % reltool is opposite
end
end