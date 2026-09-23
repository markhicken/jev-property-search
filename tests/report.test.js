// Deterministic report-filtering contracts. No network, no model calls, no DOM.
// Run with: node --test tests/report.test.js

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  balanceSources,
  escapeHtml,
  homeCheck,
  isPrivateRoom,
  listingAgeDays,
  listingFacts,
  lotSqftValue,
  mergeDetail,
  mismatchesHomeType,
  priceValue,
  rankListings,
  selectListings,
  listingAddress,
  mapsUrl,
  sortByValue,
  sqftValue,
  valueBenchmarks,
  valueMetrics,
  valueRatio,
} from "../jev_ultrafast/static/report.js";

const listing = (overrides = {}) => ({
  href: "https://example.test/1",
  title: "Sunny apartment",
  summary: "Sunny apartment with parking",
  price: "$3,000",
  beds: "2 bd",
  baths: "1 ba",
  sqft: "900 sqft",
  image: "https://example.test/1.jpg",
  ...overrides,
});

const select = (groups, overrides = {}) =>
  selectListings({ groups, minPrice: 2000, maxPrice: 4000, requestedType: "flat", ...overrides });

test("price bounds keep only listings inside the requested range", () => {
  const groups = [
    {
      source: "craigslist",
      listings: [
        listing({ href: "a", price: "$1,900" }),
        listing({ href: "b", price: "$2,000" }),
        listing({ href: "c", price: "$4,000" }),
        listing({ href: "d", price: "$4,100" }),
        listing({ href: "e", price: "Call for price" }),
      ],
    },
  ];
  const { listings, matches } = select(groups);
  assert.equal(matches, 2);
  assert.deepEqual(listings.map((item) => item.href), ["b", "c"]);
  assert.deepEqual(listings.map((item) => item.priceValue), [2000, 4000]);
});

test("a realistic Craigslist card is not stuck at unknown home type", () => {
  // Real card texts that used to score "unknown", which made a match unreachable.
  assert.equal(homeCheck("flat", "slip into smart living! luxury 1bd/1ba"), "pass");
  assert.equal(homeCheck("flat", "thoughtfully styled 1br home with private bathin"), "pass");
  assert.equal(homeCheck("flat", "spacious 1 bedroom 1 bathroom home with a bright and open feel"), "pass");
  assert.equal(homeCheck("flat", "corner penthouse unit on top of nob hill"), "pass");
  assert.equal(homeCheck("flat", "spacious studio $1700 lake merritt"), "pass");
  assert.equal(homeCheck("flat", "sunny apartment with parking"), "pass");
});

test("home type still fails when the card contradicts the request", () => {
  assert.equal(homeCheck("flat", "charming single-family house with a yard"), "fail");
  assert.equal(homeCheck("studio", "one-bedroom apartment"), "fail");
  assert.equal(homeCheck("studio", "2br flat"), "fail");
  assert.equal(homeCheck("house", "bright apartment near the park"), "fail");
  assert.equal(homeCheck("house", "townhouse with a garage"), "pass");
});

test("home type stays unknown with no signal at all", () => {
  assert.equal(homeCheck("flat", "great location, must see"), "unknown");
  assert.equal(homeCheck("house", "great location, must see"), "unknown");
});

test("multi-family matches duplex/triplex/fourplex and rejects flats or single-family houses", () => {
  assert.equal(homeCheck("multifamily", "charming duplex, both units updated"), "pass");
  assert.equal(homeCheck("multifamily", "turnkey triplex, three units"), "pass");
  assert.equal(homeCheck("multifamily", "fourplex investment opportunity"), "pass");
  assert.equal(homeCheck("multifamily", "modern one-bedroom apartment"), "fail");
  assert.equal(homeCheck("multifamily", "charming single-family house with a yard"), "fail");
  assert.equal(homeCheck("multifamily", "great location, must see"), "unknown");
});

test("a card that states its city and unit can qualify", () => {
  const groups = [{ source: "craigslist", listings: [{
    href: "https://example.test/1", price: "$2,400",
    title: "Spacious 1 Bedroom 1 Bathroom Home with a Bright and Open Feel",
    summary: "Spacious 1 Bedroom 1 Bathroom Home 9/20 1br San Francisco, CA $2,400",
  }] }];
  const result = selectListings({ groups, minPrice: 0, maxPrice: 4000, requestedType: "flat",
    location: "San Francisco, CA", daysListed: 30 });
  assert.equal(result.qualified.length, 1, JSON.stringify(result));
});

test("a detail-page description can confirm the city the card omitted", () => {
  const base = {
    href: "https://example.test/2", price: "$2,400", posted_text: "Today",
    title: "Sunny 1 bedroom home", summary: "Sunny 1 bedroom home 1br $2,400",
  };
  const select = (extra) => selectListings({
    groups: [{ source: "craigslist", listings: [{ ...base, ...extra }] }],
    minPrice: 0, maxPrice: 4000, requestedType: "flat", location: "San Francisco, CA", daysListed: 30,
  });
  assert.equal(select({}).qualified.length, 0, "the card alone has no city evidence");
  assert.equal(select({ description: "Located in San Francisco, CA near the park." }).qualified.length, 1);
  // A description naming a different city is evidence the listing is outside the request.
  const elsewhere = select({ description: "Located in Oakland, CA near Lake Merritt." });
  assert.equal(elsewhere.qualified.length, 0);
  assert.equal(elsewhere.excluded.length, 1);
  assert.match(elsewhere.excluded[0].reason, /city/i);
});

test("a card date is never replaced by a page phrase we cannot read", () => {
  const card = { href: "https://example.test/6", price: "$2,400", title: "Home", summary: "Home $2,400",
    posted_text: "9/20" };
  const merged = mergeDetail(card, { posted: "September 20", description: "Nice" });
  assert.equal(merged.posted_text, "9/20", "the readable card date wins");
  const filled = mergeDetail({ href: "https://example.test/7", price: "$2,400" }, { posted: "September 20" });
  assert.equal(filled.posted_text, "September 20", "a missing date is still filled in");
});

test("a truncated card time falls back to the date in the card text", () => {
  const now = Date.parse("2026-09-21T12:00:00Z");
  // A real Craigslist card: the <time> element yields "about 16", the card text carries 9/20.
  const listing = { posted_text: "about 16", summary: "Spacious 1 Bedroom Home 9/20 1br San Francisco, CA $945" };
  const age = listingAgeDays(listing, now);
  assert.ok(age != null && age <= 2, `expected a recent age, got ${age}`);
  assert.equal(listingAgeDays({ posted_text: "about 16", summary: "no date at all" }, now), null);
});

test("a written month parses as a listing age", () => {
  const now = Date.parse("2026-09-21T12:00:00Z");
  assert.ok(listingAgeDays({ posted_text: "September 20" }, now) <= 2);
  assert.ok(listingAgeDays({ posted_text: "Sep 20, 2026" }, now) <= 2);
  assert.ok(listingAgeDays({ posted_text: "August 1" }, now) > 40);
  // A future date with no year means last year, not a negative age.
  assert.ok(listingAgeDays({ posted_text: "December 25" }, now) > 200);
  assert.equal(listingAgeDays({ posted_text: "no date here" }, now), null);
});

test("detail facts fill gaps and can replace an explicitly uncertain card price", () => {
  const card = { href: "https://example.test/4", price: "$2,000+", title: "Home", summary: "Home $2,000+" };
  const merged = mergeDetail(card, {
    price: "$2,300", beds: "2 bd", baths: "1 ba", sqft: "800ft2",
    address: "401 Rose St, San Francisco, CA", description: "Bright unit", posted: "15 days ago",
    amenities: ["parking", "laundry"],
  });
  assert.equal(merged.price, "$2,300", "a '+' price is not a settled rent");
  assert.equal(merged.beds, "2 bd");
  assert.equal(merged.sqft, "800ft2");
  assert.deepEqual(merged.amenities, ["parking", "laundry"]);
  assert.equal(merged.enriched, true);
});

test("the listing's own page wins on unit size, but never over a settled price", () => {
  const card = { href: "https://example.test/5", price: "$2,900", title: "Bright flat",
    summary: "Bright flat", beds: "1 bd", image: "https://example.test/5.jpg" };
  const merged = mergeDetail(card, { price: "$9,999", beds: "3 bd", description: "Nice" });
  assert.equal(merged.beds, "3 bd", "the listing's own page is more specific than the card snippet");
  assert.equal(merged.price, "$2,900", "a settled card price is not replaced by a page price");
  assert.equal(merged.description, "Nice");
  assert.equal(merged.image, "https://example.test/5.jpg");
});

test("a partial card is enriched by detail facts without losing the card's own values", () => {
  const enriched = {
    href: "https://example.test/3", price: "$2,900", title: "Bright flat", summary: "Bright flat $2,900",
    beds: "2 bd", baths: "1 ba", sqft: "800ft2", address: "401 Rose St, San Francisco, CA",
    amenities: ["parking", "laundry"], posted_text: "Today",
  };
  const result = selectListings({
    groups: [{ source: "craigslist", listings: [enriched] }],
    minPrice: 0, maxPrice: 4000, requestedType: "flat", location: "San Francisco, CA", daysListed: 30,
  });
  assert.equal(result.qualified.length, 1, JSON.stringify(result));
  assert.equal(result.qualified[0].checks.location, "pass");
  assert.equal(result.qualified[0].address, "401 Rose St, San Francisco, CA");
});

test("a house-only card is excluded from a Flat request but kept for House", () => {
  const groups = [
    {
      source: "zillow",
      listings: [
        listing({ href: "house", title: "Charming single-family house", summary: "house" }),
        listing({ href: "flat", title: "Modern apartment", summary: "apartment" }),
      ],
    },
  ];
  assert.deepEqual(select(groups).listings.map((item) => item.href), ["flat"]);
  assert.deepEqual(select(groups, { requestedType: "house" }).listings.map((item) => item.href), ["house"]);
});

test("a studio request excludes whole apartments and houses", () => {
  const groups = [
    {
      source: "redfin",
      listings: [
        listing({ href: "studio", title: "Studio with a view", summary: "studio" }),
        listing({ href: "flat", title: "One-bedroom apartment", summary: "apartment" }),
      ],
    },
  ];
  assert.deepEqual(select(groups, { requestedType: "studio" }).listings.map((item) => item.href), ["studio"]);
  assert.equal(mismatchesHomeType("studio", "one-bedroom apartment"), true);
});

test("private rooms, shares, and roommate ads are excluded", () => {
  for (const text of ["Private room in Mission", "Room for rent", "Roommate wanted", "Shared room near BART"]) {
    assert.equal(isPrivateRoom(text), true, text);
  }
  assert.equal(isPrivateRoom("Bright one-bedroom apartment"), false);
  const groups = [
    {
      source: "craigslist",
      listings: [listing({ href: "room", title: "Private room in a shared flat", summary: "private room" })],
    },
  ];
  assert.equal(select(groups).matches, 0);
});

test("the private-room exclusion only applies to rentals, not for-sale listings", () => {
  const groups = [
    {
      source: "craigslist",
      listings: [listing({ href: "room", title: "Private room in a shared flat", summary: "private room" })],
    },
  ];
  assert.equal(select(groups, { mode: "rent" }).matches, 0, "rent mode excludes private rooms");
  assert.equal(select(groups, { mode: "buy" }).matches, 1, "buy mode does not exclude on room wording");
});

test("hrefs are deduplicated across sources", () => {
  const shared = listing({ href: "https://example.test/shared" });
  const groups = [
    { source: "zillow", listings: [shared] },
    { source: "redfin", listings: [{ ...shared }] },
  ];
  const { listings, matches, countsBySource } = select(groups);
  assert.equal(matches, 1);
  assert.equal(listings.length, 1);
  assert.equal(listings[0].source, "zillow");
  assert.deepEqual(countsBySource, { zillow: 1 });
});

test("richer cards rank first and price breaks completeness ties", () => {
  const rich = listing({ href: "rich", price: "$3,900" });
  const sparse = listing({ href: "sparse", price: "$2,100", beds: "", baths: "", sqft: "", image: "" });
  assert.deepEqual(rankListings([sparse, rich]).map((item) => item.href), ["rich", "sparse"]);
  const cheapRich = listing({ href: "cheap", price: "$2,100" });
  const dearRich = listing({ href: "dear", price: "$3,900" });
  assert.deepEqual(rankListings([dearRich, cheapRich]).map((item) => item.href), ["cheap", "dear"]);
});

test("source balancing keeps every source in a small report", () => {
  const many = Array.from({ length: 20 }, (_, index) =>
    listing({ href: `many-${index}`, price: `$${2000 + index}` }),
  );
  const few = [listing({ href: "few-1" }), listing({ href: "few-2" })];
  const { listings, shown } = select(
    [
      { source: "zillow", listings: many },
      { source: "craigslist", listings: few },
    ],
    { limit: 4 },
  );
  assert.equal(shown, 4);
  const sources = new Set(listings.map((item) => item.source));
  assert.deepEqual([...sources].sort(), ["craigslist", "zillow"]);
  assert.equal(listings.filter((item) => item.source === "craigslist").length, 2);
});

test("balanceSources respects the limit and stops when buckets empty", () => {
  const ranked = [listing({ href: "a", source: "zillow" })];
  assert.equal(balanceSources(ranked, 18).length, 1);
  assert.equal(balanceSources([], 18).length, 0);
});

test("missing metadata is reported as unavailable, not as zero", () => {
  const facts = listingFacts(listing({ beds: "2 bd", baths: "", sqft: "" }));
  assert.deepEqual(
    facts.map((fact) => [fact.label, fact.available]),
    [["beds", true], ["baths", false], ["sqft", false]],
  );
  const zero = listingFacts(listing({ beds: "0 bd", baths: "", sqft: "" }))[0];
  assert.equal(zero.available, true);
  assert.equal(zero.value, "0 bd");
});

test("selectListings defaults to at most 18 cards", () => {
  const many = Array.from({ length: 40 }, (_, index) =>
    listing({ href: `h-${index}`, price: `$${2000 + index}` }),
  );
  const { matches, shown } = select([{ source: "zillow", listings: many }]);
  assert.equal(matches, 40);
  assert.equal(shown, 18);
});

test("priceValue parses currency and rejects non-numeric prices", () => {
  assert.equal(priceValue("$4,215"), 4215);
  assert.equal(priceValue("$5,265+"), 5265);
  assert.equal(priceValue(""), null);
  assert.equal(priceValue("Call for price"), null);
  assert.equal(priceValue(undefined), null);
});

test("sqftValue parses living-area square footage", () => {
  assert.equal(sqftValue("1,800 sqft"), 1800);
  assert.equal(sqftValue("900ft2"), 900);
  assert.equal(sqftValue(""), null);
  assert.equal(sqftValue(undefined), null);
});

test("lotSqftValue normalizes acres and labeled lot square footage to one scale", () => {
  assert.equal(lotSqftValue("0.25 acres"), 0.25 * 43560);
  assert.equal(lotSqftValue("1.2 ac lot"), 1.2 * 43560);
  assert.equal(lotSqftValue("10,890 sqft lot"), 10890);
  // A living-area sqft mention with no "lot" qualifier is not a lot size.
  assert.equal(lotSqftValue("1,800 sqft"), null);
  assert.equal(lotSqftValue(""), null);
});

test("valueMetrics computes price-efficiency ratios only when their inputs exist", () => {
  const full = valueMetrics({ priceValue: 435600, sqft: "1,800 sqft", lot: "0.5 acres" });
  assert.equal(full.pricePerSqft, 242);
  assert.equal(full.pricePerAcre, 435600 / 0.5);
  assert.equal(full.pricePerTotalSqft, 435600 / (1800 + 0.5 * 43560));
  const sqftOnly = valueMetrics({ priceValue: 435600, sqft: "1,800 sqft" });
  assert.equal(sqftOnly.pricePerSqft, 242);
  assert.equal(sqftOnly.pricePerAcre, null);
  assert.equal(sqftOnly.pricePerTotalSqft, null);
  const none = valueMetrics({ price: "Call for price" });
  assert.deepEqual(none, { pricePerSqft: null, pricePerAcre: null, pricePerTotalSqft: null });
});

test("sortByValue orders by the chosen ratio and pushes listings missing it to the end", () => {
  const cheap = { href: "cheap", priceValue: 200000, sqft: "2,000 sqft" }; // $100/sqft
  const pricey = { href: "pricey", priceValue: 300000, sqft: "1,000 sqft" }; // $300/sqft
  const noSqft = { href: "no-sqft", priceValue: 100000 };
  const sorted = sortByValue([pricey, noSqft, cheap], "price_per_sqft");
  assert.deepEqual(sorted.map((item) => item.href), ["cheap", "pricey", "no-sqft"]);
  // An unknown sort key is a no-op so the caller's own order is preserved.
  assert.deepEqual(sortByValue([pricey, cheap], "default"), [pricey, cheap]);
});

test("sortByValue value_ratio ranks the best value first and pushes listings with no metric last", () => {
  // Against the set median, cheaper per sqft = higher value ratio = ranked earlier.
  const great = { href: "great", priceValue: 100000, sqft: "2,000 sqft" }; // $50/sqft
  const fair = { href: "fair", priceValue: 200000, sqft: "2,000 sqft" }; // $100/sqft
  const pricey = { href: "pricey", priceValue: 400000, sqft: "2,000 sqft" }; // $200/sqft
  const noMetric = { href: "no-metric", priceValue: 150000 };
  const sorted = sortByValue([fair, noMetric, pricey, great], "value_ratio");
  assert.deepEqual(sorted.map((item) => item.href), ["great", "fair", "pricey", "no-metric"]);
});

test("valueBenchmarks takes the median price per sqft and per acre across the set", () => {
  const listings = [
    { priceValue: 200000, sqft: "2,000 sqft", lot: "0.5 acres" }, // $100/sqft, $400k/acre
    { priceValue: 300000, sqft: "1,500 sqft", lot: "1 acre" }, // $200/sqft, $300k/acre
    { priceValue: 300000, sqft: "1,000 sqft" }, // $300/sqft, no lot
  ];
  const benchmarks = valueBenchmarks(listings);
  assert.equal(benchmarks.pricePerSqft, 200); // median of 100, 200, 300
  assert.equal(benchmarks.pricePerAcre, 350000); // median of the two lots: 400k, 300k
  assert.deepEqual(valueBenchmarks([]), { pricePerSqft: null, pricePerAcre: null });
});

test("valueRatio rewards beating both benchmarks and needs at least one metric", () => {
  const benchmarks = { pricePerSqft: 200, pricePerAcre: 400000 };
  // $100/sqft and $200k/acre: twice as cheap on both, geometric mean is 2x.
  const bargain = { priceValue: 200000, sqft: "2,000 sqft", lot: "1 acre" };
  assert.equal(valueRatio(bargain, benchmarks), 2);
  // Cheap per sqft but pricey per acre: the geometric mean lands near typical.
  const mixed = { priceValue: 400000, sqft: "4,000 sqft", lot: "0.5 acres" }; // $100/sqft, $800k/acre
  assert.ok(Math.abs(valueRatio(mixed, benchmarks) - 1) < 1e-9);
  // Only price/sqft is known, so the ratio rests on that single metric.
  assert.equal(valueRatio({ priceValue: 200000, sqft: "2,000 sqft" }, benchmarks), 2);
  // No usable metric at all.
  assert.equal(valueRatio({ price: "Call for price" }, benchmarks), null);
  assert.equal(valueRatio({ priceValue: 200000, sqft: "2,000 sqft" }, { pricePerSqft: null, pricePerAcre: null }), null);
});

test("listingAddress uses the street address, never the listing title", () => {
  // No street address (common on Craigslist/Facebook): return null so the card hides its
  // address actions rather than copying/mapping a meaningless headline.
  assert.equal(listingAddress({ title: "4 Bed/2 Bath Move in Ready!" }, "Meridian, ID"), null);
  // A full address with a state is used as-is.
  assert.equal(
    listingAddress({ address: "742 Evergreen Terrace, Austin, TX", title: "Cozy home" }, "Austin, TX"),
    "742 Evergreen Terrace, Austin, TX",
  );
  // A bare street address gains the search location for disambiguation.
  assert.equal(
    listingAddress({ address: "742 Evergreen Terrace" }, "Austin, TX"),
    "742 Evergreen Terrace, Austin, TX",
  );
  // A ZIP counts as a region, so nothing is appended.
  assert.equal(listingAddress({ address: "742 Evergreen Terrace 78704" }, "Austin, TX"), "742 Evergreen Terrace 78704");
});

test("mapsUrl builds a Google Maps search link with an encoded address", () => {
  assert.equal(
    mapsUrl("742 Evergreen Terrace, Austin, TX"),
    "https://www.google.com/maps/search/?api=1&query=742%20Evergreen%20Terrace%2C%20Austin%2C%20TX",
  );
});

test("escapeHtml neutralizes markup and attribute injection", () => {
  assert.equal(escapeHtml('a&b<c>"d"\'e'), "a&amp;b&lt;c&gt;&quot;d&quot;&#39;e");
  assert.equal(escapeHtml(null), "");
  assert.equal(escapeHtml(0), "0");
  assert.equal(
    escapeHtml('"><img src=x onerror=alert(1)>'),
    "&quot;&gt;&lt;img src=x onerror=alert(1)&gt;",
  );
});
