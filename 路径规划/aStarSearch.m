function [pathX, pathY] = aStarSearch(xGrid, yGrid, occupancyMap, StartNode, OriginalGoalNode, GoalNode, movementType)
% Implementation of A* path search algorithm

% Input
%   xGrid                the X vectors of the substrate grid, N1*N2 matrix
%   yGrid                the Y vectors of the substrate grid, N1*N2 matrix
%   occupancyMap         the raster graph occupied by binary values (true=obstacles, false=free space), N1*N2 matrix
%   startNode            the node index of start point on the substrate grid, [row, col], 1*2 matrix
%   originalgoalNode     the original node index of start point on the substrate grid, [row, col], 1*2 matrix
%   goalNode             the adjusted originalgoalNode in case of locating inside the obstacles or at the boundaries, [row, col], 1*2 matrix
%   movementType         movement type ('4-connected' or '8-connected'), 1*N charaters
% Output
%   pathX                the X coordinates of link path (real-world coordinates), 1*N matrix
%   pathY                the Y coordinates of link path (real-world coordinates), 1*N matrix

% Parameters check
if size(occupancyMap, 1) ~= length(yGrid) || size(occupancyMap, 2) ~= length(xGrid)
    error('The size of occupancyMap dose not match xGrid/yGrid');
end

% Default parameters processing
if nargin < 7
    movementType = '8-connected'; % by default, move in 8 directions
end
maxWeight = 2; %default maximum weight

% Get the substrate grid map size
[mapRows, mapCols] = size(occupancyMap);

% Initialize the node information matrix
gScore = inf(mapRows, mapCols);    % the actual cost from the start node to this node
fScore = inf(mapRows, mapCols);    % estimated total cost, f = g + h
cameFrom = cell(mapRows, mapCols); % record the parent node of each node

% Initialize the start node
startRow = StartNode(1);
startCol = StartNode(2);
initialDist = heuristic(StartNode, GoalNode, movementType);

gScore(startRow, startCol) = 0;
fScore(startRow, startCol) = dynamicWeight(startRow, startCol, GoalNode, movementType, initialDist, maxWeight) * ...
    heuristic(StartNode, GoalNode, movementType);

% Initialize the openSet（priority queue, sorted by fScore）
openSet = containers.Map();
openSetKey = mat2str([startRow, startCol]);
openSet(openSetKey) = [startRow, startCol, fScore(startRow, startCol)];

% Initialize the closeSet
closedSet = false(mapRows, mapCols);

% Define the direction of movement
if strcmpi(movementType, '4-connected')
    % Move in 4 directions：up, down, left, right
    directions = [ -1,  0;  % up
                    1,  0;  % down
                    0, -1;  % left
                    0,  1]; % right
else
    % Move in 8 directions：including the diagonal
    directions = [ -1, -1;  % upper left
                   -1,  0;  % up
                   -1,  1;  % upper right
                    0, -1;  % left
                    0,  1;  % right
                    1, -1;  % lower left
                    1,  0;  % down
                    1,  1]; % lower right
end

% A* main loop
while ~isempty(openSet)
    % Obtain the node with the smallest fScore from the openSet
    currentNode = getMinFNode(openSet);
    currentRow = currentNode(1);
    currentCol = currentNode(2);
    
    % If the target node is found, reconstruct the path
    if currentRow == GoalNode(1) && currentCol == GoalNode(2)
        [pathRows, pathCols] = reconstructPath(cameFrom, GoalNode);
        break;
    end
    
    % Add the current node to the closeSet
    closedSet(currentRow, currentCol) = true;
    
    % Remove the current node from the openSet
    currentKey = mat2str([currentRow, currentCol]);
    if isKey(openSet, currentKey)
        remove(openSet, currentKey);
    end
    
    % Check all the neighbors
    for i = 1:size(directions, 1)
        neighborRow = currentRow + directions(i, 1);
        neighborCol = currentCol + directions(i, 2);
        
        % Skip invalid neighbors（Beyond the boundary or an obstacle）
        if ~isValidNeighbor(neighborRow, neighborCol, mapRows, mapCols, occupancyMap)
            continue;
        end
        
        % Skip the neighbors that are already in the closeSet
        if closedSet(neighborRow, neighborCol)
            continue;
        end
        
        % Calculate the tentative gScore from the start node through the current node to the neighbor
        if abs(directions(i, 1)) + abs(directions(i, 2)) == 2
            % Diagonal movement, at a cost of√2
            tentativeGScore = gScore(currentRow, currentCol) + sqrt(2);
        else
            % Horizontal or vertical movement, at a cost of 1
            tentativeGScore = gScore(currentRow, currentCol) + 1;
        end
        
        % Check if this path is better
        neighborKey = mat2str([neighborRow, neighborCol]);
        if ~isKey(openSet, neighborKey) || tentativeGScore < gScore(neighborRow, neighborCol)
            % This is a better path, record it
            cameFrom{neighborRow, neighborCol} = [currentRow, currentCol];
            gScore(neighborRow, neighborCol) = tentativeGScore;
            w = dynamicWeight(neighborRow, neighborCol, GoalNode, movementType, initialDist, maxWeight);% dynamic calculation of weights
            fScore(neighborRow, neighborCol) = tentativeGScore + w * heuristic([neighborRow, neighborCol], GoalNode, movementType);
            
            % Add to the openSet
            if ~isKey(openSet, neighborKey)
                openSet(neighborKey) = [neighborRow, neighborCol, fScore(neighborRow, neighborCol)];
            end
        end
    end
end

% If the open set is empty and no path has been found
if isempty(openSet) && exist('pathRows','var') == 0 && exist('pathCols','var') == 0
    pathRows = [];
    pathCols = [];
    warning('The A* algorithm cannot find the path from the start node to the goal node!');
end

% Add the original goal node to the list
if ~isequal(OriginalGoalNode, GoalNode)
    pathRows = [pathRows; OriginalGoalNode(1)];
    pathCols = [pathCols; OriginalGoalNode(2)];
end

% Convert the grid index of the path back to real-world coordinates
pathX = xGrid(pathCols);
pathY = yGrid(pathRows);
end

%% Auxiliary Functions
function w = dynamicWeight(row, col, goalNode, movementType, initialDist, maxWeight)
% Calculate the distance from the current node to the goal node
currentDist = heuristic([row, col], goalNode, movementType);

% Dynamic weight formula
w = 1 + (maxWeight - 1) * (1 - currentDist / initialDist);

% Make sure the weights are within the range of [1, maxWeight]
w = max(1, min(maxWeight, w));
end

function h = heuristic(node, goal, movementType)
% Heuristic function: Calculate the estimated cost from the node to the goal node
if strcmpi(movementType, '4-connected')
    % Manhattan distance
    h = abs(node(1) - goal(1)) + abs(node(2) - goal(2));
else
    % Euclidean distance（suitable for move in 8 directions）
    h = sqrt((node(1) - goal(1))^2 + (node(2) - goal(2))^2);
end
end

function valid = isValidNeighbor(row, col, maxRows, maxCols, occupancyMap)
% Check whether the neighbor nodes are valid
valid = (row >= 1) && (row <= maxRows) && ...
        (col >= 1) && (col <= maxCols) && ...
        ~occupancyMap(row, col); % not an obstacle
end

function minNode = getMinFNode(openSet)
% Obtain the node with the smallest fScore from the openSet
minF = inf;
minNode = [];

keys = openSet.keys();
for i = 1:length(keys)
    key = keys{i};
    nodeInfo = openSet(key);
    if nodeInfo(3) < minF
        minF = nodeInfo(3);
        minNode = nodeInfo(1:2);
    end
end
end

function [pathRows, pathCols] = reconstructPath(cameFrom, goalNode)
% Reconstruct the complete path by backtracking from the goal node
pathRows = [];
pathCols = [];

currentNode = goalNode;
while ~isempty(cameFrom{currentNode(1), currentNode(2)})
    pathRows = [currentNode(1); pathRows];
    pathCols = [currentNode(2); pathCols];
    currentNode = cameFrom{currentNode(1), currentNode(2)};
end

% Add the start node
pathRows = [currentNode(1); pathRows];
pathCols = [currentNode(2); pathCols];
end