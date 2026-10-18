---
title: "Focusing a telescope by reading a number instead of squinting"
date: 2026-10-17
kind: note
summary: "My stars were blurry donuts. The software measured every picture and put one number on my phone, and I turned the focus knob until the number got small."
hero: "images/2026-10-17-focus-before-after.jpg"
hero_alt: "Vega and two nearby stars, twice: on the left the small stars are rings, on the right they are points"
---

## The problem: every star was a donut

The first pictures tonight were out of focus. Not a little soft. Every star was a ring with a hole in the middle.

Astronomers measure sizes in the sky with angles, and a really small angle is called an arcsecond. One arcsecond is about the width of a coin seen from 5 kilometers away. My stars were 12 arcseconds wide. Last week this telescope made them 4 to 5.

No software can fix blurry pictures after they're taken. The light is already spread out. Claude told me as much, and I told it I could dial in the focus in 45 minutes.

## Why a blurry star looks like a donut

My telescope is a Celestron 8SE. Light comes in the front, bounces off a big curved mirror at the back, then off a small mirror stuck in the middle of the front glass, and finally goes back out through a hole in the big mirror to the camera.

That small mirror blocks the middle of the incoming light. When the telescope is in focus you never notice, because all the light comes together in one point. When it's out of focus, every star turns into a little picture of the telescope's opening, with the small mirror's shadow as the hole. The bigger the donut, the more out of focus you are.

## The fix: measure the stars instead of eyeballing them

Judging focus by eye on a tiny camera screen in the dark is miserable. So the software measures it for you. In every picture it finds the stars, and for each one it measures how wide a circle you'd need to hold half of that star's light. Astronomers call that the half-flux diameter. It works just as well on a donut as on a sharp point, so it always tells you how far off you are.

The software takes the middle value of all the stars in a picture and shows it on the camera page as "Star size", next to the number from the picture before.

## Getting ready before I got home

While I was still out, Claude pointed the telescope at Vega, a bright star high in the sky, and set the camera taking a 2 second picture over and over, one about every 17 seconds. When I got there, all I had to do was turn the knob, wait for the next picture, and look at the number.

On an 8SE the focus knob is on the back of the tube. It slides the big mirror back and forth. There's no lock and no fine adjustment, just the knob. I turned it a bit and Claude read the next pictures.

![Vega and two nearby stars, twice: on the left the small stars are rings, on the right they are points](images/2026-10-17-focus-before-after.jpg "The same patch of sky around Vega, before and after one turn of the focus knob. On the left the two small stars on either side of Vega are rings. On the right they are points. The software measured 12.2 arcseconds before and 4.8 after.")

Picture by picture, the numbers went 12.8, 12.2, then 4.8 and 5.2. One turn in the right direction and it was there.

## How small is small enough

You can't shrink a star to nothing, because the air between you and the star is always moving and smears it a little. On a typical night here that blur is about 4 arcseconds. Once you're at 5, turning the knob more mostly chases the air. Claude's advice was to stop there rather than risk turning past it.

## Try it yourself

If you have a camera on your telescope and software that measures star size (lots of free camera programs do, under names like HFD or FWHM), this is the easiest way to focus. Point at a bright star, take short pictures over and over, and turn the knob in whichever direction makes the number go down. When the number starts going back up, you went too far, so turn back about half as much.
