defmodule Controller.Stack.Terms do
  @moduledoc """
  Every correction on the Control Stack in plain words: what it is, why it
  matters at the eyepiece, where the number comes from, and what a person can
  do about it. The Stack page links each row to its term; the term page shows
  the live value beside these words. A pro reads the row; anyone can tap in.
  """

  @terms %{
    "hold" => %{
      name: "Tracking the target",
      what: "A loop that checks every 20 seconds where the target should be and where the mount is, and moves the difference. It is what keeps something centered on a mount that isn't polar-aligned.",
      source: "The model's prediction for the target now, against the mount's own encoders.",
      fix: "Nothing to do. Nudge the view with the touchpad or D-pad and it tracks wherever you leave it."
    },
    "parallax" => %{
      name: "The Moon's shift from where you stand",
      what: "The Moon is close enough that where you stand on Earth moves where it appears in the sky, by up to a degree. Planets and stars are far enough that it is under an arcsecond.",
      source: "The Moon's distance and your site, computed for this second.",
      fix: "Nothing to do: it is applied. Without it the Moon was 45′ off on the first night."
    },
    "precession" => %{
      name: "Star positions, year 2000 to today",
      what: "The Earth's axis wobbles slowly, so star coordinates drift about 1′ a year. Star catalogs, plate solves and the mount model all use the year-2000 frame, so everything stays in that one frame.",
      source: "Built into the frame: nothing is converted per target, so nothing can disagree.",
      fix: "Nothing to do."
    },
    "refraction" => %{
      name: "Air bending starlight",
      what: "The atmosphere bends light like a lens, lifting everything a little: about half a degree at the horizon, about 1′ at 45° up, nothing overhead.",
      source: "The target's height above the horizon.",
      fix: "Not applied yet. It matters for Go To low in the sky and for photos, not for looking."
    },
    "cone" => %{
      name: "Tube not square to its axis",
      what: "If the telescope tube isn't exactly perpendicular to the Dec axis, every pointing is off by a little that changes with where it points. Called cone error.",
      source: "Not measured yet. It hides inside the alignment's leftover error.",
      fix: "Shimming the tube rings fixes it; the model can learn it once it has more alignment points."
    },
    "square" => %{
      name: "Axes not square to each other",
      what: "The mount's two axes are meant to cross at exactly 90°. A little off, and pointing errors grow toward the pole.",
      source: "Not measured yet; inside the alignment's leftover error.",
      fix: "A mount property: the model can learn it from more points spread across the sky."
    },
    "flexure" => %{
      name: "The tube sagging",
      what: "A long tube bends slightly under its own weight, differently depending on where it points.",
      source: "Not measured yet.",
      fix: "Stiffer mounting; the model can learn a small term from many points."
    },
    "backlash" => %{
      name: "Slack in the gears",
      what: "When a motor reverses, it turns a little before the gears catch. A small nudge the other way can seem to do nothing.",
      source: "Not measured yet. The position journal (#91) will measure it at every reversal.",
      fix: "Finish centering with moves in one direction; the software will compensate once it is measured."
    },
    "pe" => %{
      name: "Wobble in the drive gear",
      what: "The worm gear isn't perfectly round, so tracking speeds up and slows down in a cycle of a few minutes. Invisible when looking, it smears long photos.",
      source: "Not measured yet. The journal (#91) will measure it.",
      fix: "Guiding, or periodic error correction once it is measured."
    },
    "polar" => %{
      name: "Where the mount's axis points",
      what: "An equatorial mount tracks with one motor only if its main axis points at the celestial pole. This one points somewhere else; the fit found where, and every Go To and tracking correct for it.",
      source: "Fitted from alignment points: photos that were plate-solved, and objects centered by eye.",
      fix: "Nothing needed for looking. For photos, turn the altitude and azimuth bolts toward the pole; Align by Phone Photo says how much."
    },
    "tripod" => %{
      name: "Tripod tilt",
      what: "A tripod that isn't level tilts the whole mount, two ways: north–south and east–west. From the sky alone that looks exactly like mis-set bolts, so it hides inside the axis error above.",
      source: "Unknown until a level reading of the mount head splits it from the bolts.",
      fix: "Put a level app on the mount head, front to back and side to side, and enter what it reads."
    },
    "zeros" => %{
      name: "Where the axes started counting",
      what: "The motors count steps from wherever they were switched on. The fit worked out which way that start position faced, so the counts mean a direction in the sky without ever setting home.",
      source: "Fitted with the axis, from the same alignment points.",
      fix: "Nothing to do. A power cut loses the counts; the position journal (#91) will restore them."
    },
    "signs" => %{
      name: "Which way each motor turns",
      what: "A positive step on each axis turns the tube one way or the other depending on the mount. Getting it backwards sends every Go To the wrong way.",
      source: "Checked against plate-solved photos taken either side of a known move.",
      fix: "Nothing to do."
    },
    "points" => %{
      name: "What the alignment rests on",
      what: "Each alignment point is a moment when the software knew exactly where the tube pointed: a plate-solved photo, or an object you centered. The spread between them is the margin of error.",
      source: "Photos and centerings from tonight.",
      fix: "Center a few more objects in different parts of the sky and the margin shrinks."
    },
    "perfect" => %{
      name: "If the mount were perfect",
      what: "The simple way telescopes point: assume the mount is level, polar-aligned and home was set upright, and compute directly. Fine on a carefully set-up mount.",
      source: "Nothing to measure: it is an assumption.",
      fix: "Not used on this set-up; it would miss by degrees."
    },
    "view" => %{
      name: "Which way is which in the eyepiece",
      what: "Mirrors and the way the eyepiece is turned decide which motor moves the view up, down, left or right. The touchpad and the D-pad use this map, so up means up in what you see.",
      source: "Learned at the eyepiece on the first night; one tap on Backwards or Swapped on the Center page fixes it for a new set-up.",
      fix: "If up moves the view sideways or down, fix it on the Center page."
    },
    "field" => %{
      name: "How much sky the eyepiece shows",
      what: "The width of the circle you see, in arcminutes (60 to a degree). The margin of error only means something next to it.",
      source: "Measured from plate-solved photos through this eyepiece.",
      fix: "A different eyepiece has a different field; it will be one setting."
    },
    "ra" => %{
      name: "The tracking axis",
      what: "Right ascension: the axis that turns with the sky. Tracking runs this motor at the sky's speed, 1×.",
      source: "The mount's own report, four times a second.",
      fix: ""
    },
    "dec" => %{
      name: "The other axis",
      what: "Declination: the axis that moves the tube toward or away from the pole. On a polar-aligned mount it stays still while tracking; on this one tracking nudges it now and then.",
      source: "The mount's own report, four times a second.",
      fix: ""
    }
  }

  def get(key), do: Map.get(@terms, key)
  def keys, do: Map.keys(@terms)
end
