import { displayCustomerName } from "./displayCustomerName";

describe("displayCustomerName", () => {
  it("strips a final standalone 0 suffix", () => {
    expect(displayCustomerName("Monica Palenzuela 0")).toBe("Monica Palenzuela");
    expect(displayCustomerName("Olivia Marrese 0")).toBe("Olivia Marrese");
    expect(displayCustomerName("AngelList NY 0")).toBe("AngelList NY");
    expect(displayCustomerName("Eva Pitsoulakis 0")).toBe("Eva Pitsoulakis");
    expect(displayCustomerName("John Smith 0")).toBe("John Smith");
  });

  it("does not strip non-suffix or embedded zeros", () => {
    expect(displayCustomerName("Customer 10")).toBe("Customer 10");
    expect(displayCustomerName("Studio 0 West")).toBe("Studio 0 West");
    expect(displayCustomerName("John Smith")).toBe("John Smith");
    expect(displayCustomerName("Order 0A")).toBe("Order 0A");
  });

  it("trims whitespace and handles empty input", () => {
    expect(displayCustomerName("  Ada Lovelace 0  ")).toBe("Ada Lovelace");
    expect(displayCustomerName("")).toBe("");
    expect(displayCustomerName(null)).toBe("");
    expect(displayCustomerName(undefined)).toBe("");
  });
});
