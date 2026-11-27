# Changelog

All notable changes to this project are documented in this file. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

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
