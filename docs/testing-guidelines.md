# Testing Guidelines

Tests in this repository should protect public contracts, safety boundaries,
instrument behavior, and durable documentation structure. They should not make
normal copy, layout, or implementation cleanup unnecessarily hard.

## What To Test

Keep strict tests around behavior that contributors and automation depend on:

- CLI flags, console entry points, exit behavior, and JSON or JSONL schema
  fields.
- HTTP endpoint paths, request payload names, response field names, and stable
  DOM IDs or form `name` attributes used by automation.
- SCPI command order, dry-run plans, confirm gates, restore order, and output
  cleanup.
- Safety validation, hardware lock behavior, simulator versus real-instrument
  boundaries, and package ownership boundaries.
- Checks that private lab resources, real VISA identifiers, credentials, and
  unreleased internal details are not committed.

## What Not To Freeze

Avoid tests that freeze details that can change without breaking the product:

- README prose, tutorial wording, visible UI copy, panel order, button text, and
  local variable names.
- CSS color, grid, spacing, font size, and visual layout details.
- JavaScript helper function names and local implementation structure.
- HTML markup ordering, unless the order is itself an automation, safety,
  accessibility, legal, or privacy contract.

## Documentation Tests

Documentation tests should verify ownership and durable structure. Prefer
checking that canonical files exist, root docs link to them, and stable headings
or tokens such as `SCPI`, `safety`, and `JSON` are present.

Do not assert full paragraphs or exact natural-language sentences unless the
text is a safety warning, legal/privacy statement, public protocol definition,
or package ownership rule.

## Frontend Static Tests

Frontend static tests should protect integration contracts:

- Stable DOM IDs, form field names, select option values, and payload field
  names.
- API endpoint paths such as job submission, live data, event streams, and stop
  requests.
- Safety boundaries, including no advanced JSON injection path in command forms
  and no direct CLI imports from WebUI.
- Response fields shown in job detail or live data panels when other tooling may
  depend on them.

Do not assert exact visible copy, CSS colors, grid layout, helper function
names, local parser names, or implementation ordering unless those details are
documented contracts.

## Instrument Safety Tests

Instrument-facing tests must remain conservative. Keep strict coverage for SCPI
write order, dry-run behavior, confirm requirements, output enable/disable
cleanup, safety limits, restore order, model capability gates, and simulator
versus real-hardware selection.

Default tests must not require hardware. Any test that can affect a real output
must be explicit, opt-in, and require a caller-provided resource.

## Review Standard

When reviewing tests, ask whether a failing assertion indicates a broken public
contract, safety boundary, instrument behavior, or documentation ownership rule.
If the failure only reflects wording, styling, helper names, or local layout,
prefer loosening the test instead of forcing the implementation back to an old
shape.

## Test Output Locations

Run pytest from the repository root. The default pytest basetemp is the ignored
repository-local `.tmp_pytest` directory. When a separate per-run location is
needed, use `.tmp_tests/<purpose>`.

Do not use `Local/` for pytest basetemp directories or generated test artifacts.
`Local/` is reserved for private notes and local reference material.
