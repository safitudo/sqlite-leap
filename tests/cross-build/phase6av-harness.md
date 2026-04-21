# Phase 6av harness — date/time functions (core subset)

Adds five core date/time functions: `date()`, `time()`, `datetime()`, `julianday()`, `strftime()`. Subset of SQLite's semantics: timestrings parsed as ISO-8601 or julian-day-real; modifier subset covers day/hour/second arithmetic + `start of` truncations. No timezone support in v1 (no `localtime`, no `utc`). No new reserved keywords (function names are identifiers). One new runtime error `RUNTIME_INVALID_TIMESTRING`.

Gate: 10 fixtures green both targets. `SUMMARY phase=6av target=<c|rust> passed=10 failed=0 total=10`.

### Function signatures

```
date(timestring, modifier, ...)      → TEXT 'YYYY-MM-DD'
time(timestring, modifier, ...)      → TEXT 'HH:MM:SS'
datetime(timestring, modifier, ...)  → TEXT 'YYYY-MM-DD HH:MM:SS'
julianday(timestring, modifier, ...) → REAL (julian day number, UT)
strftime(format, timestring, modifier, ...) → TEXT (per format string)
```

All functions accept optional modifiers after the timestring. If any argument is NULL → result is NULL.

### Timestring forms accepted (v1)

- `'YYYY-MM-DD'` — midnight of that date.
- `'YYYY-MM-DD HH:MM:SS'` — space separator.
- `'YYYY-MM-DDTHH:MM:SS'` — ISO-8601 `T` separator.
- `'YYYY-MM-DD HH:MM'` — seconds default 0.
- A real number — interpreted as julian day number (e.g., `2451545.0` = noon 2000-01-01 UT).
- `'now'` — the deterministic fixed instant `2026-04-19 00:00:00` in v1. (SQLite uses wall-clock; fixing a constant in v1 keeps fixtures deterministic. Real-clock binding is a post-publication toggle.)

Any unparseable form → `RUNTIME_INVALID_TIMESTRING { input }`.

### Modifier forms accepted (v1)

- `'+N days'`, `'-N days'` (integer N)
- `'+N hours'`, `'-N hours'`
- `'+N minutes'`, `'-N minutes'`
- `'+N seconds'`, `'-N seconds'`
- `'start of day'` — truncates to 00:00:00 of the same date.
- `'start of month'` — first day of the month at 00:00:00.
- `'start of year'` — Jan 1 of the year at 00:00:00.
- `'unixepoch'` — reinterprets the **prior** arg as a unix timestamp (seconds since 1970-01-01 00:00:00 UTC). When present it must be the first modifier.

Modifiers apply left-to-right. Unknown modifier → `RUNTIME_INVALID_TIMESTRING` (SQLite returns NULL but we pin an error for determinism; harness can switch later if sqllogictest pins NULL).

### strftime format specifiers (v1 subset)

- `%Y` 4-digit year
- `%m` 2-digit month (01-12)
- `%d` 2-digit day (01-31)
- `%H` 2-digit hour (00-23)
- `%M` 2-digit minute
- `%S` 2-digit second
- `%j` 3-digit day-of-year (001-366)
- `%w` 1-digit day-of-week (0=Sunday..6=Saturday)
- `%%` literal `%`

Any other `%X` → `RUNTIME_INVALID_TIMESTRING { format }`.

### Errors

- `RUNTIME_INVALID_TIMESTRING { input }` — unparseable timestring, unknown modifier, or unknown `%X` in strftime format.

### Implementation

- Builtins: add the five functions to the scalar-function table (same mechanism as existing LENGTH / SUBSTR etc. from 6ao).
- Internal representation: parse timestring → (julian_day_real, has_time_component) tuple. Apply modifiers by arithmetic on julian_day_real (day = +1.0, hour = +1/24, etc.). Format back according to function choice.
- Julian day formula: standard integer conversion (Gregorian). v1 supports years 1-9999; out-of-range → `RUNTIME_INVALID_TIMESTRING`.
- `'now'` resolves to the constant `2026-04-19 00:00:00` → julian_day 2461150.0 in v1. Comment in the spec flags this as a v1 determinism decision.

### Non-goals (v1)

- `localtime` / `utc` modifiers (need tz database; huge surface).
- `'weekday N'` modifier.
- Fractional-second output (the format pins `%S` as integer).
- Auto-detect of other timestring forms SQLite accepts (e.g., `'YYYY-MM-DDTHH:MM:SS.fff'` with fractional seconds, `'DDDDDDDDDD'` 10-digit unix timestamp without modifier) — raise `RUNTIME_INVALID_TIMESTRING` in v1.
