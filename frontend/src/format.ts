import { finite } from "./api";
const standardNumber = new Intl.NumberFormat("it-IT", {maximumFractionDigits: 4});
const smallNumber = new Intl.NumberFormat("it-IT", {maximumFractionDigits: 8});
const scientificNumber = new Intl.NumberFormat("it-IT", {notation: "scientific", maximumFractionDigits: 4});
export function number(value: unknown, unit = ""): string {
  const n = finite(value);
  if (n === null) return "N/D";
  const magnitude = Math.abs(n);
  const formatter = magnitude > 0 && magnitude < 1e-8
    ? scientificNumber : magnitude > 0 && magnitude < 1e-4 ? smallNumber : standardNumber;
  return `${formatter.format(n === 0 ? 0 : n)}${unit ? ` ${unit}` : ""}`;
}
/** Valid broker/source quote precision (0–10 decimals), otherwise null. */
export function priceDigits(value: unknown): number | null {
  return typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= 10 ? value : null;
}
const significantPrice = new Intl.NumberFormat("it-IT", {maximumSignificantDigits: 10});
/** Prices keep the instrument's declared decimals (EURUSD 5, USDJPY 3); unknown precision keeps 10 significant digits instead of a fixed rounding. */
export function price(value: unknown, digits: unknown = null, unit = ""): string {
  const n = finite(value);
  if (n === null) return "N/D";
  const d = priceDigits(digits);
  const text = d === null
    ? significantPrice.format(n === 0 ? 0 : n)
    : new Intl.NumberFormat("it-IT", {minimumFractionDigits: d, maximumFractionDigits: d}).format(n === 0 ? 0 : n);
  return `${text}${unit ? ` ${unit}` : ""}`;
}
export function instant(value: unknown): string {
  if (typeof value !== "string" && typeof value !== "number") return "N/D";
  if (typeof value === "string" && !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value.trim())) return "N/D";
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
