const PHASES = ["new", "waxing", "full", "waning"];

export function parseMoonPhase(text: string): string | null {
  const word = text.trim().toLowerCase();
  return PHASES.includes(word) ? word : null;
}
