---
title: "Finding the Moon with a crooked telescope, a phone, and an AI"
date: 2026-09-25
summary: "I set my telescope up badly on purpose: not level, not pointed at the pole, never calibrated. Then I held my phone to the eyepiece, and an AI on my Mac worked out from the photos exactly how crooked it was, pointed it at the Moon, and held it there. Here's how we reasoned through each problem, including the one where we were aiming at the wrong Moon."
hero: "images/plates-moon-centered.jpg"
hero_alt: "The full Moon centred in the eyepiece, held there by a mount 5° off the pole"
---

<aside>

**The short version**

- A telescope normally has to be set up carefully before it can find anything. I skipped all of it.
- I took photos through the eyepiece with my phone. Software matched the stars in them to a catalogue, which says exactly where the telescope was pointing.
- From two photos it worked out how crooked the mount was, then sent it to the Moon and held it there.
- The numbers didn't quite add up, and chasing why showed it had been aiming at the Moon as seen from the centre of the Earth, not from my yard.

</aside>

## The setup: a telescope set up badly on purpose

A telescope mount like mine (an EQ6-R) is built to turn around one axis that points at the celestial pole, the spot near Polaris that the whole sky seems to spin around. Point that axis at the pole and following a star is one motor turning slowly. Get it wrong and every Go To misses and everything drifts out of view.

So normally you level the tripod, aim the axis at Polaris, and tell the mount where it's starting from. I did none of that. Polaris is behind my house, I didn't level the tripod, and I never told the mount where it started. I had a full Moon washing out the sky, the mount pointed roughly north, and my phone.

The question: can somebody who knows nothing plop this thing down and have the software work out how crooked it is?

## The plan: let photos tell the software where it's pointing

![The whole night in one loop: photograph, clean, solve, fit, go, hold](images/moon-loop.svg "The whole night in one loop: photograph, clean, solve, fit, Go To, hold.")

Every photo of the stars is a fingerprint of where the telescope is pointing. If software can read that fingerprint, it doesn't matter how crooked the mount is: the photos say where it really points, and the software works out the rest.

## How I worked: me at the eyepiece, Claude at the keyboard

I stood at the scope with a phone and a game pad and talked. [Claude Code](https://claude.com/claude-code) ran on my Mac with this project open. It read the photos I sent it, wrote the code, ran the tools, and did the math. When I said "down five percent, left twenty", it turned that into motor moves.

What made it work was the way we checked each step. Every idea came with a number that would prove it wrong. That's how we caught the biggest mistake of the night.

## Step 1: I photographed the stars through the eyepiece

There's no camera on the scope. I held my iPhone up to the eyepiece, took a picture, swung the scope somewhere else with the game pad, and took another. Fifteen in all.

![All fifteen photos, marked by whether they solved](images/plates-contact-sheet.jpg "Fifteen phone photos through the eyepiece. Ten of them solved.")

A photo through an eyepiece is a mess: a bright round window in a black frame, stars smeared into little comets by my hand, and moonlight everywhere.

![The best raw photo: the eyepiece's disc, about sixty stars, and moonlit sky](images/plates-raw-four.jpg "The best of the fifteen: a bright disc, about sixty stars, and moonlight.")

## Step 2: we cleaned each photo down to just the stars

The software that reads star fingerprints wants points of light on black. So the first job is to throw away everything that isn't a star inside the eyepiece:

1. **Make it grey.** Colour doesn't help.
2. **Find the eyepiece.** Blur hard and keep the bright part. That's the round window.
3. **Keep only the biggest bright region.** The Moon's glare can show up as a second blob.
4. **Take away the moonlight.** Moonlight is a smooth glow and stars are points, so subtracting a blurred copy of the photo leaves just the stars.
5. **Crop to the window.**

![Plate fifteen through the pipeline: the glare blob in the first mask, gone in the second](images/plates-cleaning-fifteen.jpg "Cleaning a photo: the Moon's glare (top right) survives the first pass. Keeping only the biggest bright region drops it.")

Step 3 came from a failure: on plate fifteen the glare got in, and the photo wouldn't solve. The fix is short:

```elixir
# The eyepiece is the biggest bright region in the photo. Glare from the
# Moon flaring off the eyepiece's edge is a second, smaller one: keep only
# the biggest, and crop to it.
defp eyepiece(mask, dir, opts, deadline) do
  # ask ImageMagick for every bright region, with its size and position
  listing = ["-define", "connected-components:verbose=true", "-connected-components", "8", "null:"]

  with {:ok, out} <- step(:magick, [mask | listing], dir, opts, deadline) do
    case eyepiece_disc(out) do
      # nothing big enough to be an eyepiece: use the photo as it is
      nil ->
        {:ok, nil}

      # repaint the mask with that one region, and crop to its box later
      disc ->
        keep = ["-define", "connected-components:keep-ids=#{disc.id}", "-define", "connected-components:mean-color=true", "-connected-components", "8", "-threshold", "50%", mask]
        with {:ok, _} <- step(:magick, [mask | keep], dir, opts, deadline), do: {:ok, disc}
    end
  end
end
```

## Step 3: a plate solver told us where each photo points

A plate solver is software that recognises a patch of sky the way you'd recognise a constellation: by the shape the stars make. It compares the pattern in a photo against millions of patterns from a star catalogue. When it finds a match, it knows exactly where the photo was pointing, to a fraction of a degree.

We used [astrometry.net](https://astrometry.net). Its catalogue files for this kind of view are 348 MB, small enough to put on a Raspberry Pi.

![Plate four solved: 166 stars found, 52 matched to the catalogue](images/plates-solved-four.jpg "Plate four, solved: 166 stars found, 52 of them matched to the catalogue.")

Ten of the fifteen solved. The five that didn't:

- one was blurry;
- one had the phone tilted, so the window was an oval;
- two were drowned in moonlight;
- one only ever matched the wrong patch of sky.

## Step 4: we learned not to trust every match

The solver gives every match a score: how sure it is that the stars really line up. At its default setting it accepted two wrong answers, each based on just three stars. One put the photo below my horizon, which is impossible.

![Solver scores: the false matches far below the real ones](images/moon-solver-odds.svg "Wrong answers scored around 10⁹. Right ones scored 10²⁸ and up. We put the bar at 10¹⁸.")

The gap between wrong and right was huge, so the fix was to raise the bar and write down why:

```elixir
# How sure a match must be before we believe it. The solver's own default
# (10^9) let through two false matches on the first night, each on three
# stars. Every real match scored 10^28 or better.
@min_odds 1.0e18
```

It cut the other way once too. We threw out plate three on the night because the solver's log printed a low score. That log line is its first, rough check. The final score was 10⁴⁰, on twelve stars. Lesson: read the right number.

## Step 5: two photos measured how crooked the mount is

The software describes the mount with four numbers: where its axis points (up-down and left-right), and where each motor was when it was switched on. Photos of known stars pin those numbers down.

![The mount's axis points 5.3° from the pole](images/moon-crooked-axis.svg "The mount's axis pointed 5.3° from the pole. The software measured that instead of me fixing it.")

Two things made this harder than it sounds.

**The mount never told us where it started.** The motors count from wherever they were when the power came on, so those two numbers could be anything. The fitting method we use gets lost if it starts from a bad guess, so it now tries a grid of starting points first:

```elixir
# The motors count from wherever they were at power-on, so their offsets
# could be anything. Try every pair 10° apart, keep the one that best fits
# the photos, and refine from there.
defp sweep_offsets(samples, signs, start) do
  for(ra <- 0..350//10, dec <- -180..170//10, do: %{start | off_ra: ra / 1, off_dec: dec / 1})
  |> Enum.min_by(fn p -> Enum.reduce(samples, 0.0, &(&2 + residual_deg(p, signs, &1))) end)
end
```

**One photo isn't enough.** A single photo fits the mount equally well two different ways. The first Go To on a one-photo fit pointed the telescope into my garage. The rule now: only small moves until two photos agree. With two, the first Go To landed right beside the Moon.

![After the two-plate GoTo: the Moon just off the edge of the field, lighting it up](images/plates-moon-glare.jpg "With two photos, the first Go To landed just beside the Moon. That's its glare.")

The answer: **the mount's axis was 5.3° from the pole**, 3.1° too low and 5.3° too far west. That's a badly set-up mount, and it didn't matter.

## Step 6: small nudges centred the Moon, and a loop held it there

From there it was me at the eyepiece saying things like "down five percent, left twenty", and Claude sending the nudges. It took two wrong guesses to learn which motor moves the view which way.

![The Moon, centred and held](images/plates-moon-centered.jpg "The Moon centred, and held there for as long as I watched.")

A well set-up mount follows the Moon with one motor. A crooked one has to correct both, all the time. So a loop ran every 20 seconds: work out where the motors should be for the Moon now, compare with where they were when it was centred, and move the difference.

Over 17 minutes it made 8 small corrections on one axis and 27 on the other, each well under two arcminutes (an arcminute is a sixtieth of a degree). The Moon stayed put. The mount's own tracking alone would have walked it out of view in about half an hour.

## The surprise: the software was aiming at the wrong Moon

The photos and the Moon should all have agreed about the mount to within a few arcminutes. They were 23′ apart, and the Moon was the odd one out. That number is what gave it away.

![From Earth's centre and from my yard, the Moon lands in different places against the stars](images/moon-parallax.svg "The software aimed at the Moon as seen from the centre of the Earth. From my yard it sits about 45′ away: more than the eyepiece shows.")

Two things were off, and both were in how the software worked out where the Moon is:

| What | How far off | Why |
|---|---|---|
| Parallax | about 45′ | The Moon is close enough that where you stand on Earth moves it against the stars. The software used the centre of the Earth. |
| The calendar | about 22′ | Star positions drift slowly over the years. The Moon was worked out for today, the stars for the year 2000. |
| **Together** | **44.6′** | They partly cancel. |

That's more than half of what the eyepiece shows. With the Moon put where I actually see it, in the same year-2000 frame as the stars, the same measurements agree to **6.6′ instead of 23.4′**.

The fix is to subtract where I'm standing from where the Moon is:

```elixir
# Where the Moon is from my yard, not from the centre of the Earth.
# `p` is the Moon's position from the Earth's centre, with its distance.
def topocentric(%{distance_km: dist} = p, dt, %{lat: lat, lon: lon} = site) do
  phi = lat * @deg
  h = Map.get(site, :elevation_m, 0) / 1000 / @earth_radius_km

  # where I am, relative to the Earth's centre, in Earth radii
  # (the Earth is slightly flattened, so latitude needs a correction)
  u = :math.atan(0.99664719 * :math.tan(phi))
  rho_sin = 0.99664719 * :math.sin(u) + h * :math.sin(phi)
  rho_cos = :math.cos(u) + h * :math.cos(phi)
  lst = Astro.lst_deg(dt, lon) * @deg

  # the Moon as a point in space, minus me: the Moon as I see it
  {x, y, z} = vec(p.ra_deg, p.dec_deg, dist / @earth_radius_km)
  {x, y, z} = {x - rho_cos * :math.cos(lst), y - rho_cos * :math.sin(lst), z - rho_sin}
  ...
end
```

Checked against NASA's [JPL Horizons](https://ssd.jpl.nasa.gov/horizons/) on three dates, the Moon is now within 1.4′ of where it should be. The old code was 45′ out.

## Everything the software corrects for, in one table

Including the things that don't matter yet, so it's clear what's handled and what isn't:

| What | Size on the first night | Handled? |
|---|---|---|
| Moon parallax | about 45′ | Yes, since this night |
| Year-2000 star positions | about 22′ | Yes, since this night |
| Air bending starlight | about 1′ | Not yet |
| Mount axis, up-down | 3.1° | Yes, measured from photos |
| Mount axis, left-right | 5.3° | Yes, measured from photos |
| Tripod not level | hidden in the two above | Needs a level reading |
| Where each motor started | anything | Yes, measured from photos |
| Tube not square, flex, gear slack | inside the 6.6′ left over | Not yet |
| Photo timestamps | ±45 s, up to 11′ | Guessed: the phone's times were lost |
| Centring by eye | about 1% of the view | That's me |
| Tracking, both axes | under 2′ | Yes |

The tripod row is the interesting one. From the sky alone, a tripod that isn't level and an axis that's aimed wrong look exactly the same, because the stars only see where the axis ends up. A level reading on the mount would split them, and turn "5.3° west" into "this much is the tripod, turn this bolt that much."

## What went wrong

- **The wrong Moon.** Worked out from the centre of the Earth and in the wrong year's frame, 44.6′ out. Fixed and checked against JPL Horizons.
- **One photo sent the scope into the garage.** One photo can't tell which of two ways the mount is sitting. Now: small moves until two agree.
- **The solver accepted wrong answers.** Once it put the photo below the horizon. The bar is 10¹⁸ now.
- **We threw out a right answer.** We read the solver's rough first score instead of its final one.
- **Moonlight got into the eyepiece mask.** Now only the biggest bright region is kept.
- **The photo times were lost.** Sending the photos stripped their timestamps, so each was guessed to within 45 seconds. At the speed the sky turns, that's up to 11′.
- **"Up" meant three things.** Up in the eyepiece, up in a photo, and up on a motor are all different.

## What working with an AI on this was like

- **It's fast at the parts that are slow for me:** geometry, fitting, catalogue math, and writing and running the code, while I stayed at the eyepiece.
- **The numbers caught its mistakes.** Nobody spotted the wrong Moon by looking. Three measurements that should have agreed didn't, and we asked why.
- **It needs thresholds, like any software.** Left alone it would have believed a match below the horizon. We set the bar from the data.
- **The physical world needs precise words.** "Down five percent" only worked once we agreed what "down" meant.
- **I kept the safety calls.** The garage Go To is why big moves wait for two photos.

## What's next

- **A record of where the mount was, all the time,** so a photo's timestamp says exactly where the scope was pointing.
- **A tilt reading from the phone,** to split tripod from axis.
- **Tracking and plate solving on the box itself,** so none of this needs my Mac. Both are done now: see [the Moon we couldn't go to](2026-09-26-the-moon-we-couldnt-go-to.html).
- **Steering by what I see,** not by motor names. Done: see [up is up](2026-09-26-up-is-up-steering-by-the-eyepiece.html).
