---
title: "Finding the Moon with a crooked telescope, a phone, and an AI"
date: 2026-09-25
summary: "I set up my telescope badly on purpose, took pictures through the eyepiece with my phone, and had an AI figure out where it was pointing. It found the Moon. It also turned out to be aiming at the wrong one."
hero: "images/plates-moon-centered.jpg"
hero_alt: "The full Moon centered in the eyepiece, held there by a mount 5° off the pole"
---

If you've ever set up a telescope with a motorized mount, you know the drill. Level the tripod, point the mount at the North Star, center a few bright stars so it knows where it is, and only then can you start looking at stuff. It takes a while and it's easy to mess up.

I wanted to see what would happen if I skipped all of that. I plopped my EQ6-R mount down in the backyard, didn't level it, didn't point it at the North Star (it's behind my house anyway), and never told it where it was starting from. The full Moon was out, washing out most of the sky. I had my phone.

The question I wanted to answer: could the software figure out how crooked the mount was on its own?

## Photos of the sky can tell you where the telescope is pointing

![Take a photo, clean it up, match it on a star map, measure how crooked the mount is, go to the Moon, keep it there](images/moon-loop.svg "How the night went: take a photo, clean it up, match the stars, figure out how crooked the mount is, go to the Moon, and keep it there.")

Every photo of the stars is kind of like a fingerprint. The pattern of stars in it tells you exactly what patch of sky you're looking at. If software can read that, it doesn't matter how badly the mount is set up, because the photos tell you where it's really pointing.

I stood out at the telescope with my phone and a game controller. [Claude Code](https://claude.com/claude-code) was running on my Mac Studio inside with this project open. I'd take a picture and send it over, and Claude would process it, do the math, and move the mount. I didn't touch a keyboard all night.

## I held my phone up to the eyepiece

There's no camera on the telescope yet, so I held my iPhone up to the eyepiece, snapped a picture, moved the telescope somewhere else with the controller, and did it again. I took fifteen.

![All fifteen photos, marked by whether they solved](images/plates-contact-sheet.jpg "All fifteen photos from the night. Ten of them could be matched to a spot in the sky.")

They're pretty rough. You get a bright circle of sky in the middle of a black frame, stars smeared into little comets because I can't hold a phone still, and moonlight everywhere.

![The best raw photo: the eyepiece's disc, about sixty stars, and moonlit sky](images/plates-raw-four.jpg "This was the best one. You can count about sixty stars in there.")

## The photos had to be cleaned up first

The software that matches star patterns wants dots of light on a black background, so Claude had it throw away everything outside the circle and take out the moonlight. That second part is a neat trick. Moonlight is a smooth glow and stars are tiny dots, so if you blur a copy of the photo and subtract it, the glow cancels out and the stars are left.

![Plate fifteen through the pipeline: the glare blob in the first mask, gone in the second](images/plates-cleaning-fifteen.jpg "Cleaning up a photo. Glare from the Moon (top right) got picked up as part of the eyepiece at first, so now it only keeps the biggest bright blob.")

One of the photos had glare from the Moon that showed up as a second bright blob next to the circle, and it threw everything off. The fix was to only keep the biggest bright blob, since that's always the eyepiece.

## A plate solver matches the stars against a map of the sky

This is where it gets fun. A plate solver looks at the pattern of stars in a photo and compares it against millions of patterns from a star catalog, kind of like how you'd recognize the Big Dipper by its shape. When it finds a match, it knows where the photo was pointing down to a tiny fraction of a degree. I used [astrometry.net](https://astrometry.net), which is free, and the catalog files it needs for my eyepiece are small enough to fit on a Raspberry Pi.

![Plate four solved: 166 stars found, 52 matched to the catalog](images/plates-solved-four.jpg "A match. It found 166 stars in this photo and matched 52 of them to the catalog.")

Ten of the fifteen photos matched. The rest were blurry, tilted, or too washed out by the Moon.

## Don't trust every match

Every match comes with a score that says how confident the solver is. With the default settings it accepted a couple of matches that were just wrong, each based on only three stars. One of them said my phone was pointed at a part of the sky that's below my horizon, which obviously wasn't the case.

![Solver scores: the false matches far below the real ones](images/moon-solver-odds.svg "The wrong matches scored way lower than the right ones, so it was easy to set a cutoff between them.")

Luckily the wrong ones scored way lower than the right ones, so we raised the cutoff to sit in between. It went the other way once too: we threw out a good photo because the solver printed a low score in its log, which turned out to be a rough first guess. The final score was fine.

## Two photos were enough to tell how crooked the mount was

With a couple of matched photos, the software can work out which way the mount's main axis is actually pointing and where each motor was when I turned it on.

![The mount's axis points 5.3° from the pole](images/moon-crooked-axis.svg "My mount's axis was pointed 5.3° away from where it should have been. The software measured that so I didn't have to fix it.")

One photo isn't enough. With just one, the math works out equally well for two totally different ways the mount could be sitting. The first time I tried going to the Moon off one photo, the telescope swung around and pointed at my garage. After that the rule was no big moves until two photos agree. With two, it swung right over next to the Moon.

![After the two-plate GoTo: the Moon just off the edge of the field, lighting it up](images/plates-moon-glare.jpg "With two photos, the first try landed right next to the Moon. That glow is the Moon, just out of view.")

It turned out my mount's axis was 5.3° off from where it should have been. That's a pretty badly set up mount, and it didn't matter.

## Then I nudged the Moon into the middle

From there it was me at the eyepiece saying things like "down five percent, left twenty" and Claude moving the mount. It took a couple of wrong guesses to figure out which motor moved the view which way. (That annoyed me enough that we fixed it later that same night. More on that in [Up is up](2026-09-26-up-is-up-steering-by-the-eyepiece.html).)

![The Moon, centered and held](images/plates-moon-centered.jpg "The Moon, dead center.")

Keeping it there is the other half. A properly set up mount follows the Moon with one motor turning slowly. A crooked one has to keep adjusting both motors, so every 20 seconds the software checked where the Moon should be and made a small correction. Over 17 minutes it made 35 of them and the Moon didn't budge.

## The software was aiming at the wrong Moon

This was the most interesting part of the night. The photos and the Moon should have agreed about how the mount was set up, and they didn't. They were off by about a third of a degree, and the Moon was the odd one out.

![From Earth's center and from my yard, the Moon lands in different places against the stars](images/moon-parallax.svg "The Moon is close enough that where you stand changes where it shows up against the stars. The software was working it out from the center of the Earth.")

Hold your thumb out at arm's length and look at it with one eye closed, then switch eyes. It jumps. The Moon does the same thing depending on where you are on Earth, because it's so close. The software was calculating where the Moon is from the center of the Earth instead of from my backyard, and that alone put it about 45 arcminutes off, which is more than the entire view in my eyepiece.

There was a second, smaller problem too. Star maps are pinned to the year 2000 because the stars slowly drift over the decades, and the Moon was being calculated for today. Once Claude fixed both, the photos and the Moon agreed to within about a tenth of a degree. We double checked the new Moon positions against NASA's [JPL Horizons](https://ssd.jpl.nasa.gov/horizons/) on three different dates and they're within about an arcminute and a half.

Nobody noticed this by looking through the eyepiece. It came up because a couple of numbers that should have matched didn't, and we kept asking why.

## What I'd do differently

Don't trust a single photo. That's how the telescope ended up pointed at my garage.

Keep the photos' timestamps. Sending photos from my phone stripped out when they were taken, so we had to guess to within 45 seconds, and the sky turns fast enough that 45 seconds matters.

Figure out which way is up before you start nudging. Up in the eyepiece, up in a photo, and up on the motors are three different things, and I burned a lot of time on that.

## Working with an AI on this

The math on this stuff is not something I could have done at the eyepiece, and probably not at a desk either without a lot of reading. Claude handled the geometry, the star catalogs, and all the code while I stayed outside looking through the telescope.

It also got things wrong. It happily accepted a match that was below my horizon, and it took a couple of tries to get the directions right. What worked was checking everything against something we could measure, and keeping the safety calls with me, the guy standing next to the telescope when it swings toward the garage.

## What's next

The goal is to take my Mac out of the picture. Since this post, the plate solving and the tracking both run on the Raspberry Pi on the telescope. You can read about that, and about the Go To that refused to go to the Moon, in [The Moon we couldn't go to](2026-09-26-the-moon-we-couldnt-go-to.html).
