# Capital policy release validation

This release introduces verified-NAV-based live capital management starting from €80 while preserving the historical €50 seed baseline.

Hard release invariants remain unchanged: maximum portfolio drawdown 10%, maximum daily loss 3%, minimum cash reserve 20%, bounded concentration, spot-only execution, and no leverage, margin, futures, borrowing, or martingale.

Growth/reporting ladder: €80 → €250 → €500 → €1,000 → €5,000 → €10,000 → €50,000 → €100,000+.

Production promotion requires an executable green test suite, a healthy staging deployment, `armed=false`, zero exchange open orders, and zero nonterminal journal orders before merge and deployment.
