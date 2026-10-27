"""Отрисовка карты европейской части РФ по состоянию угроз (Pillow, без GIS-зависимостей)."""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from regions import EUROPE_FOS, RegionIndex, short_label
from state import MSK

BG = (231, 238, 244)
WATER = (214, 227, 238)
GREEN = (72, 168, 96)
ORANGE = (248, 158, 34)
RED = (214, 48, 62)
BORDER = (255, 255, 255)
HEADER = (18, 30, 48)
MUTED = (108, 124, 142)

WIDTH = 1500
# рамка карты: отсекаем арктические острова (Новая Земля и т.п.), иначе масштаб «уезжает»
VIEW_LON = (19.0, 87.0)
VIEW_LAT = (41.0, 74.0)
PAD = 40
HEADER_H = 128
LEGEND_H = 120
LINE_H = 30


def _wrap_by_commas(draw, font, atoms: list[str], max_width: int) -> list[str]:
    """Переносит перечисление по запятым: строка не шире max_width.

    atoms — готовые куски вида «БПЛА: Брянская обл.», «Вологодская обл.» и т. д.
    Запятые расставляются по исходному порядку, поэтому текст читается как одна фраза.
    """
    lines: list[str] = []
    cur = ""
    for i, atom in enumerate(atoms):
        piece = atom + ("," if i < len(atoms) - 1 else "")
        cand = f"{cur} {piece}".strip() if cur else piece
        if not cur or draw.textlength(cand, font=font) <= max_width:
            cur = cand
        else:
            lines.append(cur)
            cur = piece
    if cur:
        lines.append(cur)
    return lines

FONT_DIRS = [Path(__file__).parent / "assets" / "fonts",
             Path("C:/Windows/Fonts"), Path("/usr/share/fonts/truetype/dejavu"),
             Path("/usr/share/fonts/truetype/noto"), Path("/System/Library/Fonts")]


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = (["NotoSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf", "seguisb.ttf"]
             if bold else ["NotoSans-Regular.ttf", "arial.ttf", "Arial.ttf", "DejaVuSans.ttf", "segoeui.ttf"])
    for d in FONT_DIRS:
        for n in names:
            p = d / n
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), size)
                except Exception:
                    pass
    return ImageFont.load_default()


def rings(geometry: dict):
    if geometry["type"] == "Polygon":
        yield from geometry["coordinates"]
    elif geometry["type"] == "MultiPolygon":
        for poly in geometry["coordinates"]:
            yield from poly


def ring_centroid(ring: list) -> tuple[float, float]:
    if ring and ring[0] == ring[-1]:
        ring = ring[:-1]
    if len(ring) < 3:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return (sum(xs) / len(xs), sum(ys) / len(ys)) if xs else (0, 0)
    twice_area = cx = cy = 0.0
    for i in range(len(ring)):
        x0, y0 = ring[i][0], ring[i][1]
        x1, y1 = ring[(i + 1) % len(ring)][0], ring[(i + 1) % len(ring)][1]
        cross = x0 * y1 - x1 * y0
        twice_area += cross
        cx += (x0 + x1) * cross
        cy += (y0 + y1) * cross
    if abs(twice_area) < 1e-9:
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        return (sum(xs) / len(xs), sum(ys) / len(ys))
    return (cx / (3 * twice_area), cy / (3 * twice_area))


class MapRenderer:
    def __init__(self, index: RegionIndex, width: int = WIDTH):
        self.index = index
        self.features = [f for f in index.features
                         if f["properties"].get("fo") in EUROPE_FOS]
        lons, lats = [], []
        for f in self.features:
            for ring in rings(f["geometry"]):
                for lon, lat in ring:
                    lons.append(lon)
                    lats.append(lat)
        self.lon_min = max(min(lons), VIEW_LON[0])
        self.lon_max = min(max(lons), VIEW_LON[1])
        self.lat_min = max(min(lats), VIEW_LAT[0])
        self.lat_max = min(max(lats), VIEW_LAT[1])
        self.width = width
        self.k = math.cos(math.radians((self.lat_min + self.lat_max) / 2))
        span_x = (self.lon_max - self.lon_min) * self.k
        span_y = self.lat_max - self.lat_min
        inner_w = width - 2 * PAD
        self.scale = inner_w / span_x
        self.inner_h = span_y * self.scale
        self.height = int(self.inner_h + 2 * PAD + HEADER_H + LEGEND_H)

    def project(self, lon: float, lat: float) -> tuple[float, float]:
        x = PAD + (lon - self.lon_min) * self.k * self.scale
        y = HEADER_H + PAD // 2 + (self.lat_max - lat) * self.scale
        return x, y

    def _summary_lines(self, state, font) -> list[str]:
        """Сводка активных регионов, разложенная по строкам (без обрезки «…»)."""
        rocket = [short_label(n) for n in state.regions if state.status(n) == "rocket"]
        bpla = [short_label(n) for n in state.regions if state.status(n) == "bpla"]
        paragraphs = []
        if rocket:
            paragraphs.append(("Ракетная", rocket))
        if bpla:
            paragraphs.append(("БПЛА", bpla))
        if not paragraphs:
            return ["Активных угроз нет"]

        measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        max_width = self.width - 2 * PAD
        lines: list[str] = []
        for title, names in paragraphs:
            atoms = [f"{title}: {names[0]}"] + names[1:]
            lines.extend(_wrap_by_commas(measure, font, atoms, max_width))
        return lines

    def render(self, state, out_path: Path, title: str = "Воздушная угроза") -> Path:
        f_bold = load_font(22, bold=True)
        summary = self._summary_lines(state, f_bold)
        # высота растёт только снизу: карта и легенда остаются на своих местах
        extra_h = max(0, len(summary) - 1) * LINE_H
        total_h = self.height + extra_h

        img = Image.new("RGB", (self.width, total_h), BG)
        d = ImageDraw.Draw(img)

        d.rectangle([0, 0, self.width, HEADER_H], fill=HEADER)
        f_title = load_font(40, bold=True)
        f_sub = load_font(22)
        d.text((PAD, 28), title, font=f_title, fill=(255, 255, 255))
        stamp = datetime.now(MSK).strftime("%d.%m.%Y %H:%M МСК")
        n_alert = len([r for r in state.regions if state.status(r)])
        tail = f"· под угрозой: {n_alert}" if n_alert else "· угроз нет"
        d.text((PAD + 2, 82), f"Европейская часть России · обновлено {stamp} {tail}", font=f_sub,
               fill=(168, 186, 208))

        # регионы
        for f in self.features:
            name = f["properties"]["name"]
            st = state.status(name)
            color = RED if st == "rocket" else ORANGE if st == "bpla" else GREEN
            for ring in rings(f["geometry"]):
                pts = [self.project(lon, lat) for lon, lat in ring]
                if len(pts) >= 3:
                    d.polygon(pts, fill=color)
        # границы
        for f in self.features:
            for ring in rings(f["geometry"]):
                pts = [self.project(lon, lat) for lon, lat in ring]
                if len(pts) >= 3:
                    d.line(pts + [pts[0]], fill=BORDER, width=2, joint="curve")

        # подписи активных регионов (с разводом от наложений)
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        f_lab = load_font(19, bold=True)
        active = [(n, state.status(n)) for n in state.regions if state.status(n)]
        placed: list[tuple[float, float, float, float]] = []
        offsets = [(0, 0), (0, -26), (0, 26), (-46, 0), (46, 0), (-46, -26), (46, -26),
                   (0, -52), (0, 52), (-46, 26), (46, 26), (0, -78), (0, 78), (-92, 0), (92, 0)]
        for name, st in active:
            feat = next((x for x in self.features if x["properties"]["name"] == name), None)
            if not feat:
                continue
            best = max(rings(feat["geometry"]), key=lambda r: len(r))
            clon, clat = ring_centroid(best)
            ax, ay = self.project(clon, clat)
            label = short_label(name)
            bbox = od.textbbox((0, 0), label, font=f_lab)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            box = None
            for dx, dy in offsets:
                x0 = ax - tw / 2 - 7 + dx
                y0 = ay - th / 2 - 5 + dy
                cand = (x0, y0, x0 + tw + 14, y0 + th + 10)
                if any(not (cand[2] < p[0] or cand[0] > p[2] or cand[3] < p[1] or cand[1] > p[3])
                       for p in placed):
                    continue
                box = cand
                break
            if box is None:
                continue  # подпись не влезла — регион всё равно есть в строке-сводке
            placed.append(box)
            od.rounded_rectangle(list(box), radius=6, fill=(255, 255, 255, 238))
            od.text((box[0] + 7, box[1] + 4 - bbox[1]), label, font=f_lab, fill=(30, 38, 48))
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
        d = ImageDraw.Draw(img)

        # легенда + сводка
        y0 = self.height - LEGEND_H + 14
        d.line([(PAD, y0 - 14), (self.width - PAD, y0 - 14)], fill=(214, 222, 230), width=2)
        f_leg = load_font(22)
        items = [("Без угрозы", GREEN), ("Опасность БПЛА", ORANGE), ("Ракетная опасность", RED)]
        x = PAD
        for label, color in items:
            d.rounded_rectangle([x, y0 + 4, x + 26, y0 + 30], radius=6, fill=color)
            d.text((x + 36, y0 + 4), label, font=f_leg, fill=(52, 64, 80))
            x += 36 + d.textlength(label, font=f_leg) + 34

        for i, line in enumerate(summary):
            d.text((PAD, y0 + 52 + i * LINE_H), line, font=f_bold, fill=(38, 50, 66))

        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(out_path, "PNG", optimize=True)
        return out_path
