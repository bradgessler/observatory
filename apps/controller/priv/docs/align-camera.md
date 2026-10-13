# Align with the Camera

With a camera on the telescope, the box can align itself. It takes a picture of the sky, works out exactly where that picture is from its stars (plate solving), moves the telescope a little and does it again. Once four pictures agree, they are the alignment: Go To and tracking go through them. No star names, no eye at the eyepiece, and no need for the tripod to be level or the mount to point north.

Any camera on the telescope will do. A video camera sends many frames a second; a camera like the Sony a6000 sends one picture every few seconds. To the alignment they are the same thing: pictures through the telescope.

## The steps

**1. Camera.** The page shows the camera it found, its latest picture and how long ago that was taken. Take a Test Picture shows what the camera sees right now: you want stars, small and round. No stars means the lens cap, a tree, cloud, or the focus is far out.

**2. Pictures.** Start Aligning takes at least four pictures, about 15 degrees apart. The telescope moves by itself between them: keep clear, and keep the cables free. Each picture has a row that says where it is:

- *Reading the picture*, then *Found 48 stars*.
- *Matching against the whole sky*: the solver is looking for those stars with no idea where the telescope points. The first three pictures are always solved this way. On the Pi it takes about ten seconds when it works.
- *Matching near where the mount thinks it points*: from the fourth picture on, the pictures so far say roughly where to look, which is quicker.
- *Solved*, with how long it took, or *No match* and why.

The bar beside a picture is the time its solve has used of the time it is allowed (two minutes). A picture that does not solve is skipped and the telescope moves on. Three in a row, and the page asks you to move the telescope to open sky and tap Continue.

**3. Counterweight.** A mount whose home was never set can reach every part of the sky two ways, one from each side, and the pictures look the same from both. So the page asks one question: is the counterweight below or above level right now? Look at the bar the weight slides on. Go To waits for the answer.

**4. Look.** Aligned, and how well: the pictures agree to so many arcminutes. Under one arcminute is good. From here, Tonight's List.

## When it does not work

- **Every picture says too few stars.** Take a test picture. If it is black: the cap, or the camera is not in a mode that takes pictures by USB (PC Remote on a Sony). If it is grey with no points: cloud, or the focus.
- **Pictures find stars but no match.** The focal length in Setup may be far from the telescope's, or the stars are badly out of focus (rings, not points).
- **It stops and says STOP was pressed.** STOP on any page or the game controller ends it. Start again.
- **The game controller moved the telescope during the run.** A picture taken while the telescope moves is taken again. Leave the controller alone until the run ends.

No camera on the telescope? [Align by Phone Photo](/docs/align-photo) does the same with a phone held to the eyepiece, and [Align by Stars](/docs/align) with your eye.
