import {describe,it,expect} from "vitest";
import {number,instant} from "./format";

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
