function createfigures(savefigure, increment, oldTriangles, newTriangles, moveRays_origins, nozzleOrientation, substrate_triangles, nozzlePath, path)
% create figures of profile prediction

% Input
% increment: iteration Number
% oldTriangles: triangles not need to be updated, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix
% newTriangles: updated triangles to replace the removed triangles, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix
% moveRay_origins: origins of rays after each move, [x, y, z], N*3 matrix
% nozzleOrientation: orientation of the nozzle in this move, [nx, ny, nz], 1*3 matrix
% substrate_triangles: coordinates of 3 vertices, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix
% spotsList: coordinates of tool center point(TCP), [x,y,z], N*3 matrix
% path: storage path

if ~savefigure
    return
end

%% Create the figure and layout
f1 = figure('Visible','off','Position',[1,41,2048,1037.6]);
t1 = tiledlayout(f1,2,2);
txt = ['Increment: i = ', num2str(increment)];
title(t1, txt, 'FontName', 'Times New Roman', 'FontSize', 32, 'FontWeight', 'bold');

%% Plot the nozzle exit and selected triangles
% create the axes
axes1 = nexttile(1,[2 1]);   
hold on;

% Draw triangulation patches
oldTR = createTriangulationFromMatrix(oldTriangles); % the unchanged triangles
trisurf(oldTR, 'FaceColor','interp');
newTR = createTriangulationFromMatrix(newTriangles); % the selected triangles
trisurf(newTR, 'FaceColor',[0.07 0.62 1], 'Marker', 'o','MarkerEdgeColor','none', 'MarkerFaceColor', 'red');

% plot the nozzle exit center
exitCenter = mean(moveRays_origins);
plot3(exitCenter(1), exitCenter(2), exitCenter(3),'Marker', 'o', 'Color', 'blue',...
    'MarkerSize', 6, 'MarkerFaceColor', 'blue');

% plot the nozzle exit disk
if abs(nozzleOrientation(1)) < 0.8 % determine the 2 orthogonal basis vectors
    v1 = [1 0 0];
else
    v1 = [0 1 0];
end
v1 = v1 - dot(v1, nozzleOrientation) * nozzleOrientation;
v1 = v1 / norm(v1);
v2 = cross(nozzleOrientation, v1);
v2 = v2 / norm(v2);
resolution = 30; % calculate the coordinated of the points on the nozzle exit disk
radius = 6;
theta = linspace(0, 2*pi, resolution)';
exitPoints = repmat(exitCenter, resolution, 1) + radius * (cos(theta) * v1 + sin(theta) * v2);
exitPoints_x = exitPoints(:,1);
exitPoints_y = exitPoints(:,2);
exitPoints_z = exitPoints(:,3);
fill3(exitPoints_x, exitPoints_y, exitPoints_z, 'red', 'FaceAlpha', 0.5, 'EdgeColor', 'none'); % draw the solid disk

% plot the arrow standing for spraying direction
quiver3(exitCenter(1), exitCenter(2), exitCenter(3), ...
    -nozzleOrientation(1), -nozzleOrientation(2), -nozzleOrientation(3), ...
    'Color', [0 0 1], 'AutoScaleFactor', 8, 'LineWidth', 2, 'MaxHeadSize', 1, 'AlignVertexCenters', 'on');

% plot the solid spraying cone
conePoints = exitPoints - 35 * nozzleOrientation;
n_points = size(exitPoints, 1);
points_x = zeros(2, n_points);
points_y = zeros(2, n_points);
points_z = zeros(2, n_points);
for i = 1:n_points
    points_x(:, i) = [exitPoints(i, 1); conePoints(i, 1)];
    points_y(:, i) = [exitPoints(i, 2); conePoints(i, 2)];
    points_z(:, i) = [exitPoints(i, 3); conePoints(i, 3)];
end
surf(points_x, points_y, points_z, 'EdgeColor', 'none', 'FaceColor', [0.3010 0.7450 0.9330], 'FaceAlpha', 0.5);
hold off;

% set the axes attributes
zlabel({'Z axis (mm)'},'HorizontalAlignment','center','FontName','Times New Roman','Position',[-2.14,148,0.75]); % axis label
ylabel({'Y axis (mm)'},'HorizontalAlignment','right','FontName','Times New Roman','Rotation',-30);
xlabel({'X axis (mm)'},'HorizontalAlignment','left','FontName','Times New Roman','Rotation',33);
xlim(axes1,[-10 110]); % coordinate range
ylim(axes1,[-10 110]);
zlim(axes1,[0 36]);

view(axes1,[-45 35]);
grid(axes1,'on');
set(axes1,'DataAspectRatio',[1 1 1],'FontName','Times New Roman','FontSize',28,...
    'XLimitMethod','tight','XTick',[0 20 40 60 80 100],'XGrid','on',...
    'YLimitMethod','tight','YTick',[0 20 40 60 80 100],'YGrid','on',...
    'ZLimitMethod','tight','ZTick',[0 18 36],'ZGrid','on'); % remainging attributes

%% Plot the path of tool center point(TCP)
% create the axes
axes2 = nexttile(2);
hold on;

% plot the substrate
substrateTR = createTriangulationFromMatrix(substrate_triangles);
trisurf(substrateTR, 'FaceColor', [0.3010 0.7450 0.9330]);
% plot the TCP
plot3(nozzlePath(:,1), nozzlePath(:,2), nozzlePath(:,3),...
    'Marker','o','MarkerIndices',size(nozzlePath, 1),'MarkerSize', 6,'MarkerFaceColor', 'red','MarkerEdgeColor', 'red',...
    'Color', [0.6350 0.0780 0.1840], 'LineWidth', 2);
% plot3(nozzlePath(:,1), nozzlePath(:,2), nozzlePath(:,3),...
%     'Marker','o','MarkerIndices',size(nozzlePath, 1),'MarkerSize', 6,'MarkerFaceColor', 'red','MarkerEdgeColor', 'red',...
%     'Color', 'interp', 'LineWidth', 2);
hold off;

% set the axes attributes
zlabel({'Z axis (mm)'},'HorizontalAlignment','center','FontName','Times New Roman','Position',[5.13,139.76,-1.13]); % axis label
ylabel({'Y axis (mm)'},'HorizontalAlignment','right','FontName','Times New Roman','Rotation',-33,'Position',[-6.75,33.67,-23.3]);
xlabel({'X axis (mm)'},'HorizontalAlignment','left','FontName','Times New Roman','Rotation',33,'Position',[33.98,-7.29,-23.54]);
xlim(axes2,[0 100]); % coordinate range
ylim(axes2,[0 100]);
zlim(axes2,[0 10]);

view(axes2,[-45 35]);
grid(axes2,'on');
set(axes2,'DataAspectRatio',[1 1 1],'FontName','Times New Roman','FontSize',28,...
    'XLimitMethod','tight','XTick',[0 50 100],'XGrid','on',...
    'YLimitMethod','tight','YTick',[00 50 100],'YGrid','on',...
    'ZLimitMethod','tight','ZTick',[0 10],'ZGrid','on'); % remainging attributes

%% Plot the profile evolution
% create the axes
axes3 = nexttile(4);
hold on;

% Draw triangulation patches
trisurf(oldTR, 'FaceColor','interp');  % the unchanged triangles
trisurf(newTR, 'FaceColor','interp'); % the selected triangles
c = colorbar(axes3, 'Location', 'eastoutside', 'Position', [0.93,0.11,0.0078,0.34]);
c.Ruler.TickLabelFormat = '%.1f';
hold off;

% set the axes attributes
zlabel({'Z axis (mm)'},'HorizontalAlignment','center','FontName','Times New Roman','Position',[-38.4,96.5,42.37]); % axis label
ylabel({'Y axis (mm)'},'HorizontalAlignment','right','FontName','Times New Roman','Rotation',-33,'Position',[-6.75,33.67,-23.3]);
xlabel({'X axis (mm)'},'HorizontalAlignment','left','FontName','Times New Roman','Rotation',33, 'Position',[33.98,-7.29,-23.54]);
xlim(axes3,[0 100]); % coordinate range
ylim(axes3,[0 100]);
zlim(axes3,[0 10]);

view(axes3,[-45 35]);
grid(axes3,'on');
set(axes3,'DataAspectRatio',[1 1 1],'FontName','Times New Roman','FontSize',28,...
    'XLimitMethod','tight','XTick',[0 50 100],'XGrid','on',...
    'YLimitMethod','tight','YTick',[0 50 100],'YGrid','on',...
    'ZLimitMethod','tight','ZTick',[0 10],'ZGrid','on'); % remainging attributes

%% Save
saveas(f1,[path,num2str(increment)],'jpeg');
close(f1);
end