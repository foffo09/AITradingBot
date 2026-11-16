import { finite } from "./api";
export function number(value: unknown, unit = ""): string {
  const n = finite(value);
  return n === null
    ? "N/D"
    : `${new Intl.NumberFormat("it-IT", { maximumFractionDigits: 4 }).format(n)}${unit ? ` ${unit}` : ""}`;
}
export function instant(value: unknown): string {
  if (typeof value !== "string" && typeof value !== "number") return "N/D";
  const date = new Date(typeof value === "number" ? value * 1000 : value);
  return Number.isNaN(date.getTime())
    ? "N/D"
    : `${new Intl.DateTimeFormat("it-IT", { dateStyle: "short", timeStyle: "medium", timeZone: "UTC" }).format(date)} UTC`;
}
export function text(value: unknown): string {
  return typeof value === "string"
    ? value
    : typeof value === "number"
      ? number(value)
      : "N/D";
}
