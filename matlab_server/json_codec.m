function out = json_codec(action, varargin)
%JSON_CODEC  JSON encode/decode helpers for the MATLAB server (Protocol v3.0).
%
%   The MATLAB server uses a JSON-over-TCP wire format that mirrors the
%   protobuf schema defined in algorithm_protocol_v3.proto. Binary tensor
%   payloads are encoded as base64 strings so that a single jsonencode /
%   jsondecode round-trip is sufficient to move a complete Envelope.
%
%   This is a dispatch function. Call it with an action name:
%
%     json_codec('encode_struct', s)            -> json string (char)
%     json_codec('decode_request', json_str)    -> struct (envelope)
%     json_codec('matrix_to_tensor', m)         -> tensor struct
%     json_codec('matrix_to_tensor', m, dtype)  -> tensor struct
%     json_codec('matrix_to_tensor', m, dtype, units)
%     json_codec('tensor_to_matrix', t)         -> double matrix
%     json_codec('value_to_matlab', v)          -> matlab value
%     json_codec('matlab_to_value', x)          -> value struct
%     json_codec('base64encode', uint8_bytes)   -> char
%     json_codec('base64decode', b64_str)       -> uint8 row vector
%
%   Tensor JSON format (matches the Python codec):
%       {"dtype":"F64","shape":[3,6],"data":"<base64>","units":"mm"}
%
%   Value JSON format (oneof kind):
%       {"num":1.5} | {"intval":3} | {"str":"abc"} | {"flag":true}
%       | {"tensor":{...}}
%
%   Shape is row-major (as in protobuf); MATLAB's column-major layout is
%   handled by an explicit permute so round-trips are exact.

    switch action
        case 'encode_struct'
            out = encode_struct(varargin{1});
        case 'decode_request'
            out = decode_request(varargin{1});
        case 'matrix_to_tensor'
            if nargin >= 3, dtype = varargin{2}; else, dtype = 'F64'; end
            if nargin >= 4, units = varargin{3}; else, units = ''; end
            out = matrix_to_tensor(varargin{1}, dtype, units);
        case 'tensor_to_matrix'
            out = tensor_to_matrix(varargin{1});
        case 'value_to_matlab'
            out = value_to_matlab(varargin{1});
        case 'matlab_to_value'
            out = matlab_to_value(varargin{1});
        case 'base64encode'
            out = base64encode_bytes(varargin{1});
        case 'base64decode'
            out = base64decode_str(varargin{1});
        otherwise
            error('json_codec:unknownAction', 'Unknown action: %s', action);
    end
end

% ============================================================
% Struct <-> JSON string
% ============================================================

function s = encode_struct(obj)
%ENCODE_STRUCT  Convert a MATLAB struct/cell to a compact JSON string.
%   Binary (uint8) arrays inside the struct are NOT auto-encoded here; use
%   matrix_to_tensor first. jsonencode handles nested structs/cells/strings.
    s = jsonencode(obj, 'ConvertInfAndNaN', true, 'PrettyPrint', false);
end

function env = decode_request(json_str)
%DECODE_REQUEST  Parse a JSON envelope string into a MATLAB struct.
%   Accepts char, string, or uint8 bytes. Returns an empty struct on failure
%   so the caller can surface a clean protocol error instead of crashing.
    try
        if isinteger(json_str) || isuint8(json_str)
            json_str = char(json_str(:).');
        elseif isstring(json_str)
            json_str = char(json_str);
        end
        env = jsondecode(json_str);
    catch err
        env = struct();
        env.__decode_error = err.message;
    end
end

% ============================================================
% Tensor <-> MATLAB matrix
% ============================================================

function t = matrix_to_tensor(m, dtype, units)
%MATRIX_TO_TENSOR  Pack a MATLAB matrix into the Tensor JSON struct.
%   m     : numeric matrix (double / single / int32 / int64 / uint8 / logical)
%   dtype : 'F64' | 'F32' | 'I32' | 'I64' | 'U8'  (default auto from class)
%   units : optional units string, e.g. 'mm'
    if nargin < 2 || isempty(dtype), dtype = ''; end
    if nargin < 3, units = ''; end
    if isempty(dtype)
        dtype = default_dtype_for(m);
    end

    shape = size(m);
    % Convert to row-major byte order: reverse dims, flatten column-major.
    if isempty(m)
        vec = m;
    else
        mperm = permute(m, ndims(m):-1:1);
        vec = mperm(:);
    end
    data_bytes = typed_bytes(vec, dtype);

    t = struct();
    t.dtype  = dtype;
    t.shape  = shape;          % keep as row vector; jsonencode -> [a b c]
    t.data   = base64encode_bytes(data_bytes);
    t.units  = units;
end

function m = tensor_to_matrix(t)
%TENSOR_TO_MATRIX  Unpack a Tensor JSON struct into a MATLAB double matrix.
%   The matrix is reshaped respecting the row-major shape stored in t.shape.
    if isempty(t) || ~isfield(t, 'data')
        m = [];
        return;
    end
    dtype = 'F64';
    if isfield(t, 'dtype') && ~isempty(t.dtype), dtype = t.dtype; end
    raw = base64decode_str(t.data);
    vec = bytes_to_typed(raw, dtype);
    if isfield(t, 'shape') && ~isempty(t.shape)
        shape = t.shape;
        shape = shape(:).';   % row vector
        if isempty(vec)
            m = zeros(shape);
        else
            % reshape into reversed shape (row-major -> column-major), then
            % permute back to the declared dimension order.
            rev = shape(end:-1:1);
            m = reshape(vec, rev);
            m = permute(m, numel(shape):-1:1);
        end
    else
        m = vec(:);
    end
end

% ============================================================
% Value <-> MATLAB scalar/matrix/string
% ============================================================

function v = value_to_matlab(val)
%VALUE_TO_MATLAB  Convert a Value oneof struct to a native MATLAB value.
%   Recognised keys: num, intval, str, flag, tensor. Unknown/empty -> [].
    if isempty(val) || ~isstruct(val)
        v = val;
        return;
    end
    if isfield(val, 'num') && ~isempty(val.num)
        v = val.num;
    elseif isfield(val, 'intval') && ~isempty(val.intval)
        v = val.intval;
    elseif isfield(val, 'str') && ~isempty(val.str)
        v = val.str;
    elseif isfield(val, 'flag') && ~isempty(val.flag)
        v = val.flag;
    elseif isfield(val, 'tensor') && ~isempty(val.tensor)
        v = tensor_to_matrix(val.tensor);
    else
        v = [];
    end
end

function val = matlab_to_value(x)
%MATLAB_TO_VALUE  Convert a native MATLAB scalar/value to a Value struct.
    val = struct();
    if islogical(x)
        val.flag = logical(x);
    elseif ischar(x) || isstring(x)
        val.str = char(x);
    elseif isinteger(x) && isscalar(x)
        val.intval = double(x);
    elseif isnumeric(x) && isscalar(x)
        val.num = double(x);
    elseif isnumeric(x) && ~isscalar(x)
        val.tensor = matrix_to_tensor(x);
    elseif iscell(x) && numel(x) == 1
        % unwrap single-element cell
        val = matlab_to_value(x{1});
    else
        val.str = jsonencode(x);
    end
end

% ============================================================
% dtype helpers
% ============================================================

function dt = default_dtype_for(m)
    if islogical(m) || isa(m, 'uint8')
        dt = 'U8';
    elseif isa(m, 'int32')
        dt = 'I32';
    elseif isa(m, 'int64')
        dt = 'I64';
    elseif isa(m, 'single')
        dt = 'F32';
    else
        dt = 'F64';
    end
end

function b = typed_bytes(vec, dtype)
    switch upper(dtype)
        case 'F64', b = typecast(double(vec(:)),  'uint8');
        case 'F32', b = typecast(single(vec(:)),  'uint8');
        case 'I32', b = typecast(int32(vec(:)),   'uint8');
        case 'I64', b = typecast(int64(vec(:)),   'uint8');
        case 'U8',  b = uint8(vec(:));
        otherwise
            error('json_codec:badDtype', 'Unsupported dtype: %s', dtype);
    end
    b = b(:).';
end

function v = bytes_to_typed(b, dtype)
    b = b(:);
    switch upper(dtype)
        case 'F64', v = double(typecast(uint8(b), 'double'));
        case 'F32', v = double(typecast(uint8(b), 'single'));
        case 'I32', v = double(typecast(uint8(b), 'int32'));
        case 'I64', v = double(typecast(uint8(b), 'int64'));
        case 'U8',  v = double(uint8(b));
        otherwise
            error('json_codec:badDtype', 'Unsupported dtype: %s', dtype);
    end
end

% ============================================================
% base64 helpers (prefer matlab.net, fall back to Java)
% ============================================================

function s = base64encode_bytes(b)
    b = uint8(b(:).');
    persistent enc
    if isempty(enc)
        try
            enc = 'matlab.net';
        catch
            enc = 'java';
        end
    end
    if strcmp(enc, 'matlab.net')
        try
            s = char(matlab.net.base64encode(b));
            return;
        catch
            enc = 'java';
        end
    end
    % Java fallback: java.util.Base64
    % L2 fix: removed dead javaArray/java.lang.Byte loop (never used by
    % encodeToString; java.lang.Byte(int) deprecated since Java 9)
    s = char(java.util.Base64.getEncoder().encodeToString(int8(b)));
end

function b = base64decode_str(s)
    if isstring(s), s = char(s); end
    persistent dec
    if isempty(dec)
        try
            dec = 'matlab.net';
        catch
            dec = 'java';
        end
    end
    if strcmp(dec, 'matlab.net')
        try
            b = matlab.net.base64decode(string(s));
            b = b(:).';
            return;
        catch
            dec = 'java';
        end
    end
    % Java fallback
    bytes = java.util.Base64.getDecoder().decode(int8(s));
    b = uint8(bytes).';
end
