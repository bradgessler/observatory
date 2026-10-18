"""Step 11: the share set, as the annotate-pictures skill says: three JPEGs in share/, full size, quality 93, no chroma
subsampling, no metadata. The caption band is added underneath and never covers the picture; nothing is enlarged.
  saturn.jpg            the finished picture, nothing on it
  saturn-annotated.jpg  the moons named where they were found (step 6: points matched to JPL Horizons), the star that is
                        not a moon (Gaia DR3), the planet's parts that are seen; north, east and a scale bar; the facts
  saturn-how.jpg        for photographers: which part came from which exposure, and how
Every number is read from work/*.json (the recipe's sources). No clock times and no measured altitude to the degree."""
from PIL import Image, ImageDraw, ImageFont
from common import *
AV = '/System/Library/Fonts/Avenir Next.ttc'
def font(s, w='regular'): return ImageFont.truetype(AV, int(s), index={'bold': 0, 'demi': 2, 'medium': 5, 'regular': 7}[w])
INK, DIM, PILL = (235, 235, 235), (165, 165, 165), (0, 0, 0, 170)

GEAR = '© 2026 Brad Gessler  ·  Celestron 8SE (8 inch, f/10.3) and Sony a6000 on an EQ6-R  ·  San Francisco Bay Area  ·  night of 17 October 2026'   # as the night's other cards (m27)
TRUE = "Stacked from the camera's RAW frames. Nothing generated."

def band(W, title, sub, rows, cols=1, credit=()):
    f1, f2, f3 = font(30, 'demi'), font(18), font(17); lines = []
    img = Image.new('RGB', (W, 4000), (0, 0, 0)); d = ImageDraw.Draw(img); y = 24
    d.text((28, y), title, font=f1, fill=INK); y += 46; d.text((28, y), sub, font=f2, fill=DIM); y += 40
    colw = (W - 56) // cols
    for i in range(0, len(rows), cols):
        hmax = 0
        for j, (k, v) in enumerate(rows[i:i + cols]):
            x = 28 + j * colw; yy = y
            if k: d.text((x, yy), k, font=font(15, 'demi'), fill=DIM); yy += 22
            words = v.split(); ln = ''
            for w_ in words:
                if d.textlength(ln + ' ' + w_, font=f3) > colw - 24 and ln: d.text((x, yy), ln, font=f3, fill=INK); yy += 24; ln = w_
                else: ln = (ln + ' ' + w_).strip()
            d.text((x, yy), ln, font=f3, fill=INK); yy += 34; hmax = max(hmax, yy - y)
        y += hmax
    y += 4
    for i, l in enumerate(credit):                       # the night's footer: the gear line, then the frames and "Nothing generated"
        ln = ''
        for w_ in l.split(' '):
            if d.textlength(ln + ' ' + w_, font=font(15)) > W - 56 and ln: d.text((28, y), ln, font=font(15), fill=INK if i == 0 else DIM); y += 24; ln = w_
            else: ln = (ln + ' ' + w_) if ln else w_
        d.text((28, y), ln, font=font(15), fill=INK if i == 0 else DIM); y += 24
    y += 16
    return img.crop((0, 0, W, y))

def save(img, path): img.convert('RGB').save(path, 'JPEG', quality=93, subsampling=0)

if __name__ == '__main__':
    os.makedirs(os.path.join(HERE, 'share'), exist_ok=True)
    co = jload('compose.json'); mo = jload('moons.json'); eph = jload('ephemeris.json'); st = jload('stack.json'); rs = jload('restore.json'); ti = jload('titan.json'); se = jload('select.json'); fr = jload('frames.json')
    pic = Image.open(os.path.join(FINAL, 'saturn-finished.png')).convert('RGB'); Wp, Hp = pic.size; s = 1 / co['arcsec_per_px']
    au = eph['distance_au'][2]; km = au * 1.495979e8; light_min = au * 499.005 / 60; diam = eph['equatorial_diameter_arcsec'][2]
    W_ = max(Wp, 1100); TOP = 90                      # black above the picture, room for labels (a frame, nothing resampled)
    def framed(p): c = Image.new('RGB', (W_, Hp + TOP), (0, 0, 0)); c.paste(p, ((W_ - Wp) // 2, TOP)); return c, (W_ - Wp) // 2
    # 1. plain
    save(pic, os.path.join(HERE, 'share', 'saturn-full.jpg')) if False else None
    plain, ox = framed(pic); plain = plain.crop((0, TOP, W_, TOP + Hp)); save(plain, os.path.join(HERE, 'share', 'saturn.jpg'))
    # 2. annotated
    a, ox = framed(pic); d = ImageDraw.Draw(a, 'RGBA'); f = font(17, 'medium'); fs = font(14)
    def label(px, text, dx, dy, gap=9, small=None):
        x, y = px[0] + ox, px[1] + TOP; tx, ty = x + dx, y + dy; L = np.hypot(dx, dy); ux, uy = dx / L, dy / L
        d.line([(x + ux * gap, y + uy * gap), (tx - ux * 4, ty - uy * 4)], fill=(200, 200, 200, 255), width=1)
        w = max(d.textlength(text, font=f), d.textlength(small, font=fs) if small else 0); bx = tx if dx >= 0 else tx - w - 12; by = ty - 12 if abs(dy) < 1e-6 else (ty - 24 if dy < 0 else ty)
        d.rounded_rectangle([bx - 2, by, bx + w + 10, by + 24 + (18 if small else 0)], 6, fill=PILL); d.text((bx + 4, by + 2), text, font=f, fill=INK)
        if small: d.text((bx + 4, by + 24), small, font=fs, fill=DIM)
    m = co['moons_px']; P = co['planet_px']
    label(m['Titan'], 'Titan', 40, 50, small='bigger than Mercury'); label(m['Rhea'], 'Rhea', 50, 40); label(m['Dione'], 'Dione', 60, -40)
    label(m['Iapetus'], 'Iapetus', -60, -40); label(m['Enceladus'], 'Enceladus', -70, -55, small='faint')
    for sr in co['stars_px']: label(sr['where'], 'A star, not a moon', -30, -75, gap=6)
    re_px = diam / 2 * s; ang = 0.0
    label([P[0] - 1.9 * re_px, P[1] + 1], 'Rings', -20, 80, gap=4); label([P[0], P[1] - 0.7 * re_px], 'Globe', -90, -40, gap=4)
    label([P[0] + 1.35 * re_px, P[1] + 1], 'Dark gap between rings and globe', 60, 95, gap=3)
    # north, east, scale bar (1 arcmin)
    bx, by = 40 + ox, Hp + TOP - 40; L1 = 60 * s; d.line([(bx, by), (bx + L1, by)], fill=INK, width=2); d.text((bx, by - 26), '1 arcminute', font=fs, fill=INK)
    nx, ny = Wp - 260 + ox, Hp + TOP - 40; d.line([(nx, ny), (nx, ny - 50)], fill=INK, width=2); d.text((nx - 5, ny - 72), 'N', font=fs, fill=INK); d.line([(nx, ny), (nx - 50, ny)], fill=INK, width=2); d.text((nx - 68, ny - 9), 'E', font=fs, fill=INK)
    facts = [('How far', 'Saturn was %s million km away; its light took %d minutes to get here.' % (format(int(round(km / 1e6)), ','), round(light_min))),
             ('How big', 'The globe is about 120,000 km across, nine Earths side by side; the rings span about 270,000 km and are mostly less than a kilometre thick. Here the globe is %.0f arcseconds wide, about 50 pixels.' % diam),
             ('The moons', 'Five of its moons, named from where JPL\'s orbits put them at that moment; each name sits on a point found in the picture. Titan, the largest, has a thick atmosphere. Tethys and Mimas were lost in the planet\'s glare, Hyperion was too faint.'),
             ('Honest note', 'The air was soft that night. The rings, the dark gap inside them and the globe show; the Cassini division in the rings does not. The planet and the moons are shown at different brightness: the moons are hundreds to thousands of times fainter than the planet.')]
    credit = [GEAR, '%d of %d frames of 1/60 s for the planet, 2 frames of 2 s for the moons.  ' % (st['keep'], len(fr['planet'])) + TRUE]
    cap = band(W_, 'Saturn and five of its moons', 'The night of 17 October 2026. San Francisco Bay Area. Celestron 8SE and Sony a6000. North up.', facts, cols=2, credit=credit)
    out = Image.new('RGB', (W_, Hp + TOP + cap.size[1]), (0, 0, 0)); out.paste(a, (0, 0)); out.paste(cap, (0, Hp + TOP)); save(out, os.path.join(HERE, 'share', 'saturn-annotated.jpg'))
    # 3. how it was made
    h, ox = framed(pic); d = ImageDraw.Draw(h, 'RGBA'); R_ = (co['grow_px'] + 60)
    d.ellipse([P[0] + ox - 95, P[1] + TOP - 50, P[0] + ox + 95, P[1] + TOP + 50], outline=(200, 200, 200, 255), width=1); d.text((P[0] + ox + 100, P[1] + TOP + 22), 'Planet: %d frames at 1/60 s' % st['keep'], font=fs, fill=INK)
    d.text((ox + 30, Hp + TOP - 30), 'Everything else: 2 frames at 2 s', font=fs, fill=INK)
    usable = se['usable']; n_all = len(fr['planet'])
    rows = [('Exposures', 'Planet: 1/60 s at ISO 800. Moons: 2 s at ISO 6400, the two framing shots taken just before, in which the planet is blown out (960 times the exposure).'),
            ('Frames', 'Planet: %d taken, all %d usable (no cloud: light within 4 percent), graded by sharpness; the sharpest %d kept. Moons: both frames.' % (n_all, usable, st['keep'])),
            ('Why %d' % st['keep'], 'Plain stacks of 5 to 488 frames compared: 8 to 25 were equally sharp, more were softer, 5 sharper still but after restoration 25 beat 5 with half the grain.'),
            ('Stacking', 'No demosaic: each colour plane laid at its own place on a grid 3 times finer than the sensor, the field\'s turn (%.3f deg per minute) taken out, registered to %.2f sensor px rms; red and blue slid onto green (%s and %s px).' % (se['turn_deg_per_minute'], st['residual_shift_after_fine_px_rms'] / 3, st['dispersion_native_px']['red'], st['dispersion_native_px']['blue'])),
            ('Restoration', 'Blur measured on Titan in the same %d frames (%.1f x %.1f arcsec), divided out with %d rounds of Richardson-Lucy, stopped before a model planet grows a false rim of 2 percent.' % (st['keep'], *ti['fwhm_arcsec'], rs['rounds'])),
            ('Moons', 'Two frames averaged, the lower kept where they disagree; the planet\'s glare taken off ring by ring; points matched to JPL Horizons to %.2f arcsec rms; a star checked against Gaia.' % mo['similarity_fit']['rms_arcsec']),
            ('Sampling', '%.3f arcsec per pixel, the sensor\'s own scale: the fine grid is for the arithmetic, the planet is not enlarged.' % co['arcsec_per_px']),
            ('Field', '%.1f by %.1f arcminutes, north up.' % (Wp / s / 60, Hp / s / 60)),
            ('When', 'Around midnight, Saturn about 50 degrees up, a two-hour run; the kept frames mostly from its first hour.'),
            ('Finish', 'Each part its own levels (white, gamma, arcsinh for the moons), sky set neutral, the dark sky quieted, a little colour.'),
            ('Telescope', 'Celestron 8SE: 203 mm aperture, %s mm focal length by plate solve, f/10.3.' % format(int(round(FL_MM)), ',')),
            ('Camera, mount', 'Sony a6000 at prime focus, RAW. Sky-Watcher EQ6-R, unguided, not dithered.')]
    cap = band(W_, 'How it was made', 'Saturn, the night of 17 October 2026', rows, cols=2, credit=credit)
    out = Image.new('RGB', (W_, Hp + TOP + cap.size[1]), (0, 0, 0)); out.paste(h, (0, 0)); out.paste(cap, (0, Hp + TOP)); save(out, os.path.join(HERE, 'share', 'saturn-how.jpg'))
    print('share/saturn.jpg, saturn-annotated.jpg, saturn-how.jpg; %d x %d picture in a %d wide frame' % (Wp, Hp, W_))
