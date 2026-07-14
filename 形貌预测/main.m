%% Start Initialization
% H3 fix: removed 'clear all; close all' - would destroy matlab_server state
% when this script is on the path. Use 'clc' only.
clc;

%% Define Parameter(mm)
stlfilename = 'part.stl';             % name of STL file
base_plane = 5;                       % height of the reference plane
model_scale = 1;                      % zoom in model
tol = 1e-8;                           % tolerance
layer_height = 2;                     % layer thickness (mm)
scanning_angle = -45;                 % direction of Zig-Zag infill path, in degree system
buffer_additive = 2;                  % buffering distance for the additive polygon above the base plane to generate infill path
buffer_repairing = 0;                 % buffering distance for the repairing polygon below the base plane to generate infill path
scanning_step = 2;                    % distance between scanning lines of Zig-Zag infill path
edge_step_size = 2;                   % step size of edge compensation inclined spraying between neighbouring spots
tilt_angle = 60;                      % angle of edge compensation inclined spraying
linkPath_freeDistance = 20;           % the activity range of link path relative to the range of model
resolution = 2;                       % the resolution of the substrate obstacle map
nozzle_normal_vector = [0,0,1];       % the orientation of the nozzle in workpiece coordinate system
ReferencePoint = [0,0,0];             % translate the model for proper position on the substrate (real-word coordinates in workpiece coordinate system)
robotcommandoutput = 'RScommend.txt'; % name of the output file
moduleID = 'mod20260623';             % name of the module in Rapid

%% Read STL File
tic
triangles = read_stl_file(stlfilename);
timersf = toc;
fprintf('Read stl file done, %.4f sec elapsed\n',timersf);

%% Model Process
tic
[all_triangles, addtive_triangles_cluster, repairing_triangles_cluster, x_min, x_max, y_min, y_max]=model_process(triangles, model_scale, tol, base_plane);
%            1   2   3   4   5   6   7   8   9  10 11 12  13   14   15
%triangles=[vx1 vy1 vz1 vx2 vy2 vz2 vx3 vy3 vz3 nx xy xz minz maxz angle]
timemp = toc;
fprintf('Model process done, %.4f sec elapsed\n',timemp);

%% layer slice
tic
[additive_layerlist, repairing_layerlist] = layer_slice(addtive_triangles_cluster, repairing_triangles_cluster, layer_height, base_plane);
timels = toc;
fprintf('Layer slice done, %.4f sec elapsed\n',timels);

%% generate path
tic
[pointlist, velocitylist, zonelist] = generate_path(additive_layerlist, repairing_layerlist,...
    buffer_additive, buffer_repairing, scanning_angle, scanning_step,...
    edge_step_size, tilt_angle, x_min, x_max, y_min, y_max, linkPath_freeDistance, resolution);
timegp = toc;
fprintf('Generate path done, %.4f sec elapsed\n',timegp);

%% point interpretation
tic
moves_matrix = point_interpretaion(pointlist, nozzle_normal_vector, tol);
timepi = toc;
fprintf('Point interpretation done, %.4f sec elapsed\n',timepi);

%% robot_command_output
tic
save('pointlist.mat', 'pointlist');
save('velocitylist.mat', 'velocitylist');
sprayArea = robot_command_output(moves_matrix, ReferencePoint, velocitylist, zonelist, robotcommandoutput, moduleID);
timerco = toc;
fprintf('Robot_command_output done, %.4f sec elapsed\n',timerco);
disp('sprayArea_x sprayArea_y sprayArea_z')
disp(sprayArea)