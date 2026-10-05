"""Two pieces of the terminator cut out of the finished pictures at the sensor's own scale (one
picture pixel = one sensor pixel, 0.388 arcsec). Nothing is resampled, drawn or written on them:
each is the same rectangle of the plain PNG and of the restored PNG.
Usage: crops.py <output folder>"""
import sys, os, json, cv2
out = sys.argv[1]
CROPS = {  # name: x, y, width, height on the north-up picture, and what is in it
    "copernicus-eratosthenes": (1250, 1500, 1200, 900, "Copernicus, Montes Carpatus and Eratosthenes at the terminator (9-15 N); clear frames"),
    "tycho-clavius": (1650, 4050, 1200, 900, "Tycho in shadow, Longomontanus, Clavius and its arc of craterlets (43-58 S); frames through thin cloud"),
}
made = {}
for stem, suffix in (("moon-last-quarter", ""), ("moon-last-quarter-restored", "-restored")):
    img = cv2.imread(os.path.join(out, stem + ".png"), cv2.IMREAD_COLOR)
    for name, (x, y, w, h, what) in CROPS.items():
        f = "crop-%s%s.png" % (name, suffix)
        cv2.imwrite(os.path.join(out, f), img[y:y + h, x:x + w], [cv2.IMWRITE_PNG_COMPRESSION, 9])
        made[f] = dict(cut_from=stem + ".png", x=x, y=y, width=w, height=h, shows=what)
json.dump(made, open(os.path.join(out, "crops.json"), "w"), indent=1); print("\n".join(made))
