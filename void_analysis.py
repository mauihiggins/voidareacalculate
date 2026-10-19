"""Pixel-center polygon rasterization and 8-connected bright void detection."""
import numpy as np


def local_contrast(gray, region, radius):
    """Masked grayscale opening: estimate background without bright voids.

    Work in the pad bounding box; outside-pad intensities never participate.
    The square window should be wider than the largest expected void.
    """
    yy, xx = np.nonzero(region)
    box = np.s_[yy.min():yy.max()+1, xx.min():xx.max()+1]
    valid = region[box]
    values = gray[box].astype(np.float32)

    def extreme(a, minimum):
        operation = np.minimum if minimum else np.maximum
        fill = np.inf if minimum else -np.inf
        for axis in (0, 1):
            padding = [(0, 0), (0, 0)]
            padding[axis] = (radius, radius)
            padded = np.pad(a, padding, constant_values=fill)
            result = np.full_like(a, fill)
            for offset in range(2*radius+1):
                selection = [slice(None), slice(None)]
                selection[axis] = slice(offset, offset+a.shape[axis])
                operation(result, padded[tuple(selection)], out=result)
            a = result
        return a

    eroded = extreme(np.where(valid, values, np.inf), True)
    background = extreme(np.where(valid, eroded, -np.inf), False)
    contrast = np.zeros(gray.shape, dtype=np.float32)
    contrast[box] = np.where(valid, np.maximum(values-background, 0), 0)
    return contrast


def analyze(image, polygon, threshold=125, minimum=4, mode='absolute',
            contrast_threshold=8, background_radius=60):
    if mode not in ('absolute', 'local'):
        raise ValueError('지원하지 않는 검출 모드입니다.')
    if not 1 <= background_radius <= 250 or int(background_radius) != background_radius:
        raise ValueError('배경 반경은 1~250의 정수여야 합니다.')
    if not 1 <= contrast_threshold <= 255:
        raise ValueError('국소 밝기 차이는 1~255여야 합니다.')
    if len(polygon) < 3:
        raise ValueError('패드 경계를 3점 이상 지정하세요.')
    gray = np.asarray(image.convert('L'))
    height, width = gray.shape
    # Row-wise rasterization avoids allocating a full coordinate grid.
    region = np.zeros((height, width), dtype=bool)
    xs = np.arange(width) + 0.5
    for row in range(height):
        y = row + 0.5
        for a, b in zip(polygon, polygon[1:] + polygon[:1]):
            if (a[1] > y) != (b[1] > y):
                crossing = (b[0]-a[0]) * (y-a[1]) / (b[1]-a[1]) + a[0]
                region[row] ^= xs < crossing
    area = int(region.sum())
    if not area:
        raise ValueError('패드 영역에 픽셀이 없습니다.')
    score = (local_contrast(gray, region, background_radius)
             if mode == 'local' else gray)
    pending = region & (score >= (contrast_threshold if mode == 'local' else threshold))
    mask = np.zeros_like(region)
    sizes = []
    for y, x in zip(*np.nonzero(pending)):
        if not pending[y, x]:
            continue
        stack = [(int(y), int(x))]
        pending[y, x] = False
        pixels = []
        while stack:
            cy, cx = stack.pop()
            pixels.append((cy, cx))
            for ny in range(max(0, cy-1), min(height, cy+2)):
                for nx in range(max(0, cx-1), min(width, cx+2)):
                    if pending[ny, nx]:
                        pending[ny, nx] = False
                        stack.append((ny, nx))
        if len(pixels) >= minimum:
            yy, xx = zip(*pixels)
            mask[yy, xx] = True
            sizes.append(len(pixels))
    void = sum(sizes)
    return dict(pad_area=area, void_area=void, ratio=100*void/area,
                sizes=sorted(sizes, reverse=True), mask=mask)
