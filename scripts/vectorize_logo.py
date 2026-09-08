# Vettorializza il logo GIGA: maschere -> contorni (marching squares) -> semplificazione -> JSON di poligoni con buchi.
import json, sys, numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

SRC = "C:/Users/simon/Desktop/ade_mail_agent/docs/brand/gigamail-logo-256.png"
OUT = "C:/Users/simon/Desktop/ade_mail_agent/docs/brand/gigamail-logo.shapes.json"
UP = 4  # sovracampionamento per contorni morbidi

im = Image.open(SRC).convert("RGBA")
im = im.resize((im.width * UP, im.height * UP), Image.LANCZOS)
a = np.asarray(im).astype(np.float32)
alpha = a[..., 3] / 255.0
rgb = a[..., :3] / 255.0
lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
sat = rgb.max(-1) - rgb.min(-1)

silhouette = alpha > 0.5
colored = silhouette & ((lum > 0.30) | (sat > 0.45))          # facce blu/rosa, non il navy
colored = ndimage.binary_opening(colored, iterations=2)          # via i pixel misti sul bordo

def marching_squares(mask):
    """Contorni chiusi (liste di (x,y)) al livello 0.5 di una maschera binaria, con bordo di padding."""
    m = np.pad(mask.astype(np.uint8), 1)
    H, W = m.shape
    # segmenti per cella, chiave = punto medio del lato (in coordinate della griglia raddoppiata per restare interi)
    segs = {}
    def mid(y, x, side):  # side: 0 top,1 right,2 bottom,3 left -> punto sul lato (x2,y2 interi)
        return {0: (2*x+1, 2*y), 1: (2*x+2, 2*y+1), 2: (2*x+1, 2*y+2), 3: (2*x, 2*y+1)}[side]
    table = {1:[(3,2)],2:[(2,1)],3:[(3,1)],4:[(0,1)],5:[(3,0),(2,1)],6:[(0,2)],7:[(3,0)],
             8:[(0,3)],9:[(0,2)],10:[(0,1),(2,3)],11:[(0,1)],12:[(1,3)],13:[(1,2)],14:[(2,3)]}
    adj = {}
    for y in range(H-1):
        for x in range(W-1):
            c = m[y,x]*8 + m[y,x+1]*4 + m[y+1,x+1]*2 + m[y+1,x]*1
            if c in (0, 15): continue
            for s0, s1 in table[c]:
                p, q = mid(y,x,s0), mid(y,x,s1)
                adj.setdefault(p, []).append(q); adj.setdefault(q, []).append(p)
    contours, seen = [], set()
    for start in adj:
        if start in seen: continue
        path, cur, prev = [start], start, None
        seen.add(start)
        while True:
            nxt = [n for n in adj[cur] if n != prev and n not in seen]
            if not nxt:
                break
            prev, cur = cur, nxt[0]
            seen.add(cur); path.append(cur)
        if len(path) > 8:
            contours.append([((px - 2) / 2.0, (py - 2) / 2.0) for px, py in path])  # via il padding
    return contours

def rdp(pts, eps):
    if len(pts) < 3: return pts
    P = np.array(pts); a, b = P[0], P[-1]
    ab = b - a; n = np.hypot(*ab) or 1e-9
    d = np.abs(np.cross(ab, P - a)) / n
    i = int(d.argmax())
    if d[i] > eps:
        return rdp(pts[:i+1], eps)[:-1] + rdp(pts[i:], eps)
    return [pts[0], pts[-1]]

def area(pts):
    P = np.array(pts); x, y = P[:,0], P[:,1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))

def inside(pt, poly):
    x, y = pt; n = len(poly); ins = False
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i+1) % n]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if xi > x: ins = not ins
    return ins

def polygons(mask, eps):
    cs = [rdp(c, eps) for c in marching_squares(mask)]
    cs = [c for c in cs if abs(area(c)) > 40]
    outers = [c for c in cs if abs(area(c)) == max(abs(area(d)) for d in cs if inside(c[0], d) or d is c)]
    # classificazione: un contorno e' buco se sta dentro un altro contorno
    result = []
    holes = []
    for c in cs:
        parents = [d for d in cs if d is not c and inside(c[0], d)]
        if len(parents) % 2 == 1: holes.append((c, min(parents, key=lambda d: abs(area(d)))))
        else: result.append({"outer": c, "holes": []})
    for h, parent in holes:
        for r in result:
            if r["outer"] is parent: r["holes"].append(h)
    return result

H = im.height
def norm(poly):  # pixel (y giu') -> unita' con altezza logo = 1, y su, origine in basso a sinistra del canvas
    return [[round(x / H, 4), round((H - y) / H, 4)] for x, y in poly]

sil = polygons(silhouette, eps=1.6)
fac = polygons(colored, eps=1.6)
# ordina le facce da sinistra a destra
fac.sort(key=lambda r: min(p[0] for p in r["outer"]))
data = {"height": 1.0, "aspect": im.width / H,
        "outline": [{"outer": norm(r["outer"]), "holes": [norm(h) for h in r["holes"]]} for r in sil],
        "faces":   [{"outer": norm(r["outer"]), "holes": [norm(h) for h in r["holes"]]} for r in fac]}
json.dump(data, open(OUT, "w"), separators=(",", ":"))
print("outline parts", [(len(r["outer"]), len(r["holes"])) for r in sil])
print("face parts", [(len(r["outer"]), len(r["holes"])) for r in fac])

# anteprima
prev = Image.new("RGB", im.size, (240, 240, 235)); d = ImageDraw.Draw(prev)
for r in sil:
    d.polygon([tuple(p) for p in r["outer"]], fill=(23, 35, 63))
    for h in r["holes"]: d.polygon([tuple(p) for p in h], fill=(240, 240, 235))
for r in fac:
    d.polygon([tuple(p) for p in r["outer"]], fill=(120, 150, 240))
    for h in r["holes"]: d.polygon([tuple(p) for p in h], fill=(23, 35, 63))
prev.save(sys.argv[1] if len(sys.argv) > 1 else "preview.png")
