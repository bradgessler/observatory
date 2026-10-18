---
title: "You can't plate solve the Moon, and you don't need to"
date: 2026-10-17
kind: note
summary: "My telescope finds where it's pointing by matching stars. A photo of the Moon has no stars in it. Here's how it would point at the Moon anyway, and how one grey photo showed my garage was in the way."
hero: "images/2026-10-17-moon-behind-garage.jpg"
hero_alt: "A flat grey photo with a few faint dust rings and no stars"
---

The Moon was out early tonight, a little less than half lit, low in the southwest. My telescope's focus was off and I wasn't home yet. So I asked Claude, the AI that runs my telescope with me, whether it could find the Moon by itself and take some pictures while it waited.

## The problem: my telescope aims by looking at stars

My telescope figures out where it's pointing with a trick called plate solving. It takes a photo, finds the stars in it, and compares their pattern to a map of millions of stars. When the pattern matches, it knows exactly which bit of sky it's looking at. Then it compares that with where it wanted to point and nudges itself the difference.

The Moon breaks this. It's so bright that a photo of it has to be very quick, 1/250 of a second tonight. A photo that quick doesn't catch any stars at all, so there's nothing to match.

## Why that's fine: the Moon is bigger than the view

My camera on this telescope sees a patch of sky about two thirds of a degree wide. The Moon is half a degree across, so it nearly fills the view. Once the telescope is set up, it points to within about one sixtieth of a degree. That's close enough for the Moon to land right in the picture without any stars to help.

There's one thing my software can't do yet. The Moon slowly slides across the starry background, about its own width every hour. My telescope follows the stars, so it would slowly lose the Moon. For a few quick pictures that doesn't matter. For a big picture of the whole Moon it would, so it's on my list to fix.

## What happened: the first photo came back black

The Moon had already crossed the line straight overhead, from east to west. My mount has to swing the telescope over to its other side to point there, which is called a meridian flip. Claude checked that the heavy counterweight would end up hanging below the telescope, where it's safe, and sent it.

The first picture was completely black. Not a single pixel had any light in it.

## One grey photo told us why

Next Claude took a 2 second picture at the camera's most sensitive setting. That's about 16,000 times more light, enough to see whatever was in front of the telescope.

![A flat grey photo with a few faint dust rings and no stars](images/2026-10-17-moon-behind-garage.jpg "Two seconds pointed at the Moon. Even grey from edge to edge, no stars, just the faint rings of dust on the camera. Something lit was in front of the telescope.")

Here's how Claude worked it out. If the Moon were just outside the picture, one side would be much brighter, because the sky right next to the Moon glows. If the telescope were looking at open sky, there would be stars. It measured the brightness across the picture in a grid of nine squares. The middle read 150 out of 255 and the corners about 137. Telescopes are always a little darker at the edges, so that's normal. There was no bright side and no stars, so something solid was blocking the view. I'd already told Claude the garage might be in the way. The Moon was behind it and sinking lower.

## What I learned: a low Moon isn't worth chasing anyway

Even without the garage it wouldn't have been a great picture. When something is low in the sky, you're looking at it through a lot more air, and air shimmers like the air over a hot road. That shimmer blurs the fine details you want on the Moon, like the edges of craters. In winter, the Moon at this phase climbs high in the evening sky, and that's when I'll try again.

So Claude gave up on the Moon and pointed the telescope at Vega instead, a bright star high in the west, so I'd have something to focus on when I got home.
