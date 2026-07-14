function info = resource_cleanup(cfg)
%RESOURCE_CLEANUP  Periodic in-process memory reclamation.
%
%   info = resource_cleanup(cfg)
%
%   Called by the server every N requests (cfg.cleanup_interval). MATLAB is
%   single-threaded, so cleanup runs synchronously between requests - never
%   on a background thread.
%
%   Actions:
%     1. Run `pack` to defragment memory when Java RSS exceeds
%        cfg.memory_threshold_mb. `pack` only works at the command prompt,
%        so when running as a function it is skipped in favour of Java GC.
%     2. Invoke java.lang.System.gc() to nudge the JVM heap.
%     3. Return a small report struct.
%
%   CRITICAL: This function NEVER calls `clear all` or `clear` without
%   arguments - that would wipe the running server's registry, lifecycle and
%   socket state. Only local temporaries are scoped to this function and
%   therefore freed automatically on return.

    if nargin < 1 || isempty(cfg)
        cfg = struct('memory_threshold_mb', 4096);
    end

    info = struct();
    info.ran_at    = char(datetime('now','TimeZone','UTC'));
    info.mem_before_mb = memory_usage_mb();

    % Trigger JVM garbage collection (cheap, always available).
    try, java.lang.System.gc(); catch, end

    % M2 fix: 'pack' cannot run from within a function (errors "pack can only
    % be called at the prompt"), so evalin('base','pack') was always a no-op.
    % Memory defragmentation must be run manually by the operator if needed;
    % here we rely on System.gc() + drawnow to release figure handles.
    if info.mem_before_mb > cfg.memory_threshold_mb
        try, drawnow('reduce'); catch, end
    end
    info.packed = false;  % operator must run `pack` manually if required

    info.mem_after_mb = memory_usage_mb();
end

% ============================================================
function mb = memory_usage_mb()
    mb = 0;
    try
        rt = java.lang.Runtime.getRuntime();
        used = rt.totalMemory() - rt.freeMemory();
        mb = double(used) / (1024 * 1024);
    catch
    end
    if mb <= 0
        try
            m = memory;
            mb = m.MemUsedMATLAB / (1024 * 1024);
        catch
        end
    end
end
