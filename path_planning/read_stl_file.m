function triangles = read_stl_file(filename)
%READ_STL_FILE Read a binary or ASCII STL file into an N-by-12 matrix.
%
% Columns are [x1 y1 z1 x2 y2 z2 x3 y3 z3 nx ny nz].

if nargin ~= 1 || ~(ischar(filename) || isStringScalar(filename))
    error('CSAM:InvalidSTLPath', 'STL filename must be a character vector or string scalar.');
end
filename = char(filename);
file_info = dir(filename);
if isempty(file_info) || file_info(1).isdir
    error('CSAM:STLNotFound', 'STL file not found: %s', filename);
end

% A binary STL has an exact, self-describing length. Do not classify solely
% from an initial "solid" token because valid binary headers may contain it.
is_binary = false;
if file_info(1).bytes >= 84
    fid = open_file(filename, 'rb', 'ieee-le');
    close_guard = onCleanup(@() fclose(fid)); %#ok<NASGU>
    header = fread(fid, 80, 'uint8=>uint8');
    facet_count = fread(fid, 1, 'uint32=>double');
    if numel(header) == 80 && isscalar(facet_count)
        expected_bytes = 84 + 50 * facet_count;
        is_binary = isfinite(expected_bytes) && expected_bytes == file_info(1).bytes;
    end
    clear close_guard
end

if is_binary
    triangles = read_binary_file(filename, file_info(1).bytes);
else
    triangles = read_ascii_file(filename);
end

if isempty(triangles)
    error('CSAM:EmptySTL', 'STL file contains no facets: %s', filename);
end
if size(triangles, 2) ~= 12 || any(~isfinite(triangles), 'all')
    error('CSAM:InvalidSTLData', ...
        'STL facets must form a finite N-by-12 matrix: %s', filename);
end
end

function tr = read_binary_file(filename, file_bytes)
fid = open_file(filename, 'rb', 'ieee-le');
close_guard = onCleanup(@() fclose(fid)); %#ok<NASGU>

header = fread(fid, 80, 'uint8=>uint8');
num_triangles = fread(fid, 1, 'uint32=>double');
if numel(header) ~= 80 || ~isscalar(num_triangles)
    error('CSAM:TruncatedSTL', 'Binary STL header is truncated: %s', filename);
end
if 84 + 50 * num_triangles ~= file_bytes
    error('CSAM:InvalidSTLLength', ...
        'Binary STL length does not match its facet count: %s', filename);
end

tr = zeros(num_triangles, 12);
for idx = 1:num_triangles
    values = fread(fid, 12, 'single=>double');
    attribute = fread(fid, 1, 'uint16=>uint16'); %#ok<NASGU>
    if numel(values) ~= 12
        error('CSAM:TruncatedSTL', ...
            'Binary STL ended while reading facet %d of %d: %s', ...
            idx, num_triangles, filename);
    end
    % STL stores normal first and then the three vertices.
    tr(idx, :) = [values(4:12).', values(1:3).'];
end
end

function tr = read_ascii_file(filename)
fid = open_file(filename, 'rt');
close_guard = onCleanup(@() fclose(fid)); %#ok<NASGU>

vertices = zeros(0, 3);
normals = zeros(0, 3);
while true
    line = fgetl(fid);
    if ~ischar(line)
        break;
    end
    trimmed = strtrim(line);
    if startsWith(trimmed, 'facet normal', 'IgnoreCase', true)
        value = sscanf(trimmed, '%*s %*s %f %f %f');
        if numel(value) ~= 3
            error('CSAM:InvalidASCIISTL', ...
                'Invalid facet normal in ASCII STL: %s', filename);
        end
        normals(end + 1, :) = value.'; %#ok<AGROW>
    elseif startsWith(trimmed, 'vertex', 'IgnoreCase', true)
        value = sscanf(trimmed, '%*s %f %f %f');
        if numel(value) ~= 3
            error('CSAM:InvalidASCIISTL', ...
                'Invalid vertex in ASCII STL: %s', filename);
        end
        vertices(end + 1, :) = value.'; %#ok<AGROW>
    end
end

if mod(size(vertices, 1), 3) ~= 0
    error('CSAM:InvalidASCIISTL', ...
        'ASCII STL vertex count is not divisible by three: %s', filename);
end
facet_count = size(vertices, 1) / 3;
if size(normals, 1) ~= facet_count
    error('CSAM:InvalidASCIISTL', ...
        'ASCII STL has %d facets but %d normals: %s', ...
        facet_count, size(normals, 1), filename);
end
tr = [reshape(vertices.', 9, []).', normals];
end

function fid = open_file(filename, permission, varargin)
fid = fopen(filename, permission, varargin{:});
if fid == -1
    error('CSAM:STLOpenFailed', 'Unable to open STL file: %s', filename);
end
end
