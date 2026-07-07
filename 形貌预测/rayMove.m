function [moveRays_origins, moveRays_directions, nozzleOrientation, Coef_THK] = rayMove(spotInfo, rays_origins, rays_directions)
% Calculate the information of rays during the moving process, take the original one as the reference

% Input:
% spotInfo: information of spot, [x,y,z,nx,ny,nz, velocity compensation coefficient], 1*7 matrix
% rays_origins: coordinates of ray origins, N*3 matrix, [x, y, z], N*3 matrix 
% rays_directions: directions of rays, [nx, ny, nz], N*3 matrix
% Output
% moveRays_origins: origins of rays after each move, [x, y, z], N*3 matrix
% moveRays_directions: directions of rays after each move, [nx, ny, nz], N*3 matrix
% nozzleOrientation: orientation of the nozzle in this move, [nx, ny, nz], 1*3 matrix
% Coef_THK: coefficent of the thickness, 1*1 double

nozzleOrientation = spotInfo(4:6);

R = rodrigues([0,0,1], nozzleOrientation);
moveRays_directions = rays_directions*R';
moveRays_origins =  rays_origins*R' + repmat(spotInfo(1:3), size(rays_origins,1), 1);

Coef_THK = spotInfo(7);
end

%% Auxiliary Function
function R = rodrigues(v1, v2)
% Rodrigues rotation formula, rotate from v1 to v2

% Inputs
% v1: being rotated vector, 3*1 column vector
% v2: rotating vector, 3*1 column vector
% Outputs
% R: rotation matrix, 3*3 matrix
% R*v1 and v2 are in the same direction
% if v1, v2: 1x3 row vectors，v1*R' and v2 are in the same direction.

% normalize the 2 vectors
v1 = v1 / norm(v1);
v2 = v2 / norm(v2);

% calculate the rotation axis (cross product)
k = cross(v1, v2);
k_norm = norm(k);

% handling special situations
if k_norm < 1e-10
    if dot(v1, v2) > 0
        R = eye(3);  % same direction
        return
    else
        R = -eye(3); % opposite direction
        return
    end
else
    % calculate the rotation angle
    k = k / k_norm;
    cos_theta = dot(v1, v2);
    sin_theta = k_norm;  
    theta = atan2(sin_theta, cos_theta);
end

% construct the antisymmetric matrix
K = [0, -k(3), k(2);
    k(3), 0, -k(1);
    -k(2), k(1), 0];

% Rodrigues formula
R = eye(3) + sin(theta)*K + (1 - cos_theta)*(K*K);
end