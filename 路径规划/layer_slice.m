function [additive_layerlist, repairing_layerlist] = layer_slice(addtive_triangles_cluster, repairing_triangles_cluster, layer_height, base_plane)
% Generate the layerlist of the additive triangle clusters and repairing triangle clusters

% Input
% addtive_triangles_cluster: the clusters of addtive triangles above the base plane, 1*1 cell, N*15 matrix for the cell
% repairing_triangles_cluster: the clusters of repairing triangles below the base plane, 1*N cell, N*15 matrix for each cell
% layer_height: layer thickness (mm), 1*1 double
% base_plane: height of the reference plane, 1*1 double
% Output
% additive_layerlist: layerlist of triangles above the base plane, 1*1 cell, N*4 cell for the cell,...
%                     [application, slicing method, height, polygon], including empty matrix ([])
% repairing_layerlist: layerlist of triangles below the base plane, 1*N cell, N*4 cell for each cell,...
%                      [application, slicing method, height, polygon], including empty matrix ([])

repairing_layerlist = sliceLayers(repairing_triangles_cluster, layer_height, base_plane, "repairing");
additive_layerlist = sliceLayers(addtive_triangles_cluster, layer_height, base_plane, "additive");
end

%% Auxiliary Function
function layerlist = sliceLayers(triangles_cluster, layer_height, base_plane, str)
% Generate the layerlist of the triangle clusters

% Input
% triangles_cluster: the clusters of triangles, 1*N cell, N*15 matrix for each cell
% layer_height: layer thickness (mm), 1*1 double
% base_plane: height of the reference plane, 1*1 double
% str: instruction of application field, 1*N characters, only available for 'additive' or 'repairing'
% Output
% layerlist: layerlist of triangles, 1*N cell, N*4 cell for each cell,...
%            [application, slicing method, height, polygon], including empty matrix ([])

% exclude the empty cell
if isempty(triangles_cluster)
    layerlist = {};
    return
end

% calculate the slices and polygons
layerlist = cell(1, length(triangles_cluster));
for clusterSN = 1:length(triangles_cluster)
    triangles = triangles_cluster{clusterSN};

    % generate the slices
    min_z = min(triangles(:,13)) + 1e-4; % 1e-4 is set to maintain stability
    max_z = max(triangles(:,14)) + 1e-4;
    if str == "repairing"
        z_slices = min_z : layer_height : base_plane-layer_height + 1e-4;
    else
        z_slices = base_plane + 1e-4 : layer_height : max_z-layer_height; % "additive"
    end

    % generate the polygons
    if isempty(z_slices)
        layerlist{clusterSN} = [];
    else
        application = cell(length(z_slices), 1);
        layertype = cell(length(z_slices), 1);
        z_slices_cell = cell(length(z_slices), 1);
        polygon_cell = cell(length(z_slices), 1);
        for i = 1:length(z_slices)
            application{i} = str;
            layertype{i} = "uniform thickness";
            z_slices_cell{i} = z_slices(i);
        end

        % Pre-open up space to store the serial number of the triangles
        z_triangles_list = zeros(size(z_slices,2),size(triangles,1));
        z_triangles_size=zeros(size(z_slices,2),1);
        for i = 1:size(triangles,1)
            node_low = triangles(i,13);
            node_high = triangles(i,14);
            z_high_index=find(z_slices<=node_high,1,'last');
            z_low_index=find(z_slices>=node_low,1);
            if z_high_index >= z_low_index
                for j = z_low_index:z_high_index
                    z_triangles_size(j) = z_triangles_size(j) + 1;
                    % z_triangles_size is a column vector, the length is the total number of layers.
                    % The value of z_triangles_size that intersects the current triangle increases by 1.
                    % After the loop has completed all the patches,
                    % each value of z_triangles_size represents the number of triangles that intersect with the corresponding z_slices.
                    z_triangles_list(j,z_triangles_size(j)) = i;
                    % z_triangles_list is sorted from up to down according to the order of z_triangles_size.
                    % Each row represents the serial number of the triangles that intersects with the corresponding z_slices，
                    % The number of valid data in each row of z_triangles is equal to the value of each row of z_triangles_size.
                end
            end
        end

        %list formed
        for  k = 1:size(z_slices,2)
            triangle_checklist = z_triangles_list(k,1:z_triangles_size(k));
            % triangle_checklist is a row vector, its length equals to the number of traingles intersecting the current z_slices,
            % with each element representing the serial number of the intersecting traingles.
            tri=triangles(triangle_checklist,:);
            % tri is all the traingles that intersects with the current z_slices.

            % calculate the intersections
            tri = tri';
            p1 = tri(1:3,:);
            p2 = tri(4:6,:);
            p3 = tri(7:9,:);

            c = ones(1,size(p1,2))*z_slices(k) ;
            P = [zeros(1,size(p1,2));zeros(1,size(p1,2));ones(1,size(p1,2))];
            t1 = (c-sum(P.*p1))./sum(P.*(p2-p1));
            t2 = (c-sum(P.*p2))./sum(P.*(p3-p2));
            t3 = (c-sum(P.*p3))./sum(P.*(p1-p3));
            t1(isnan(t1)) = 0;
            t2(isnan(t2)) = 0;
            t3(isnan(t3)) = 0;
            intersect1 = p1+bsxfun(@times,p2-p1,t1);
            intersect2 = p2+bsxfun(@times,p3-p2,t2);
            intersect3 = p3+bsxfun(@times,p1-p3,t3);
            i1 = t1<1 & t1>=0;
            i2 = t2<1 & t2>=0;
            i3 = t3<1 & t3>=0;
            i_qty = i1+i2+i3 == 2; % Only the triangles has 2 intersections can be added to the polygon.

            % calculate the sides of polygon
            intersect = reshape([intersect1;intersect2;intersect3],[],1);
            i_col_vec = reshape([i1;i1;i1;i2;i2;i2;i3;i3;i3],[],1);
            i_qty_col_vec = reshape(repmat(i_qty,9,1),[],1);
            intersect = intersect(i_col_vec&i_qty_col_vec,:);
            lines = reshape(intersect,6,[])';
            linesize = size(lines,1);

            if linesize ~= 0
                % find all the points, assign nodes and remove duplicates
                start_nodes = lines(1:linesize,1:2);
                end_nodes = lines(1:linesize,4:5);
                nodes = [start_nodes; end_nodes];
                tol_uniquetol = 1e-8;
                tol = 1e-8;
                nodes = uniquetol(nodes,tol_uniquetol,'ByRows',true);
                nodes = sortrows(nodes,[1 2]);

                % check for bad stl files. repeated edges, too thin surfaces, unclosed loops
                [~, n1] = ismembertol(start_nodes, nodes, tol, 'ByRows',true);
                [~, n2] = ismembertol(end_nodes, nodes,tol,  'ByRows',true);
                conn1 = [n1 n2];
                conn2 = [n2 n1];
                check = ismember(conn2,conn1,'rows');
                conn1(check == 1,:)=[];
                G = graph(conn1(:,1),conn1(:,2));

                % create subgraph for connected components
                bins = conncomp(G);
                cluster_list =[];
                for i = 1:max(bins)
                    startNode = find(bins==i, 1, 'first');
                    path = dfsearch(G, startNode);
                    path = [path; path(1)];
                    cluster_list_iter = [nodes(path,1) nodes(path,2)];
                    if ~isempty(path)
                        if cluster_list_iter(1,1)>cluster_list_iter(2,1) || cluster_list_iter(1,2)>cluster_list_iter(2,2)
                            cluster_list_iter = cluster_list_iter(end:-1:1,:);
                        end
                    end
                    % connect to the first point
                    cluster_list = [cluster_list; cluster_list_iter; [NaN NaN]];
                end
                polygon_cell{k} = cluster_list;
            end
        end
        layerlist{clusterSN} = [application, layertype, z_slices_cell, polygon_cell];
    end
end
end