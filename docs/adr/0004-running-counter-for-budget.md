# Running counter for budget tracking, not escrow or holds

Mandate tracks spend as a running counter: total spent + new amount must not exceed budget. The money stays in the agent wallet until each payment settles via Circle Nanopayments. We rejected pre-paid escrow (adds a lock/draw-down/refund contract with no demo value) and pre-auth holds (mimics the credit-card authorization flow that caused the exact double-hold bug we are trying to prevent — $179.80 held on a $150 limit in the Reddit post-mortem).
