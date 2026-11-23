export function getTideTable(port: string): { port: string; rows: number[] } {
  return { port, rows: [] };
}

export function getTideTables(ports: string[]) {
  return ports.map(getTideTable);
}
