"""
Genera assets/icona.ico — icona a "grafo" (nodi + archi).
Usa solo la stdlib Python (struct, os): nessuna dipendenza esterna.
"""
import os
import struct

BG    = (250, 246, 240, 255)   # sfondo (BGRA) bianco-crema
EDGE  = (150, 120, 70, 255)    # archi grigio-blu
NODES = [                       # colori nodi (BGRA), tonalità blu/verde
    (168, 114, 76, 255),
    (82, 168, 85, 255),
    (219, 152, 52, 255),
    (198, 78, 196, 255),
    (139, 68, 68, 255),
]

# Posizioni nodi in coordinate frazionarie (x, y) 0..1, y cresce verso il basso
NODE_POS_FRAC = [
    (0.5, 0.12),
    (0.15, 0.45),
    (0.85, 0.45),
    (0.30, 0.88),
    (0.70, 0.88),
]
EDGES = [(0, 1), (0, 2), (1, 3), (2, 4), (1, 2), (3, 4)]


def _draw_line(grid, size, x0, y0, x1, y1, color, width=1):
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        for ox in range(-width // 2, width // 2 + 1):
            for oy in range(-width // 2, width // 2 + 1):
                px, py = x + ox, y + oy
                if 0 <= px < size and 0 <= py < size:
                    grid[py][px] = color
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy


def _draw_circle(grid, size, cx, cy, r, color):
    for py in range(max(0, cy - r), min(size, cy + r + 1)):
        for px in range(max(0, cx - r), min(size, cx + r + 1)):
            if (px - cx) ** 2 + (py - cy) ** 2 <= r * r:
                grid[py][px] = color


def _make_bmp_32bpp(size: int) -> bytes:
    grid = [[BG] * size for _ in range(size)]

    positions = [(int(fx * size), int(fy * size)) for fx, fy in NODE_POS_FRAC]
    edge_width = max(1, size // 24)

    for a, b in EDGES:
        x0, y0 = positions[a]
        x1, y1 = positions[b]
        _draw_line(grid, size, x0, y0, x1, y1, EDGE, width=edge_width)

    node_r = max(3, size // 8)
    for i, (x, y) in enumerate(positions):
        _draw_circle(grid, size, x, y, node_r, NODES[i % len(NODES)])

    pixels = bytearray()
    for r in range(size - 1, -1, -1):
        for c in range(size):
            b, g, ra, a = grid[r][c]
            pixels.extend([b, g, ra, a])
    return bytes(pixels)


def write_ico(path: str, size: int = 48) -> None:
    pixel_data = _make_bmp_32bpp(size)

    row_bytes = (size + 31) // 32 * 4
    mask_data = b'\x00' * (row_bytes * size)

    bih = struct.pack(
        '<IiiHHIIiiII',
        40,
        size,
        size * 2,
        1,
        32,
        0,
        len(pixel_data),
        0, 0, 0, 0,
    )

    image_section = bih + pixel_data + mask_data

    ico_header = struct.pack('<HHH', 0, 1, 1)

    offset = 6 + 16
    ico_dir = struct.pack(
        '<BBBBHHII',
        size,
        size,
        0,
        0,
        1,
        32,
        len(image_section),
        offset,
    )

    with open(path, 'wb') as f:
        f.write(ico_header)
        f.write(ico_dir)
        f.write(image_section)


if __name__ == '__main__':
    here = os.path.dirname(os.path.abspath(__file__))
    ico_path = os.path.join(here, 'icona.ico')
    write_ico(ico_path, size=48)
    print(f"Icona creata: {ico_path}")
