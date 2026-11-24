"""Business collections shared by pilot installations and synthetic sample data."""

CARE_COLLECTIONS = (
    "beds",
    "residents",
    "inquiries",
    "leadContacts",
    "leadEvents",
    "visitBookings",
    "visitSchedulePolicies",
    "assessments",
    "plans",
    "tasks",
    "medications",
    "vitals",
    "handovers",
    "leaves",
    "qualityChecks",
    "careTimelineSettings",
    "bedMoves",
    "archives",
    "followups",
    "trialFollowups",
    "trialPolicies",
    "referrals",
    "drugRules",
    "longCareEvents",
)

OPERATIONS_COLLECTIONS = (
    "inventory",
    "transactions",
    "bills",
    "deposits",
    "depositEntries",
    "payments",
    "paymentOrders",
    "paymentFeeSettings",
    "channelReceipts",
    "expenses",
    "shifts",
    "reports",
    "suggestions",
    "supplyOrders",
    "staffNotices",
)


def empty_workspace():
    """Allocate an independent, empty ledger for every business collection."""
    return {name: [] for name in (*CARE_COLLECTIONS, *OPERATIONS_COLLECTIONS)}
