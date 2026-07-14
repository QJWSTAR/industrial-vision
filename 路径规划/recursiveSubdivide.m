function subdivided = recursiveSubdivide(triangles, maxEdgeLength)
% Subdivide the triangles recursively based on the longest edge length

% Input:
% triangles: coordinates of 3 vertices, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix
% maxEdgeLength: the maximum allowable edge length, 1*1 double
% Output
% subdivided: coordinates of subdivided triangles of 3 vertices, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix

n = size(triangles, 1);
allTriangles = [];
for i = 1:n
    vertices = reshape(triangles(i, :), 3, 3)';
    allTriangles = [allTriangles; recursiveSplit(vertices, maxEdgeLength)];
end
subdivided = allTriangles;
end

%% Auxiliary Function
function triangles = recursiveSplit(vertices, maxLength)
% Subdivide one triangle recursively based on the longest edge length

% Input: 
% vertices: coordinates of 3 vertices of one triangles , [x1, y1, z1; x2, y2, z2; x3, y3, z3], 3*3 matrix
% maxEdgeLength: the maximum allowable edge length, 1*1 double
% Output:
% triangles: subdivided coordinates of 3 vertices, [x1, y1, z1, x2, y2, z2, x3, y3, z3], N*9 matrix

% calculate the lengths of the three edges
edges = [...
    norm(vertices(1,:)-vertices(2,:));...
    norm(vertices(2,:)-vertices(3,:));...
    norm(vertices(3,:)-vertices(1,:))];

% if all the edges are smaller than the threshold, return to the original triangle.
if all(edges <= maxLength)
    triangles = reshape(vertices', 1, 9);
    return;
end

% divide the longest edge for further segmentation
[~, longestIdx] = max(edges);

switch longestIdx
    case 1  % edge v1-v2 is the longest
        mid = (vertices(1,:) + vertices(2,:)) / 2;
        % divided into two triangles
        t1 = [vertices(1,:); mid; vertices(3,:)];
        t2 = [mid; vertices(2,:); vertices(3,:)];

    case 2  % edge v2-v3 is the longest
        mid = (vertices(2,:) + vertices(3,:)) / 2;
        % divided into two triangles
        t1 = [vertices(1,:); vertices(2,:); mid];
        t2 = [vertices(1,:); mid; vertices(3,:)];

    case 3  % edge v3-v1 is the longest
        mid = (vertices(3,:) + vertices(1,:)) / 2;
        % divided into two triangles
        t1 = [vertices(1,:); vertices(2,:); mid];
        t2 = [mid; vertices(2,:); vertices(3,:)];
end

% recursive subdivision
triangles = [...
    recursiveSplit(t1, maxLength);...
    recursiveSplit(t2, maxLength)];
end