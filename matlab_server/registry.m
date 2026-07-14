classdef registry < handle
%REGISTRY  Algorithm registry for the MATLAB server.
%
%   Stores algorithm descriptors keyed by name. Each descriptor mirrors the
%   AlgorithmMetadata proto message and additionally carries the function
%   handle used to dispatch a request.
%
%   Methods:
%       register(descriptor)        add/replace an algorithm
%       lookup(name, version)       fetch descriptor; version '' or 'latest'
%                                    resolves to the highest registered
%       list()                      cell array of registered names
%       list_metadata()             array of AlgorithmMetadata-like structs
%       count()                     number of registered algorithms
%
%   Descriptor fields:
%       name, version, fn_handle, input_schema, output_schema,
%       dependencies, timeout_ms, idempotent, streaming, tags,
%       description, category
%
%   The function handle fn_handle(params, inputs) must return a struct with
%   fields `results` and `artifacts` (each a map-like struct of
%   Value/Tensor structs). Wrappers are defined in register_algorithms.m.

    properties (Access = private)
        % containers.Map: name (char) -> descriptor struct
        algo = []
    end

    methods
        function obj = registry()
            obj.algo = containers.Map('KeyType', 'char', 'ValueType', 'any');
        end

        function register(obj, descriptor)
            %REGISTER  Add or replace an algorithm descriptor.
            %   Required fields: name, version, fn_handle.
            this = obj.normalize(descriptor);
            obj.algo(this.name) = this;
        end

        function [desc, found] = lookup(obj, name, version)
            %LOOKUP  Fetch a descriptor by name (and optional version).
            %   version of '' or 'latest' returns the highest registered
            %   version for that name. found is false when absent.
            if nargin < 3, version = ''; end
            found = false;
            desc = [];
            if ~isKey(obj.algo, name)
                return;
            end
            d = obj.algo(name);
            if isempty(version) || strcmpi(version, 'latest')
                desc = d;
                found = true;
                return;
            end
            if strcmp(d.version, version)
                desc = d;
                found = true;
            end
        end

        function names = list(obj)
            %LIST  Cell array of registered algorithm names.
            names = keys(obj.algo);
        end

        function md = list_metadata(obj, category)
            %LIST_METADATA  Array of metadata structs (AlgorithmMetadata shape).
            %   Optional `category` filters the result.
            if nargin < 2, category = ''; end
            ks = keys(obj.algo);
            md = struct([]);
            for k = 1:numel(ks)
                d = obj.algo(ks{k});
                if ~isempty(category) && ~strcmpi(d.category, category)
                    continue;
                end
                m = struct();
                m.name             = d.name;
                m.version          = d.version;
                m.description      = d.description;
                m.category         = d.category;
                m.input_schema     = d.input_schema;
                m.output_schema    = d.output_schema;
                m.dependencies     = {d.dependencies{:}};
                m.timeout_default_ms = d.timeout_ms;
                m.streaming        = d.streaming;
                m.idempotent       = d.idempotent;
                m.tags             = {d.tags{:}};
                if isempty(md)
                    md = m;
                else
                    md(end+1) = m;
                end
            end
        end

        function n = count(obj)
            n = obj.algo.Count;
        end
    end

    methods (Access = private)
        function d = normalize(obj, d)
            %NORMALIZE  Fill optional descriptor fields with defaults so the
            %   rest of the server can assume every field exists.
            reqd = {'name','version','fn_handle'};
            for i = 1:numel(reqd)
                if ~isfield(d, reqd{i}) || isempty(d.(reqd{i}))
                    error('registry:missingField', ...
                        'Descriptor missing required field: %s', reqd{i});
                end
            end
            if ~isfield(d, 'input_schema')  || isempty(d.input_schema),  d.input_schema  = struct('fields', struct()); end
            if ~isfield(d, 'output_schema') || isempty(d.output_schema), d.output_schema = struct('fields', struct()); end
            if ~isfield(d, 'dependencies')  || isempty(d.dependencies),  d.dependencies  = {}; end
            if ~isfield(d, 'timeout_ms')    || isempty(d.timeout_ms),    d.timeout_ms    = 60000; end
            if ~isfield(d, 'idempotent')    || isempty(d.idempotent),    d.idempotent    = false; end
            if ~isfield(d, 'streaming')     || isempty(d.streaming),     d.streaming     = false; end
            if ~isfield(d, 'tags')          || isempty(d.tags),          d.tags          = {}; end
            if ~isfield(d, 'description')   || isempty(d.description),   d.description   = ''; end
            if ~isfield(d, 'category')      || isempty(d.category),      d.category      = 'general'; end
        end
    end
end
