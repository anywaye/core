import { test, expect } from "vitest";

test("behaviour", () => {
  const response = getUser(1);
  expect(response.name).toBe("Alice");
});
