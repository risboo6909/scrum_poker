const { test } = require("node:test");
const assert = require("node:assert/strict");
const { isSnowSeason } = require("../static/snow.js");

test("snow is shown only during December in the visitor's local time", () => {
  assert.equal(isSnowSeason(new Date(2026, 10, 30, 23, 59)), false);
  assert.equal(isSnowSeason(new Date(2026, 11, 1, 0, 0)), true);
  assert.equal(isSnowSeason(new Date(2026, 11, 31, 23, 59)), true);
  assert.equal(isSnowSeason(new Date(2027, 0, 1, 0, 0)), false);
  assert.equal(isSnowSeason(new Date(2027, 11, 1, 0, 0)), true);
});
