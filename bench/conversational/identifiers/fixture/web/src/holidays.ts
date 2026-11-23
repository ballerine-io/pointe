export function loadHolidayRules(text: string): string[] {
  return text.split("\n").map((line) => line.trim()).filter(Boolean);
}
