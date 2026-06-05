export type BBox = [number, number, number, number];

/**
 * Normalizes input geometry into a standard BBox [x_min, y_min, x_max, y_max] format.
 * Returns null if no valid geometry is found.
 */
export function normalizeBBox(input: any): BBox | null {
  if (!input || typeof input !== 'object') {
    return null;
  }

  // Helper to check if an array represents a valid 4-number bbox
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

  // 1. If input.bbox is an array of 4 finite numbers, return it.
  if (isValidBBoxArray(input.bbox)) {
    return input.bbox as BBox;
  }

  // 2. If input.normalized_bbox is an array of 4 finite numbers, return it.
  if (isValidBBoxArray(input.normalized_bbox)) {
    return input.normalized_bbox as BBox;
  }

  // 3. If input.box is an array of 4 finite numbers, return it.
  if (isValidBBoxArray(input.box)) {
    return input.box as BBox;
  }

  // 4. If input.bounding_box has x_min/y_min/x_max/y_max, return those.
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

  // 5. If input.geometry has min_x/min_y/max_x/max_y, return those.
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

  // 6. If input.polygon is a list of points, compute minX/minY/maxX/maxY.
  if (Array.isArray(input.polygon) && input.polygon.length > 0) {
    // Check if flat array of numbers (e.g. [x1, y1, x2, y2, x3, y3, ...])
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

    // Check if list of points: array of arrays or objects
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
