/**
 * The scan region — a band across the middle of the frame.
 *
 * Defined once and shared by the frame cropper and the viewfinder that draws
 * over it, because the two drifting apart is a particular kind of maddening:
 * the box on screen would stop meaning the area actually being read, and
 * aiming would become guesswork.
 *
 * A band rather than the whole frame for two reasons. It is faster — a decoder
 * has a fraction of the pixels to work through, which is what buys the frame
 * rate back on a mid-range Android. And it is easier to aim: a box tells the
 * operator where to hold the pack, where a full-frame scanner just says "point
 * it somewhere".
 *
 * Wide and fairly short, because most reads are 1D retail barcodes, which are
 * wide and short. It is still tall enough for the DataMatrix on a drug pack.
 */
export const SCAN_REGION = {
  widthRatio: 0.86,
  heightRatio: 0.46,
} as const;

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** The region in pixels, for a frame of the given size. */
export function scanRect(frameWidth: number, frameHeight: number): Rect {
  const width = Math.round(frameWidth * SCAN_REGION.widthRatio);
  const height = Math.round(frameHeight * SCAN_REGION.heightRatio);
  return {
    x: Math.round((frameWidth - width) / 2),
    y: Math.round((frameHeight - height) / 2),
    width,
    height,
  };
}
