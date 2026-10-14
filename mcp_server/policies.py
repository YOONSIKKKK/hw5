"""Shop policy constants the agents must reason with.

These are exposed over MCP so the agents read the rules from the shop itself
rather than only from their system prompts.
"""

MIN_GROSS_MARGIN_PCT = 40.0
LOW_STOCK_THRESHOLD = 5
CASH_ACCOUNT = "checking"

POLICIES = {
    "shop_clock": (
        "The shop's current date is desk.date_today. Use it for every overdue or "
        "due-date calculation. Never use the real-world date."
    ),
    "human_approval_required": (
        "Every payment and every purchase order must be approved by the human "
        "supervisor. Agent tools can only REQUEST them; nothing moves money "
        "without a human decision."
    ),
    "cash_floor": (
        "Cash is strictly outgoing -- no revenue enters the system. A payment is "
        "rejected if it would drop the checking balance below zero."
    ),
    "vendor_hold": (
        "A vendor will not ship anything while it has an unpaid invoice. Clear "
        "the outstanding invoice before expecting a restock from that vendor."
    ),
    "lead_times": (
        "Delivery dates come from vendors.lead_days counted from the shop date."
    ),
    "purchase_orders_prepaid": (
        "The shop is on prepay terms, so an approved purchase order pays the "
        "vendor immediately and is subject to the same cash floor."
    ),
    "min_gross_margin_pct": (
        f"Discounts must leave at least {MIN_GROSS_MARGIN_PCT:.0f}% gross margin "
        "on the discounted unit price."
    ),
    "drafts_only": (
        "Customer and vendor messages are DRAFTED onto the board for human "
        "review. The shop never sends real email and never calls a vendor."
    ),
}
