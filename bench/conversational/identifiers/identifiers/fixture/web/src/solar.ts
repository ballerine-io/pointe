export function sunriseOffset(lat: number): number {
  return Math.round((lat / 15) * 100) / 100;
}
