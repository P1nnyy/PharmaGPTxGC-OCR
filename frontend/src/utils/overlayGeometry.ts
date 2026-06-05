export type BBox = [number, number, number, number];

/**
 * Checks if a bounding box uses normalized coordinates (values between 0 and 1).
 */
export function isNormalizedBBox(bbox: BBox): boolean {
  if (!bbox || bbox.length !== 4) return false;
  const [xMin, yMin, xMax, yMax] = bbox;
  return (
    xMin >= 0 && xMin <= 1 &&
    xMax >= 0 && xMax <= 1 &&
    yMin >= 0 && yMin <= 1 &&
    yMax >= 0 && yMax <= 1
  );
}

/**
 * Normalizes input geometry into a standard BBox [x_min, y_min, x_max, y_max] format.
 * Returns null if no valid geometry is found.
 */
export function normalizeBBox(input: any): BBox | null {
  if (!input || typeof input !== 'object') {
    return null;
  }

  const isValidBBoxArray = (arr: any): boolean => {
    return (
      Array.isArray(arr) &&
      arr.length === 4 &&
      arr.every(num => typeof num === 'number' && Number.isFinite(num))
    );
  };

  // 0. If input itself is a valid 4-number bbox array, return it directly.
  if (isValidBBoxArray(input)) {
    return input as BBox;
  }

  if (isValidBBoxArray(input.bbox)) {
    return input.bbox as BBox;
  }

  if (isValidBBoxArray(input.normalized_bbox)) {
    return input.normalized_bbox as BBox;
  }

  if (isValidBBoxArray(input.box)) {
    return input.box as BBox;
  }

  if (input.bounding_box && typeof input.bounding_box === 'object') {
    const { x_min, y_min, x_max, y_max } = input.bounding_box;
    if (
      typeof x_min === 'number' && Number.isFinite(x_min) &&
      typeof y_min === 'number' && Number.isFinite(y_min) &&
      typeof x_max === 'number' && Number.isFinite(x_max) &&
      typeof y_max === 'number' && Number.isFinite(y_max)
    ) {
      return [x_min, y_min, x_max, y_max];
    }
  }

  if (input.geometry && typeof input.geometry === 'object') {
    const { min_x, min_y, max_x, max_y } = input.geometry;
    if (
      typeof min_x === 'number' && Number.isFinite(min_x) &&
      typeof min_y === 'number' && Number.isFinite(min_y) &&
      typeof max_x === 'number' && Number.isFinite(max_x) &&
      typeof max_y === 'number' && Number.isFinite(max_y)
    ) {
      return [min_x, min_y, max_x, max_y];
    }
  }

  if (Array.isArray(input.polygon) && input.polygon.length > 0) {
    if (
      input.polygon.length >= 6 &&
      input.polygon.every((num: any) => typeof num === 'number' && Number.isFinite(num))
    ) {
      let minX = Infinity;
      let minY = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;
      for (let i = 0; i < input.polygon.length - 1; i += 2) {
        minX = Math.min(minX, input.polygon[i]);
        minY = Math.min(minY, input.polygon[i + 1]);
        maxX = Math.max(maxX, input.polygon[i]);
        maxY = Math.max(maxY, input.polygon[i + 1]);
      }
      if (minX !== Infinity && minY !== Infinity && maxX !== -Infinity && maxY !== -Infinity) {
        return [minX, minY, maxX, maxY];
      }
    }

    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    let valid = false;

    for (const p of input.polygon) {
      if (
        Array.isArray(p) &&
        p.length >= 2 &&
        typeof p[0] === 'number' &&
        typeof p[1] === 'number' &&
        Number.isFinite(p[0]) &&
        Number.isFinite(p[1])
      ) {
        minX = Math.min(minX, p[0]);
        minY = Math.min(minY, p[1]);
        maxX = Math.max(maxX, p[0]);
        maxY = Math.max(maxY, p[1]);
        valid = true;
      } else if (
        p &&
        typeof p === 'object' &&
        typeof p.x === 'number' &&
        typeof p.y === 'number' &&
        Number.isFinite(p.x) &&
        Number.isFinite(p.y)
      ) {
        minX = Math.min(minX, p.x);
        minY = Math.min(minY, p.y);
        maxX = Math.max(maxX, p.x);
        maxY = Math.max(maxY, p.y);
        valid = true;
      }
    }

    if (valid && minX !== Infinity && minY !== Infinity && maxX !== -Infinity && maxY !== -Infinity) {
      return [minX, minY, maxX, maxY];
    }
  }

  return null;
}

/**
 * Capture layout and rendering metrics of the displayed image inside the viewport container.
 */
export function getRenderedImageMetrics(
  imageElement: HTMLImageElement | null,
  containerElement: HTMLDivElement | null
) {
  if (!imageElement || !containerElement) {
    return {
      width: 0,
      height: 0,
      naturalWidth: 0,
      naturalHeight: 0,
      offsetLeft: 0,
      offsetTop: 0,
      scaleX: 1,
      scaleY: 1
    };
  }

  const imgRect = imageElement.getBoundingClientRect();
  const containerRect = containerElement.getBoundingClientRect();

  return {
    width: imgRect.width,
    height: imgRect.height,
    naturalWidth: imageElement.naturalWidth || 800,
    naturalHeight: imageElement.naturalHeight || 1000,
    offsetLeft: imgRect.left - containerRect.left,
    offsetTop: imgRect.top - containerRect.top,
    scaleX: imgRect.width / (imageElement.naturalWidth || 1),
    scaleY: imgRect.height / (imageElement.naturalHeight || 1)
  };
}

/**
 * Maps a source coordinate bounding box to the display space of the rendered image.
 */
export function mapBBoxToDisplaySpace(
  bbox: BBox,
  sourceImageSize: { width: number; height: number },
  renderedImageMetrics: any
): BBox {
  let [xMin, yMin, xMax, yMax] = bbox;

  // Multiply by source dimensions if coordinates are normalized
  if (isNormalizedBBox(bbox)) {
    xMin *= sourceImageSize.width;
    xMax *= sourceImageSize.width;
    yMin *= sourceImageSize.height;
    yMax *= sourceImageSize.height;
  }

  const displayXMin = xMin * renderedImageMetrics.scaleX + renderedImageMetrics.offsetLeft;
  const displayXMax = xMax * renderedImageMetrics.scaleX + renderedImageMetrics.offsetLeft;
  const displayYMin = yMin * renderedImageMetrics.scaleY + renderedImageMetrics.offsetTop;
  const displayYMax = yMax * renderedImageMetrics.scaleY + renderedImageMetrics.offsetTop;

  return [displayXMin, displayYMin, displayXMax, displayYMax];
}
