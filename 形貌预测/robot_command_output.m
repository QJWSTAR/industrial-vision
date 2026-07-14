function sprayArea = robot_command_output(moves_matrix, ReferencePoint, velocitylist, zonelist, robotcommandoutput, moduleID)
% Output the ABB moving instructions

% Input
% moves_matrix: values of reltool instruction, [x, y, z, ax, ay, az], N*6 matrix
% ReferencePoint: translate the model for proper position on the substrate (real-word coordinates in workpiece coordinate system), 1*3 matrix
% velocitylist: name of speeddata in ABB moving instructions, N*1 string
% zonelist: name of zonedata in ABB moving instructions, N*1 string
% robotcommandoutput: name of the output file, 1*N charaters
% moduleID: name of the module in Rapid, 1*N charaters
% Output
% sprayArea: spray scope, 2*3 matrix

% Output the spray range
sprayArea_x_min = min(moves_matrix(:,1)) + ReferencePoint(1);
sprayArea_x_max = max(moves_matrix(:,1)) + ReferencePoint(1);
sprayArea_y_min = min(moves_matrix(:,2)) + ReferencePoint(2);
sprayArea_y_max = max(moves_matrix(:,2)) + ReferencePoint(2);
sprayArea_z_min = min(moves_matrix(:,3)) + ReferencePoint(3);
sprayArea_z_max = max(moves_matrix(:,3)) + ReferencePoint(3);
sprayArea = [sprayArea_x_min, sprayArea_y_min, sprayArea_z_min; ...
    sprayArea_x_max, sprayArea_y_max, sprayArea_z_max];

% Prepare the moves_matrix for output
moves_matrix = string(round(moves_matrix));
moves_matrix = [moves_matrix, velocitylist, zonelist]'; % read by column by default

% Print and output
myfile = fopen(robotcommandoutput,'w');
fprintf(myfile, 'PROC '); fprintf(myfile, moduleID); fprintf(myfile, '()\n');
fprintf(myfile, 'MoveJ StartPoint,v100,fine,tool_nozzle\x005CWObj:=wobj_substrate;\n');
formatSpec = 'MoveL RelTool(ReferencePoint,%s,%s,%s\x005CRx:=%s\x005CRy:=%s\x005CRz:=%s),%s,%s,tool_nozzle\x5CWObj:=wobj_substrate;\n';
fprintf(myfile,formatSpec,moves_matrix);
fprintf(myfile, 'MoveL Offs(StartPoint,0,0,%d),v100,fine,tool_nozzle\x005CWObj:=wobj_substrate;\n', round(sprayArea_z_max+20));
fprintf(myfile, 'ENDPROC');
fclose(myfile);
end