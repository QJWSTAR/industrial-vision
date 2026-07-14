function createvideo(savevideo, path, totalFrame)
% Create video of profile prediction based on figures

% Input
% path: storage path
% totalFrame: total frames of the video

if ~savevideo
    return
end

myobj = VideoWriter([path '\Video'],'MPEG-4');
myobj.FrameRate = 30;
open(myobj);
for i = 1:totalFrame
    fname = strcat(path, num2str(i),'.jpg');
    frame = imread(fname);
    writeVideo(myobj,frame);
end
close(myobj);