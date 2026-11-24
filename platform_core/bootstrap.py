"""Business collections shared by pilot installations and synthetic sample data."""

CARE_COLLECTIONS = (
    "beds",
    "residents",
    "inquiries",
    "assessments",
    "plans",
    "tasks",
    "medications",
    "vitals",
    "handovers",
    "leaves",
    "qualityChecks",
    "bedMoves",
    "archives",
)

OPERATIONS_COLLECTIONS = (
    "inventory",
    "transactions",
    "bills",
    "deposits",
    "depositEntries",
    "payments",
    "shifts",
    "reports",
    "suggestions",
)


def empty_workspace():
    """Allocate an independent, empty ledger for every business collection."""
    return {name: [] for name in (*CARE_COLLECTIONS, *OPERATIONS_COLLECTIONS)}
