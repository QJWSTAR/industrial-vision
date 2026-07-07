function triangles = read_STLfile(stlfilename)
% Read the STL file into the format of vertices

% Input
% stlfilename: name of STL file, 1*N character vector
% Output
% triangles: coordinates of 3 vertices, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix

TR = stlread(stlfilename);
triangles = [...
    TR.Points(TR.ConnectivityList(:,1),:),...
    TR.Points(TR.ConnectivityList(:,2),:),...
    TR.Points(TR.ConnectivityList(:,3),:)];
end