---
title: "My telescope's new dust detector mistook a galaxy for dust"
date: 2026-10-17
kind: note
summary: "A few hours after we taught the telescope to find dust on its camera by itself, it decided 122 specks of dust were covering 14 percent of the camera. Most of them were the galaxy. The fix was the same test I'd done by eye."
---

Earlier tonight I spotted dust on my camera's sensor, and Claude taught the telescope's computer to find dust by itself and step around it. This note is about what happened the first time that ran on the real telescope, because it went wrong in a way that's worth learning from.

## How the dust detector works

Dust sits on the camera's sensor, so it shows up in the same place in every picture. Stars and galaxies move when the telescope moves. So the detector takes a bunch of pictures from different places in the sky and, for each spot on the sensor, takes the middle value of all of them. Anything that moves around, like stars, gets averaged away. Anything stuck in place, like dust, stays. Then it looks for the dark spots.

When we tested it on the Mac with pictures of two different objects, the Dumbbell Nebula and the Triangulum Galaxy, it found the same dust I'd seen and said the telescope should move about 1.5 arcminutes between pictures to step around it. (An arcminute is a sixtieth of a degree, a sliver of the camera's view.)

## What went wrong on the real telescope

After we loaded the new software onto the little computer on the tripod, the memory of earlier pictures was wiped. So the detector started from scratch, and the only long pictures it saw for the next hour were of the Triangulum Galaxy.

The telescope was already moving a little between pictures, so the detector counted each move as a "different place in the sky." But the galaxy fills almost the whole picture, and the moves were tiny compared to it. The galaxy barely moved. Its dark lanes, the darker gaps between its spiral arms, stayed in nearly the same place in every picture, which is exactly what dust does.

So the detector reported 122 specks of dust covering 14 percent of the sensor, and decided the telescope should move 4 arcminutes between pictures to get around them. That's way too much. It wasn't a disaster, because bigger moves still make good pictures, but the number was obviously wrong. The real answer is about a dozen specks covering 1 percent.

## The fix was the test I'd done by eye

When I first asked whether the spots were dust, the test we used was simple: look at the same spots in pictures of two completely different objects. If the dark spot is there in both, it's on the camera. If it's only in one, it's part of that object.

The detector was skipping that step. It was mixing everything into one big pile. Now it makes a separate map for each object it photographs, and a spot only counts as dust if it's dark in every map. A galaxy's dark lane is only in the galaxy's pictures, so it's thrown out. Dust is in all of them, so it stays.

Run on tonight's pictures of the Dumbbell Nebula and the Triangulum Galaxy, the new version finds 14 specks covering 1.1 percent of the sensor and picks 1.5 arcminute moves again, the same as we chose by hand. It also refuses to trust a map from before this rule, so the bad map saved on the telescope gets thrown away.

## What I learned

Testing on the Mac worked because we happened to give it two different objects. The real telescope gave it one. The bug was in the assumption that "the telescope moved a bit" is the same as "a different part of the sky", and it isn't when the thing you're photographing is bigger than the move. When you build something that makes decisions on its own, test it on the situation it will actually be in, not just the nice example you have handy.
