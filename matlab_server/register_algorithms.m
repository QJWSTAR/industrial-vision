function register_algorithms(reg)
%REGISTER_ALGORITHMS  Register every algorithm function exposed by the server.
%
%   register_algorithms(reg)
%
%   Registers all 19 algorithm functions from the path-planning and
%   morphology modules (everything except main.m, createfigures.m and
%   createvideo.m). Each registration wraps the existing MATLAB function so
%   that JSON params/inputs are converted to native MATLAB arguments and the
%   native outputs are converted back to JSON results/artifacts.
%
%   Wrapper contract
%   ----------------
%   Each wrapper has signature  out = wrap_xxx(params, inputs)  and returns
%       out.results   : struct of name -> Value (scalars / strings / packed)
%       out.artifacts : struct of name -> Tensor (numeric matrices)
%
%   Type conventions for the Python codec:
%     * scalars / strings / bool          -> params as Value {num|intval|str|flag}
%     * numeric matrices (pointlist, ...) -> inputs as Tensor {dtype,shape,data,units}
%     * cell arrays / nested structs      -> params as Value.str holding a JSON
%                                            string produced by pack_json();
%                                            the matching wrapper decodes with
%                                            get_json(). This keeps arbitrarily
%                                            nested MATLAB types portable.
%     * cell arrays of matrices may also be sent as indexed inputs
%       <name>_1 .. <name>_N with a <name>_count param; see get_input_cell().
%
%   File-inherently algorithms (read_stl_file, read_STLfile, particleFitting,
%   robot_command_output) take a path string param and read/write that file;
%   this is intrinsic to the algorithm, not an artefact of the transport.

    % ---------- path_planning.* ----------
    add(reg, 'path_planning.layer_slice',            '1.0.0', @wrap_layer_slice, ...
        'path_planning', 'Slice additive/repairing triangle clusters into per-layer polygons.', ...
        {}, 60000);  % H2 fix: base MATLAB only (containers.Map), no Map_Toolbox needed
    add(reg, 'path_planning.model_process',          '1.0.0', @wrap_model_process, ...
        'path_planning', 'Classify triangles into additive/repairing clusters and compute bounds.', ...
        {}, 60000);  % H2 fix: base MATLAB only
    add(reg, 'path_planning.generate_path',          '1.0.0', @wrap_generate_path, ...
        'path_planning', 'Generate spray pointlist/velocitylist/zonelist from layer lists.', ...
        {'Map_Toolbox'}, 120000);
    add(reg, 'path_planning.a_star_search',          '1.0.0', @wrap_a_star_search, ...
        'path_planning', 'A* link-path search on a substrate occupancy grid.', ...
        {}, 60000);
    add(reg, 'path_planning.point_interpretaion',    '1.0.0', @wrap_point_interpretaion, ...
        'path_planning', 'Convert pointlist normals to ABB reltool Euler angles.', ...
        {}, 30000);
    add(reg, 'path_planning.read_stl_file',          '1.0.0', @wrap_read_stl_file, ...
        'path_planning', 'Read an STL file into an N*12 triangle matrix (with normals).', ...
        {}, 30000);
    add(reg, 'path_planning.robot_command_output',   '1.0.0', @wrap_robot_command_output, ...
        'path_planning', 'Emit ABB Rapid moving instructions to a file.', ...
        {}, 30000);

    % ---------- morphology.* ----------
    add(reg, 'morphology.spot_interp',                '1.0.0', @wrap_spot_interp, ...
        'morphology', 'Interpolate spray spots along a pointlist at a fixed step size.', ...
        {}, 30000);  % H2 fix: base MATLAB only (containers.Map)
    add(reg, 'morphology.ray_triangle_intersection',  '1.0.0', @wrap_ray_triangle_intersection, ...
        'morphology', 'Moller-Trumbore ray/triangle intersection for candidate triangles.', ...
        {}, 120000);
    add(reg, 'morphology.build_octree',               '1.0.0', @wrap_build_octree, ...
        'morphology', 'Build an octree acceleration structure over a triangle soup.', ...
        {}, 60000);
    add(reg, 'morphology.batch_octree_filter',        '1.0.0', @wrap_batch_octree_filter, ...
        'morphology', 'Filter candidate triangles per ray via octree traversal.', ...
        {}, 120000);
    add(reg, 'morphology.classify_removed_triangles', '1.0.0', @wrap_classify_removed_triangles, ...
        'morphology', 'Cluster removed triangles and extract boundary loops.', ...
        {}, 60000);  % H2 fix: base MATLAB only (graph/conncomp)
    add(reg, 'morphology.create_triangulation_from_matrix', '1.0.0', @wrap_create_triangulation_from_matrix, ...
        'morphology', 'Build a MATLAB triangulation from an N*9 matrix.', ...
        {}, 30000);
    add(reg, 'morphology.improve_short_edges',        '1.0.0', @wrap_improve_short_edges, ...
        'morphology', 'Collapse short edges to improve triangle quality.', ...
        {}, 60000);  % H2 fix: base MATLAB only
    add(reg, 'morphology.ray_move',                   '1.0.0', @wrap_ray_move, ...
        'morphology', 'Transform ray origins/directions to a nozzle spot pose.', ...
        {}, 30000);
    add(reg, 'morphology.recursive_subdivide',        '1.0.0', @wrap_recursive_subdivide, ...
        'morphology', 'Recursively subdivide triangles until edges fit a max length.', ...
        {}, 60000);
    add(reg, 'morphology.profile_predict',            '1.0.0', @wrap_profile_predict, ...
        'morphology', 'Predict deposit profile triangles for a spray move.', ...
        {'Map_Toolbox'}, 120000);
    add(reg, 'morphology.particle_fitting',           '1.0.0', @wrap_particle_fitting, ...
        'morphology', 'Fit CFD particle distributions into ray properties (reads Excel).', ...
        {'Curve_Fitting_Toolbox'}, 120000);
    add(reg, 'morphology.read_stlfile',               '1.0.0', @wrap_read_stlfile, ...
        'morphology', 'Read an STL file into an N*9 triangle matrix (vertices only).', ...
        {}, 30000);
end

% ============================================================
% descriptor helper
% ============================================================
function add(reg, name, ver, fn, cat, desc, deps, timeout)
    d = struct();
    d.name          = name;
    d.version       = ver;
    d.fn_handle     = fn;
    d.category      = cat;
    d.description   = desc;
    d.dependencies  = deps;
    d.timeout_ms    = timeout;
    d.idempotent    = true;
    d.streaming     = false;
    d.tags          = {cat};
    d.input_schema  = struct('fields', struct());
    d.output_schema = struct('fields', struct());
    reg.register(d);
end

% ============================================================
% extraction helpers (params / inputs / packed json)
% ============================================================

function v = get_param(params, name, default)
%GET_PARAM  Read a Value from the params struct; returns default if absent.
    if nargin < 3, default = []; end
    v = default;
    if isstruct(params) && isfield(params, name)
        v = coerce_value(params.(name));
    end
end

function v = coerce_value(f)
%COERCE_VALUE  Value struct -> matlab, or pass raw value through.
    if isstruct(f) && (isfield(f,'num')||isfield(f,'intval')||isfield(f,'str')||isfield(f,'flag')||isfield(f,'tensor'))
        v = json_codec('value_to_matlab', f);
    else
        v = f;
    end
end

function m = get_input(inputs, name)
%GET_INPUT  Read a Tensor matrix from the inputs struct; [] if absent.
    m = [];
    if isstruct(inputs) && isfield(inputs, name)
        m = coerce_tensor(inputs.(name));
    end
end

function m = coerce_tensor(f)
%COERCE_TENSOR  Tensor struct -> matrix, or pass raw numeric through.
    if isstruct(f) && isfield(f,'data')
        m = json_codec('tensor_to_matrix', f);
    elseif isnumeric(f)
        m = f;
    else
        m = f;
    end
end

function c = get_input_cell(inputs, name, count)
%GET_INPUT_CELL  Reconstruct a cell of matrices from indexed inputs.
    c = cell(count, 1);
    for i = 1:count
        c{i} = get_input(inputs, sprintf('%s_%d', name, i));
    end
end

function v = get_json(params, name, default)
%GET_JSON  Read a packed-JSON cell/struct from params (Value.str or raw).
    if nargin < 3, default = []; end
    v = default;
    if isstruct(params) && isfield(params, name)
        s = coerce_value(params.(name));
        if ischar(s) || isstring(s)
            try, v = jsondecode(char(s)); catch, v = s; end
        else
            v = s;
        end
    end
end

function s = pack_json(x)
%PACK_JSON  Serialize a cell/struct to a JSON string for transport.
    s = jsonencode(x, 'ConvertInfAndNaN', true);
end

function out = ok(results, artifacts)
%OK  Assemble a success wrapper output.
    if nargin < 1, results = struct(); end
    if nargin < 2, artifacts = struct(); end
    out = struct('results', results, 'artifacts', artifacts);
end

function sa = to_strarray(x)
%TO_STRARRAY  Coerce char/cell/json-string into an N*1 string array.
    if isstring(x)
        sa = x(:);
    elseif iscell(x)
        sa = string(x);
    elseif ischar(x)
        try
            d = jsondecode(x);
            if iscell(d), sa = string(d); else sa = string(x); end
        catch
            sa = string(x);
        end
    else
        sa = string(x);
    end
    sa = sa(:);
end

% ============================================================
% PATH-PLANNING WRAPPERS
% ============================================================

function out = wrap_layer_slice(params, inputs)
    addClusters = get_json(params, 'additive_triangles_cluster', {});
    repClusters = get_json(params, 'repairing_triangles_cluster', {});
    layerHeight = get_param(params, 'layer_height', 2.0);
    basePlane   = get_param(params, 'base_plane', 0.0);
    [addList, repList] = layer_slice(addClusters, repClusters, layerHeight, basePlane);
    r = struct();
    r.additive_layerlist  = struct('str', pack_json(addList));
    r.repairing_layerlist = struct('str', pack_json(repList));
    out = ok(r, struct());
end

function out = wrap_model_process(params, inputs)
    triangles  = get_input(inputs, 'triangles');
    modelScale = get_param(params, 'model_scale', 1.0);
    tol        = get_param(params, 'tol', 1e-4);
    basePlane  = get_param(params, 'base_plane', 0.0);
    [allTri, addClu, repClu, xmin, xmax, ymin, ymax] = ...
        model_process(triangles, modelScale, tol, basePlane);
    a = struct();
    a.all_triangles = json_codec('matrix_to_tensor', allTri, 'F64', 'mm');
    r = struct();
    r.addtive_triangles_cluster    = struct('str', pack_json(addClu));
    r.repairing_triangles_cluster  = struct('str', pack_json(repClu));
    r.x_min = struct('num', xmin);
    r.x_max = struct('num', xmax);
    r.y_min = struct('num', ymin);
    r.y_max = struct('num', ymax);
    out = ok(r, a);
end

function out = wrap_generate_path(params, inputs)
    addList      = get_json(params, 'additive_layerlist', {});
    repList      = get_json(params, 'repairing_layerlist', {});
    bufAdd       = get_param(params, 'buffer_additive', 0.0);
    bufRep       = get_param(params, 'buffer_repairing', 0.0);
    scanAngle    = get_param(params, 'scanning_angle', -45.0);
    scanStep     = get_param(params, 'scanning_step', 2.0);
    edgeStep     = get_param(params, 'edge_step_size', 1.0);
    tiltAngle    = get_param(params, 'tilt_angle', 45.0);
    xmin         = get_param(params, 'x_min', 0.0);
    xmax         = get_param(params, 'x_max', 0.0);
    ymin         = get_param(params, 'y_min', 0.0);
    ymax         = get_param(params, 'y_max', 0.0);
    linkFree     = get_param(params, 'linkPath_freeDistance', 0.0);
    resolution   = get_param(params, 'resolution', 1.0);
    [pointlist, velocitylist, zonelist] = generate_path( ...
        addList, repList, bufAdd, bufRep, scanAngle, scanStep, edgeStep, ...
        tiltAngle, xmin, xmax, ymin, ymax, linkFree, resolution);
    a = struct();
    a.pointlist = json_codec('matrix_to_tensor', pointlist, 'F64', 'mm');
    r = struct();
    r.velocitylist = struct('str', pack_json(velocitylist));
    r.zonelist     = struct('str', pack_json(zonelist));
    out = ok(r, a);
end

function out = wrap_a_star_search(params, inputs)
    xGrid       = get_input(inputs, 'xGrid');
    yGrid       = get_input(inputs, 'yGrid');
    occupancy   = get_input(inputs, 'occupancyMap');
    startNode   = get_param(params, 'start_node', []);
    origGoal    = get_param(params, 'original_goal_node', []);
    goalNode    = get_param(params, 'goal_node', []);
    moveType    = get_param(params, 'movement_type', '8-connected');
    [pathX, pathY] = aStarSearch(xGrid, yGrid, occupancy, startNode, origGoal, goalNode, moveType);
    a = struct();
    a.pathX = json_codec('matrix_to_tensor', pathX, 'F64', 'mm');
    a.pathY = json_codec('matrix_to_tensor', pathY, 'F64', 'mm');
    out = ok(struct(), a);
end

function out = wrap_point_interpretaion(params, inputs)
    pointlist = get_input(inputs, 'pointlist');
    nozzle    = get_param(params, 'nozzle_normal_vector', [0 0 1]);
    tol       = get_param(params, 'tol', 1e-4);
    moves = point_interpretaion(pointlist, nozzle, tol);
    a = struct();
    a.moves_matrix = json_codec('matrix_to_tensor', moves, 'F64', 'mm');
    out = ok(struct(), a);
end

function out = wrap_read_stl_file(params, ~)
    filename = get_param(params, 'filename', '');
    triangles = read_stl_file(filename);
    a = struct();
    a.triangles = json_codec('matrix_to_tensor', triangles, 'F64', 'mm');
    out = ok(struct(), a);
end

function out = wrap_robot_command_output(params, inputs)
    moves      = get_input(inputs, 'moves_matrix');
    refPoint   = get_param(params, 'reference_point', [0 0 0]);
    velList    = to_strarray(get_param(params, 'velocitylist', strings(0,1)));
    zoneList   = to_strarray(get_param(params, 'zonelist', strings(0,1)));
    outFile    = get_param(params, 'robotcommandoutput', 'spray.mod');
    moduleID   = get_param(params, 'module_id', 'module1');
    sprayArea = robot_command_output(moves, refPoint, velList, zoneList, outFile, moduleID);
    a = struct();
    a.spray_area = json_codec('matrix_to_tensor', sprayArea, 'F64', 'mm');
    out = ok(struct(), a);
end

% ============================================================
% MORPHOLOGY WRAPPERS
% ============================================================

function out = wrap_spot_interp(params, inputs)
    refPoint  = get_param(params, 'reference_point', [0 0 0]);
    pointlist = get_input(inputs, 'pointlist');
    velList   = to_strarray(get_param(params, 'velocitylist', strings(0,1)));
    stepSize  = get_param(params, 'spot_step_size', 1.0);
    spots = spotInterp(refPoint, pointlist, velList, stepSize);
    a = struct();
    a.spots_list = json_codec('matrix_to_tensor', spots, 'F64', 'mm');
    out = ok(struct(), a);
end

function out = wrap_ray_triangle_intersection(params, inputs)
    raysIdx   = get_input(inputs, 'rays_indices');
    raysOri   = get_input(inputs, 'rays_origins');
    raysDir   = get_input(inputs, 'rays_directions');
    triangles = get_input(inputs, 'triangles');
    triCand   = get_json(params, 'tri_candidates', {});
    [rayIds, triIds, points] = ray_triangle_intersection( ...
        raysIdx, raysOri, raysDir, triangles, triCand);
    a = struct();
    a.intersected_ray_ids = json_codec('matrix_to_tensor', rayIds, 'F64', '');
    a.intersected_tri_ids = json_codec('matrix_to_tensor', triIds, 'F64', '');
    a.intersection_points = json_codec('matrix_to_tensor', points, 'F64', 'mm');
    out = ok(struct(), a);
end

function out = wrap_build_octree(params, inputs)
    triangles = get_input(inputs, 'triangles');
    maxDepth  = get_param(params, 'max_depth', 8);
    maxTri    = get_param(params, 'max_tri_per_node', 16);
    node = buildOctree(triangles, maxDepth, maxTri);
    r = struct();
    r.octree = struct('str', pack_json(node));
    out = ok(r, struct());
end

function out = wrap_batch_octree_filter(params, inputs)
    octree  = get_json(params, 'octree', struct());
    raysOri = get_input(inputs, 'rays_origins');
    raysDir = get_input(inputs, 'rays_directions');
    cand = batchOctreeFilter(octree, raysOri, raysDir);
    r = struct();
    r.tri_candidates = struct('str', pack_json(cand));
    out = ok(r, struct());
end

function out = wrap_classify_removed_triangles(params, inputs)
    triangles  = get_input(inputs, 'triangles');
    triIds     = get_input(inputs, 'intersected_tri_ids');
    nozzle     = get_param(params, 'nozzle_orientation', [0 0 1]);
    rayIds     = get_input(inputs, 'intersected_ray_ids');
    [remIdx, remClu, raysClu, bndVerts, C] = ...
        classifyRemovedTriangles(triangles, triIds, nozzle, rayIds);
    a = struct();
    a.removed_facets_idx = json_codec('matrix_to_tensor', remIdx, 'I64', '');
    r = struct();
    r.removed_facets_cluster    = struct('str', pack_json(remClu));
    r.rays_cluster              = struct('str', pack_json(raysClu));
    r.boundary_vertices_cluster = struct('str', pack_json(bndVerts));
    r.boundary_edges            = struct('str', pack_json(C));
    out = ok(r, a);
end

function out = wrap_create_triangulation_from_matrix(params, inputs)
    triangles = get_input(inputs, 'triangles');
    TR = createTriangulationFromMatrix(triangles);
    a = struct();
    a.points          = json_codec('matrix_to_tensor', TR.Points, 'F64', 'mm');
    a.connectivity    = json_codec('matrix_to_tensor', TR.ConnectivityList, 'I32', '');
    out = ok(struct(), a);
end

function out = wrap_improve_short_edges(params, inputs)
    triangles  = get_input(inputs, 'triangles');
    bndVerts   = get_input(inputs, 'boundary_vertices');
    lenThresh  = get_param(params, 'length_threshold', 1e-3);
    tri = improveShortEdges(triangles, bndVerts, lenThresh);
    a = struct();
    a.triangles = json_codec('matrix_to_tensor', tri, 'F64', 'mm');
    out = ok(struct(), a);
end

function out = wrap_ray_move(params, inputs)
    spotInfo = get_param(params, 'spot_info', []);
    raysOri  = get_input(inputs, 'rays_origins');
    raysDir  = get_input(inputs, 'rays_directions');
    [movOri, movDir, nozzle, coefThk] = rayMove(spotInfo, raysOri, raysDir);
    a = struct();
    a.move_rays_origins    = json_codec('matrix_to_tensor', movOri, 'F64', 'mm');
    a.move_rays_directions = json_codec('matrix_to_tensor', movDir, 'F64', '');
    r = struct();
    r.nozzle_orientation = struct('str', pack_json(nozzle));
    r.coef_thk = struct('num', coefThk);
    out = ok(r, a);
end

function out = wrap_recursive_subdivide(params, inputs)
    triangles = get_input(inputs, 'triangles');
    maxEdge   = get_param(params, 'max_edge_length', 1.0);
    sub = recursiveSubdivide(triangles, maxEdge);
    a = struct();
    a.triangles = json_codec('matrix_to_tensor', sub, 'F64', 'mm');
    out = ok(struct(), a);
end

function out = wrap_profile_predict(params, inputs)
    triangles  = get_input(inputs, 'triangles');
    remIdx     = get_input(inputs, 'removed_facets_idx');
    raysClu    = get_json(params, 'rays_cluster', {});
    triIds     = get_input(inputs, 'intersected_tri_ids');
    intPoints  = get_input(inputs, 'intersection_points');
    bndVerts   = get_json(params, 'boundary_vertices_cluster', {});
    nozzle     = get_param(params, 'nozzle_orientation', [0 0 1]);
    movOri     = get_input(inputs, 'move_rays_origins');
    movDir     = get_input(inputs, 'move_rays_directions');
    raysSpd    = get_input(inputs, 'rays_speeds');
    raysLen    = get_input(inputs, 'rays_possi_lengths');
    raysVcr    = get_input(inputs, 'rays_vcr');
    coefThk    = get_param(params, 'coef_thk', 1.0);
    C          = get_json(params, 'boundary_edges', {});
    lenThresh  = get_param(params, 'length_threshold', 1e-3);
    [oldTri, newTri] = profilePredict(triangles, remIdx, raysClu, triIds, intPoints, ...
        bndVerts, nozzle, movOri, movDir, raysSpd, raysLen, raysVcr, coefThk, C, lenThresh);
    a = struct();
    a.old_triangles = json_codec('matrix_to_tensor', oldTri, 'F64', 'mm');
    a.new_triangles = json_codec('matrix_to_tensor', newTri, 'F64', 'mm');
    out = ok(struct(), a);
end

function out = wrap_particle_fitting(params, ~)
    excelFile = get_param(params, 'excel_file', '');
    SoD       = get_param(params, 'sod', 30.0);
    [raysIdx, raysOri, raysDir, raysSpd, raysLen, raysVcr, lenThresh, areaThresh] = ...
        particleFitting(excelFile, SoD);
    a = struct();
    a.rays_indices       = json_codec('matrix_to_tensor', raysIdx, 'I64', '');
    a.rays_origins       = json_codec('matrix_to_tensor', raysOri, 'F64', 'mm');
    a.rays_directions    = json_codec('matrix_to_tensor', raysDir, 'F64', '');
    a.rays_speeds        = json_codec('matrix_to_tensor', raysSpd, 'F64', 'm/s');
    a.rays_possi_lengths = json_codec('matrix_to_tensor', raysLen, 'F64', 'mm');
    a.rays_vcr           = json_codec('matrix_to_tensor', raysVcr, 'F64', 'm/s');
    r = struct();
    r.length_threshold = struct('num', lenThresh);
    r.area_threshold   = struct('num', areaThresh);
    out = ok(r, a);
end

function out = wrap_read_stlfile(params, ~)
    filename = get_param(params, 'filename', '');
    triangles = read_STLfile(filename);
    a = struct();
    a.triangles = json_codec('matrix_to_tensor', triangles, 'F64', 'mm');
    out = ok(struct(), a);
end
