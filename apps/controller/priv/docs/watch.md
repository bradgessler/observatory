# Watch

A camera pointed at the mount, read by the server, shown to anyone.

## Why it exists

Answering "is it about to wrap a cable?" from the far side of the yard, or
from another city. And giving software eyes: an agent can look at the last
twenty minutes of frames and say what happened.

## Stills and video

* **Stills** are the default: a frame every few seconds while anyone is
  looking, kept for the last 240 frames / 20 minutes / 256 MB under
  `~/.observatory/watch/frames`. *Recent Frames* shows them; `/watch/frames/<name>`
  serves them.
* **Play** starts live video: FFmpeg on the server encodes H.264 into HLS,
  which Safari plays natively and other browsers play through hls.js. One
  encoder, however many viewers. The caption says how far behind reality the
  picture is and the frame rate you are actually getting.
* *Auto* size is 720p — every camera does it and a small machine encodes it
  easily. Bigger sizes are a choice on the *Camera* page; a size the camera
  won't deliver falls back one step by itself.

## Two lessons, kept here so they aren't relearned

* Never open the camera from two processes at once. macOS renegotiates the
  shared capture format under the running stream and the picture becomes
  interleaved garbage. While video runs, stills come from the encoder.
* Ask AVFoundation for the pixel format the camera really delivers
  (`uyvy422`). Asking for `nv12` "works" — segments flow — and the H.264 is
  purple-and-green stripes.

## When there is no camera

Not every telescope has a camera watching it, and a still can go cold. When
there is nothing fresh to look at, the frame shows the mount **drawn from its
own encoders** instead of a black box: the same picture as the Scope page,
turning as the mount turns. The caption says so, and how old the camera's last
picture was. With a camera present you can pin either one: Auto, Picture or
Drawing.
