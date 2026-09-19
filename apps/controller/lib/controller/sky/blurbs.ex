defmodule Controller.Sky.Blurbs do
  @moduledoc """
  Two or three sentences for the things people actually look at: what it is,
  what you'll see in a small scope, one thing to say out loud. Generic text by
  kind for everything else. This is the deterministic backbone the sky tour
  and the LLM layer talk over (#40, #8).
  """

  @blurbs %{
    "sol-moon" => "Our Moon. In any telescope the terminator — the line between day and night — is where the craters and mountains throw long shadows; that's where to look. It's about 384,000 km away, and the light you're seeing left it 1.3 seconds ago.",
    "sol-jupiter" => "Jupiter, the biggest planet. Even at low power you'll see a bright disk with up to four little dots in a line: the Galilean moons Io, Europa, Ganymede and Callisto, which Galileo spotted in 1610. Steadier air shows the two dark cloud belts.",
    "sol-saturn" => "Saturn. The rings are obvious in any telescope at 30× or more and people gasp every time. The bright dot nearby is Titan, a moon bigger than Mercury. Light takes over an hour to get here from Saturn.",
    "sol-mars" => "Mars. A small orange disk; near opposition you can make out a polar cap and dark markings. Most of the year it's tiny — manage expectations, then mention people have landed robots on it.",
    "sol-venus" => "Venus. Dazzling but featureless: a thick cloud deck. What you can see is its phase, like a little Moon — Galileo used exactly that to argue the planets go around the Sun.",
    "sol-mercury" => "Mercury, the innermost planet, always low and in twilight. A small disk showing a phase. Seeing it at all is the achievement.",
    "m31" => "The Andromeda Galaxy — the farthest thing you can see with your bare eyes, 2.5 million light-years away. In a small scope it's a soft oval glow with a brighter core; the light left it before humans existed. It's on a collision course with us, in about 4 billion years.",
    "m42" => "The Orion Nebula, a cloud of gas where stars are being born right now. Even a small scope shows the glowing fan and the four tight stars of the Trapezium lighting it up. 1,300 light-years away.",
    "m45" => "The Pleiades, the Seven Sisters. A young cluster of hot blue stars; the naked eye sees six or seven, binoculars or the lowest power show dozens. Best at low magnification — it's bigger than the Moon.",
    "m13" => "The Great Hercules Cluster: a few hundred thousand stars packed into a ball 145 light-years across, 25,000 light-years away. Small scopes show a fuzzy snowball; larger ones resolve it into a sparkle of individual stars around the edges.",
    "m57" => "The Ring Nebula — a dying star's cast-off shell, seen face on as a tiny smoke ring. Small and faint but unmistakable at medium power. Our Sun will do this in about five billion years.",
    "m27" => "The Dumbbell Nebula, another dying star's shell, bigger and brighter than the Ring: a soft two-lobed glow. One of the easiest planetary nebulae in a small scope.",
    "m11" => "The Wild Duck Cluster, one of the richest open clusters: a dense wedge of faint stars that looks like a flock in flight. Lovely at medium power.",
    "m22" => "A big, bright globular cluster in Sagittarius, closer than M13 and looser — easy to start resolving into stars in a 4-inch. Toward the centre of our galaxy.",
    "m8" => "The Lagoon Nebula: a glowing cloud with a cluster of young stars embedded in it, visible to the naked eye from a dark site. Low power, wide field.",
    "m17" => "The Swan (or Omega) Nebula: a bright bar of glowing gas with a hook that really does look like a swan's neck at medium power.",
    "m51" => "The Whirlpool Galaxy, a face-on spiral with a small companion galaxy hanging off one arm. In a small scope two fuzzy patches; under dark skies with aperture, the spiral arms.",
    "m81" => "Bode's Galaxy, a bright spiral 12 million light-years away, usually in the same low-power field as the cigar-shaped M82. Two galaxies in one view.",
    "m82" => "The Cigar Galaxy: an edge-on starburst galaxy, a thin streak of light next to M81. Tearing itself up with star formation.",
    "m104" => "The Sombrero Galaxy, an edge-on spiral with a dark dust lane across a bright bulge — the hat brim. Needs a steady, dark sky in a 4-inch.",
    "m44" => "The Beehive Cluster: a swarm of stars visible to the naked eye as a faint smudge, spectacular in binoculars or the lowest power. Ancient observers thought it was a little cloud.",
    "m92" => "A bright globular cluster often overlooked next to M13. Compact and very old — around 14 billion years, nearly as old as the universe.",
    "m15" => "A dense globular cluster with an unusually bright, tight core — one of the most concentrated known. Small scopes show a fuzzy star; aperture starts to resolve the edges.",
    "hip91262" => "Vega, the fifth-brightest star, 25 light-years away, and the star that will be our pole star in about 12,000 years. Brilliant blue-white in the eyepiece; a good first target to line everything up on.",
    "hip95947" => "Albireo, the best double star in the sky for a small telescope: a gold star and a blue star side by side. The colour contrast is the whole show.",
    "hip65378" => "Mizar in the Big Dipper's handle — the first double star ever seen in a telescope (1617). Its naked-eye companion Alcor was an ancient eyesight test.",
    "hip11767" => "Polaris, the North Star. Not especially bright — it matters because it sits almost over the north pole, so the sky turns around it. A small scope shows a faint companion.",
    "hip80763" => "Antares, the red heart of Scorpius: a supergiant so big it would swallow Mars' orbit. Compare its colour with a blue-white star like Vega.",
    "hip27989" => "Betelgeuse, Orion's red shoulder — a dying supergiant that will one day explode as a supernova. Its colour is obvious even to the naked eye."
  }

  @generic %{
    star: "A star. In the eyepiece it stays a point of light no matter the magnification — what changes is its colour and brightness. Look for a hint of colour: blue-white is hot, orange-red is cool.",
    planet: "A planet: a tiny disk rather than a point, which is how you know it isn't a star. Higher power shows more; steady air matters more than aperture.",
    moon: "The Moon.",
    cluster: "A star cluster: a family of stars born together from the same cloud. Open clusters are loose sprinkles best at low power; globular clusters are dense balls that resolve into a sparkle around the edges.",
    galaxy: "A galaxy: hundreds of billions of stars so far away they blur into a soft glow. Averted vision — looking slightly to one side — brings it out. The light left it millions of years ago.",
    nebula: "A nebula: a cloud of gas and dust, glowing where nearby stars light it. Low power and dark-adapted eyes; from a suburb the bright ones are still worth it.",
    planetary: "A planetary nebula — nothing to do with planets: the shell a dying star puffs off. Small, fairly bright, best at medium power. Our Sun's future."
  }

  def for(%{id: id, kind: kind}) do
    @blurbs[id] || @generic[kind] || ""
  end
end
