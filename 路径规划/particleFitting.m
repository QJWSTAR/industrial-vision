function [rays_indices, rays_origins, rays_directions, rays_speeds, rays_possiLengths, rays_Vcr,...
    length_threshold, area_threshold] = particleFitting(excelFile, SoD)
% Calculate the particle position, velocity, temperature and diamater
% distributions according to the simulated results of CFD

% Input
% excelFile: name of CFD result, excel file, 1*N character vector
% SoD: standoff distance, 1*1 double
% Output
% rays_indices: indices of rays, N*1 matrix
% rays_origins: coordinates of rays origins, N*3 matrix, [x, y, z], N*3 matrix 
% rays_directions: directions of rays, [nx, ny, nz], N*3 matrix
% rays_speeds: speed values of rays, N*3 matrix
% rays_possiLengths: length distribution of rays, N*1 matrix
% rays_Vcr: critical velocity of rays, N*1 matrix
% length_threshold: minimum distance of each rays, 1*1 double
% area_threshold: minimum area based on length_threshold, equilateral triangle, 1*1 double

%% Data import
% This is the step is to get the coordinates of the position probability density  point in form of matrix before interpolation.
x = 1e+3*2*readmatrix(excelFile,'Range','B3:B4362'); % Import the X location coordinats of particles
y = 1e+3*2*readmatrix(excelFile,'Range','C3:C4362'); % Import the Y location coordinats of particles
u = 1e+3*readmatrix(excelFile,'Range','E3:E4362'); % Import the X velocity of particles
v = 1e+3*readmatrix(excelFile,'Range','F3:F4362'); % Import the Y velocity of particles
w = 1e+3*readmatrix(excelFile,'Range','G3:G4362'); % Import the Z velocity of particles
dp = 1e+6*readmatrix(excelFile,'Range','H3:H4362'); % Import the diameter of particles
Tp = readmatrix(excelFile,'Range','I3:I4362'); % Import the temperature of particles

%% Calculate position distribution
% Create the 3D probability of bar chart
nbins = 14;
Xedges = linspace(-10,10,nbins+1);
Yedges = linspace(-10,10,nbins+1);
X_COORD = Xedges(1:end-1)+diff(Xedges)/2; % Get the X edge of bar chart
Y_COORD = Yedges(1:end-1)+diff(Yedges)/2; % Get the Y edge of bar chart
Z_COORD = rot90(histcounts2(x, y, Xedges, Yedges, 'Normalization','probability')); % Get the Z edge of bar chart

% This is the step to rearrange the coordinates of probability density point in form of column vector.
X = reshape(repmat(X_COORD, nbins, 1), [], 1);
Y = reshape(repmat(Y_COORD, 1, nbins), [], 1);
Z = reshape(Z_COORD, [], 1);

% This is the step to fit the derived points into smooth surface after interpolation.
n1 = 14;
n2 = 14;
spot_min = min([X_COORD, Y_COORD]);
spot_max = max([X_COORD, Y_COORD]);
[X_fitting,Y_fitting] = meshgrid(spot_min:1/n1*(spot_max-spot_min):spot_max,...
    spot_min:1/n2*(spot_max-spot_min):spot_max);
Z_fitting = abs(griddata(X,Y,Z,X_fitting,Y_fitting,'v4')); %linear, nearest, natrual,cubic,v4
% f(x,y) = 1/(2*pi*sigmax*sigmay)*exp^(-1/2*(x^2/sigmax^2 + y^2/sigmay^2));
Z_fitting = 0.047*exp(-0.5*(0.094*pi*X_fitting.^2+0.094*pi*Y_fitting.^2)); % Used solely for testing purposes, coff before pi is 2 times 1st coff

%% Calculate velocity distribution
% This is the step to acquire the velocity surface in accordance with X axis and Y axis.
ft = fittype( 'lowess' );
opts = fitoptions( 'Method', 'LowessFit' );
opts.Normalize = 'on';
opts.Span = 0.5;

% to obtain the surface of X velocity
[ufitresult, ~] = fit( [x, y], u, ft, opts );
u_fitting = feval(ufitresult,X_fitting,Y_fitting);
% to obtain the surface of Y velocity
[vfitresult, ~] = fit( [x, y], v, ft, opts );
v_fitting = feval(vfitresult,X_fitting,Y_fitting);
% to obtain the surface of Z velocity
[wfitresult, ~] = fit( [x, y], w, ft, opts );
w_fitting = feval(wfitresult,X_fitting,Y_fitting);

%% Calculate critical velocity distribution
ft = fittype( 'lowess' );
opts = fitoptions( 'Method', 'LowessFit' );
opts.Normalize = 'on';
opts.Span = 0.1;

% to obtain the surface of diameter
[dpfitresult, ~] = fit( [x, y], dp, ft, opts );
dp_fitting = feval(dpfitresult,X_fitting,Y_fitting);
% to obtain the surface of temperature
[Tpfitresult, ~] = fit( [x, y], Tp, ft, opts );
Tp_fitting = feval(Tpfitresult,X_fitting,Y_fitting);
% to obtain the surface of critical velocity
Vcr_fitting = 1*sqrt(657000-600.*Tp_fitting)./dp_fitting.^0.18+0;

%% Transform the flat fitting map into the form of column vector
X_Gaussian = reshape(X_fitting, [], 1);
Y_Gaussian = reshape(Y_fitting, [], 1);
Z_Gaussian = reshape(Z_fitting, [], 1);
u_Gaussian = reshape(u_fitting, [], 1);
v_Gaussian = reshape(v_fitting, [], 1);
w_Gaussian = -reshape(w_fitting, [], 1);
Vcr_Gaussian = reshape(Vcr_fitting, [], 1);

%% Modification of spray spot shape
% circular shape
filterMatrix = true(size(X_Gaussian));
for i = 1:size(filterMatrix,1)
    %     if sqrt(X_Gaussian(i)^2 + Y_Gaussian(i)^2) > 1*min([abs(spot_min), abs(spot_max)])
    if sqrt(X_Gaussian(i)^2 + Y_Gaussian(i)^2) > 6
        filterMatrix(i) = false;
    end
end
X_Gaussian = X_Gaussian(filterMatrix);
Y_Gaussian = Y_Gaussian(filterMatrix);
Z_Gaussian = Z_Gaussian(filterMatrix);
u_Gaussian = u_Gaussian(filterMatrix);
v_Gaussian = v_Gaussian(filterMatrix);
w_Gaussian = w_Gaussian(filterMatrix);
Vcr_Gaussian = Vcr_Gaussian(filterMatrix);

%% Calculate rays
rays_velocity = [u_Gaussian, v_Gaussian, w_Gaussian];
rays_speeds = vecnorm(rays_velocity,2,2);
rays_directions = rays_velocity./rays_speeds;
rays_possiLengths = Z_Gaussian;
rays_Vcr = Vcr_Gaussian;
rays_origins = [X_Gaussian, Y_Gaussian, zeros(size(Z_Gaussian))] + rays_directions.*rays_speeds./w_Gaussian*SoD;
rays_indices = (1:size(rays_origins,1))';

%% Calculate the threshoulds
XGridRES = (max(Xedges) - min(Xedges))/nbins;
YGridRES = (max(Yedges) - min(Yedges))/nbins;
length_threshold = min(XGridRES, YGridRES);
area_threshold = 3^(1/2)/4*length_threshold^2;
end