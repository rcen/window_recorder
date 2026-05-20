# -*- coding: utf-8 -*-
"""
Centralized Category Definitions
================================
Single source of truth for all activity category classifications.
Import from this module instead of hardcoding categories elsewhere.

Usage:
    from categories import PRODUCTIVE_CATS, WASTED_CATS, JOB_CATS
"""

# =============================================================================
# CATEGORY GROUPS
# =============================================================================

# Productive activities - count toward productivity metrics and streaks
PRODUCTIVE_CATS = frozenset({
    "work",
    "coding", 
    "programming",
    "vibe",
    "learning",
    "church",
    "think",
    "job_search",
    "mail",  # Work communication
})

# Wasted/distracted activities - count against productivity
WASTED_CATS = frozenset({
    "wasted",
    "wasted time",
    "gaming",
    "facebook",
    "shopping",
    "youtube",
    "reddit",
    "twitter",
})

# Job-related activities - satisfy the job balance requirement
JOB_CATS = frozenset({
    "job_search",
    "current_job",
    "interview",
    "job",
    "career",
    "linkedin",
    "indeed",
    "glassdoor",
    "dice",
})

# Vibe/personal coding activities - require job balance offset
VIBE_CATS = frozenset({
    "work",
    "coding",
    "vibe", 
    "programming",
    "learning",
})

# Neutral activities - don't break streaks, don't count as productive or wasted
NEUTRAL_CATS = frozenset({
    "idle",
    "family",
    "mail",
})

# Categories to display in the daily summary ratio table
RATIO_DISPLAY_CATS = frozenset({
    "family",
    "gaming",
    "work",
    "wasted",
    "learning",
    "church",
    "mail",
    "job_search",
})

# =============================================================================
# PRIORITY FOR CONFLICT RESOLUTION
# =============================================================================

# Lower number = higher priority when resolving overlapping activities
CATEGORY_PRIORITY = {
    'work': 1,
    'programming': 1,
    'coding': 1,
    'vibe': 1,
    'job_search': 1,
    'learning': 2,
    'mail': 2,
    'church': 2,
    'family': 3,
    'not categorized': 4,
    'wasted': 5,
    'wasted time': 5,
    'gaming': 5,
    'idle': 10,
}

# =============================================================================
# CATEGORY ALIASES
# =============================================================================

# Maps goal categories to actual database categories for aggregation
CATEGORY_ALIASES = {
    'work': ['work', 'coding', 'programming', 'docs', 'documents'],
    'programming': ['work', 'coding', 'programming'],  # Legacy support
    'wasted time': ['wasted', 'wasted time', 'gaming'],
    'job_search': ['job_search', 'job', 'career', 'current_job', 'interview'],
    'learning': ['learning'],
}

# =============================================================================
# CATEGORY DISPLAY PROPERTIES
# =============================================================================

# Optional per-category properties. Defaults apply when category isn't present.
# Use this to hide categories from UI tables without changing classification.
CATEGORY_PROPERTIES: dict[str, dict] = {
    # Internal/utility categories that add noise in Activity Summary.
    'no_cat': {'enable_display': False},
    'think': {'enable_display': False},
}


def _match_category_key(category: str, key: str) -> bool:
    """Return True if category matches key exactly or as a prefix like 'key: ...'."""
    cat = (category or '').strip().lower()
    key = (key or '').strip().lower()
    if not cat or not key:
        return False
    return cat == key or cat.startswith(key + ':') or cat.startswith(key + ' ')


def should_display_in_activity_summary(category: str) -> bool:
    """Whether a category should appear as a column in the Activity Summary table."""
    cat = (category or '').strip().lower()
    if not cat:
        return False

    for key, props in CATEGORY_PROPERTIES.items():
        if _match_category_key(cat, key):
            return bool(props.get('enable_display', True))
    return True

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def is_productive(category: str) -> bool:
    """Check if a category is considered productive."""
    return category.lower() in PRODUCTIVE_CATS


def is_wasted(category: str) -> bool:
    """Check if a category is considered wasted time."""
    return category.lower() in WASTED_CATS


def is_job_related(category: str) -> bool:
    """Check if a category satisfies job balance requirement.
    
    Uses substring matching to handle categories like 
    'job_search                linkedin: job_search'.
    """
    cat_lower = category.lower()
    # First try exact match
    if cat_lower in JOB_CATS:
        return True
    # Then check if any job keyword is in the category string
    return any(job_cat in cat_lower for job_cat in JOB_CATS)


def is_vibe(category: str) -> bool:
    """Check if a category requires job balance offset."""
    return category.lower() in VIBE_CATS


def is_neutral(category: str) -> bool:
    """Check if a category is neutral (doesn't affect productivity metrics)."""
    return category.lower() in NEUTRAL_CATS


def get_priority(category: str, default: int = 99) -> int:
    """Get conflict resolution priority for a category (lower = higher priority)."""
    return CATEGORY_PRIORITY.get(category.lower(), default)


def get_aliases(category: str) -> list:
    """Get all aliases for a category for goal aggregation."""
    return CATEGORY_ALIASES.get(category.lower(), [category.lower()])


def aggregate_stats(stats: dict, category: str) -> float:
    """Aggregate stats across all aliases for a category."""
    aliases = get_aliases(category)
    return sum(stats.get(alias, 0) for alias in aliases)


# =============================================================================
# CATEGORY SETS FOR SPECIFIC USE CASES
# =============================================================================

# Categories that should show in Recent Activity with green highlight
RECENT_ACTIVITY_PRODUCTIVE = PRODUCTIVE_CATS

# Categories that should show in Recent Activity with red highlight  
RECENT_ACTIVITY_DISTRACTED = WASTED_CATS | {"no_cat", "not categorized"}

# Categories that don't break focus streaks (short idle allowed)
STREAK_NEUTRAL = frozenset({"idle", "mail"})

# Categories that break focus streaks
STREAK_BREAKERS = WASTED_CATS | {"family", "no_cat", "not categorized"}
