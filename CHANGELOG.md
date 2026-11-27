# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [1.0.1] - 2026-11-27

### Added

- A Polish version of the README (`READMEPL.md`) with an English | Polski link under the title of both files.

### Fixed

- Polish README texts from `scripts/make_charts.py`: plural forms agree with the count and several sentences read more naturally.

## [1.0.0] - 2026-11-27

### Added
- Daily demand forecast per product: a Poisson regression season per category (month, weekday, trading days) times
  the TSB level of the product; days that began out of stock are not demand.
- Ordering policies on the same interface: the planner (periodic review order-up-to level, negative binomial
  quantile, one stock budget shared by margin per zloty), fixed ABC service levels, the buyer by eye rebuilt from
  Data-Generator and a perfect forecast as the ceiling.
- The 2024 backtest on the true demand (sold and lost lines of Data-Generator 1.8.0) and tuning on a second shop.
- The 30-day purchase plan per supplier with a reason per line, an Excel order per supplier and `main.py --check`.
- A Dash app with Mantine in the portfolio look: the backtest, the plan of one supplier with its download and one
  product with its stock, forecast and planned deliveries.
- The README as a case study in English (the repository is public from this release), with charts and the animated
  demo rendered in English by `scripts/make_charts.py --lang en` and `scripts/make_demo_svg.py --lang en`.

### Data
- Data Generator v1.8.0 (public tag) with stockouts on, seeds 42 and 7: `scripts/get_data.py` gives the same tables
  byte for byte as the release branch it was built on.
