import { describe, expect, it } from "vitest";
import { instant } from "./format";

describe("timestamp esplicitamente UTC", () => {
  it("converte un offset ISO attraverso il confine di giorno e anno", () => {
    expect(instant("2026-12-31T23:30:00-01:00")).toBe("01/01/27, 00:30:00 UTC");
    expect(instant("2027-01-01T01:30:00+01:00")).toBe("01/01/27, 00:30:00 UTC");
  });

  it("distingue le due 02:30 nel ritorno dall'ora legale tramite offset", () => {
    const summer = instant("2026-10-25T02:30:00+02:00");
    const winter = instant("2026-10-25T02:30:00+01:00");
    expect(summer).toBe("25/10/26, 00:30:00 UTC");
    expect(winter).toBe("25/10/26, 01:30:00 UTC");
    expect(summer).not.toBe(winter);
  });
});

it("non attribuisce UTC a un orario privo di fuso durante il cambio dell'ora", () => {
  expect(instant("2026-10-25T02:30:00")).toBe("N/D");
});
