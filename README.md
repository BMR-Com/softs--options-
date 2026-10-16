# BMR-Com · Softs Options Analytics

**ICE cotton, coffee and sugar options — daily vol desk, positioning and strategy tools.**

🔗 **Live site:** https://bmr-com.github.io/softs--options-/

| Tab | What it shows |
|---|---|
| **Vol Desk** | Daily read for CT, KC and SB: ATM implied vol and its percentile, realized vs implied, 25-delta skew, put/call positioning, expected moves, and a per-expiry weekly table (futures price and open interest, calendar spreads, vol and skew changes, option flow, call/put walls, max gamma, max pain). Charts: implied vs realized vol, term structure, smile, skew history, open interest and gamma by strike, daily flow. |
| **Option Matrix · Charts · Rankings** | Open interest, volume, settlement and implied vol by strike and expiry. |
| **Gamma · Greeks · Vol Smile** | Black-76 greeks and gamma profile. |
| **Live Pricer · Strategy Builder · Strategy Lab · Portfolio** | Price structures, payoff and stress tests. |
| **Sentiment · Monthly Summary** | Flow and open-interest summaries. |

**Data:** ICE Daily Market Reports (options and futures), archived daily by GitHub Actions to `data/csv/` (`<T>_MASTER.csv` options, `<T>_FUTURES.csv` futures). Price history from the [COT positioning desk](https://github.com/BMR-Com/cftc-cot-full).

---
*BMR-Com · independent commodity research. Not investment advice.*
