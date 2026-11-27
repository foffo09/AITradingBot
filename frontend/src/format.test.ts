import {describe,it,expect} from "vitest";
import {number,instant,price} from "./format";

describe("numeri senza falsi zeri",()=>{
  it.each([[0.00001234,"0,00001234"],[-0.00001234,"-0,00001234"],[1e-10,"1E-10"],[-1e-10,"-1E-10"],[-0,"0"]])("mostra %s come %s",(value,expected)=>{
    expect(number(value)).toBe(expected);
  });
  it("mantiene unità, precisione normale e dati assenti",()=>{
    expect(number(123.456789,"USD")).toBe("123,4568 USD");
    expect(number(0,"USD")).toBe("0 USD");
    expect(number(.65425543,"USD")).toBe("0,6543 USD");
    expect(number(.23386224,"%")).toBe("0,2339 %");
    for(const value of [null,undefined,NaN,Infinity,"",true])expect(number(value)).toBe("N/D");
    expect(instant("invalid")).toBe("N/D");
  });
});

describe("prezzi con la precisione dello strumento",()=>{
  it("forex a 5 decimali: bid e ask restano distinti, zeri finali conservati",()=>{
    expect(price(1.08345,5)).toBe("1,08345");
    expect(price(1.08347,5)).toBe("1,08347");
    expect(price(1.083,5)).toBe("1,08300");
  });
  it("coppie JPY a 3 decimali e azioni a 2",()=>{
    expect(price(147.123,3,"JPY")).toBe("147,123 JPY");
    expect(price(187.5,2)).toBe("187,50");
  });
  it("precisione ignota: cifre significative, mai arrotondamenti fissi",()=>{
    expect(price(0.00015)).toBe("0,00015");
    expect(price(0.00012345)).toBe("0,00012345");
    expect(price(1.08345)).toBe("1,08345");
    expect(price(95000.12)).toBe("95.000,12");
    expect(price(0.1+0.2)).toBe("0,3");
  });
  it("precisione non valida o valore assente",()=>{
    for (const d of [-1,11,2.5,"5",true,NaN]) expect(price(1.08345,d)).toBe("1,08345");
    for (const v of [null,undefined,NaN,Infinity,"",true]) expect(price(v,5)).toBe("N/D");
    expect(price(-0,2)).toBe("0,00");
  });
});
