#!/usr/bin/env python3
"""
check_category.py - Debug tool to check why a URL/window title gets a specific category.

Usage:
    python check_category.py "your window title or URL here"
    python check_category.py --url "www.linkedin.com/pulse/..." --title "how i used ai to break..."
    
This will show:
1. The matching rule that was applied
2. All rules that COULD have matched (but were lower priority)
3. Suggestions for fixing miscategorization
"""

import sys
import re
import argparse
from analytics import Analytics


def check_categorization(window_title: str = None, url: str = None, verbose: bool = True):
    """
    Check how a window title/URL gets categorized and show debugging info.
    
    Returns: dict with category, matching_rule, and all_matches
    """
    analytic = Analytics()
    
    # Prepare normalized targets (same as get_cat does)
    normalized_targets = []
    if window_title:
        normalized_targets.append(window_title.lower())
    if url:
        normalized_targets.append(url.lower())
    
    if not normalized_targets:
        return {"error": "No window title or URL provided"}
    
    # Track all matches
    all_matches = []
    first_match = None
    first_match_rule = None
    
    for idx, (string, category) in enumerate(analytic.string_cats):
        if not string:
            continue
        string = string.strip()
        if not string:
            continue
        
        matched = False
        match_type = "substring"
        matched_target = None
        
        if string.lower().startswith('regex__'):
            pattern = string[7:].strip()
            match_type = "regex"
            for target in normalized_targets:
                try:
                    if re.search(pattern, target.strip(), flags=re.IGNORECASE):
                        matched = True
                        matched_target = target
                        break
                except re.error:
                    continue
        else:
            needle = string.lower()
            for target in normalized_targets:
                if needle in target:
                    matched = True
                    matched_target = target
                    break
        
        if matched:
            match_info = {
                "line": idx + 1,
                "rule": string,
                "category": category,
                "match_type": match_type,
                "matched_in": "title" if matched_target == (window_title.lower() if window_title else None) else "url"
            }
            all_matches.append(match_info)
            
            if first_match is None:
                first_match = category
                first_match_rule = match_info
    
    # Get actual result from get_cat for verification
    actual_category = analytic.get_cat(window_title or "", url)
    
    result = {
        "input": {
            "window_title": window_title,
            "url": url
        },
        "assigned_category": actual_category,
        "matching_rule": first_match_rule,
        "all_matches": all_matches,
        "match_count": len(all_matches)
    }
    
    if verbose:
        print_results(result)
    
    return result


def print_results(result: dict):
    """Pretty print the categorization debug results."""
    print("\n" + "="*70)
    print("CATEGORY CHECK RESULTS")
    print("="*70)
    
    if "error" in result:
        print(f"Error: {result['error']}")
        return
    
    print(f"\n📝 INPUT:")
    if result["input"]["window_title"]:
        # Truncate long titles for display
        title = result["input"]["window_title"]
        if len(title) > 100:
            title = title[:100] + "..."
        print(f"   Title: {title}")
    if result["input"]["url"]:
        url = result["input"]["url"]
        if len(url) > 100:
            url = url[:100] + "..."
        print(f"   URL:   {url}")
    
    print(f"\n🏷️  ASSIGNED CATEGORY: {result['assigned_category']}")
    
    if result["matching_rule"]:
        rule = result["matching_rule"]
        print(f"\n✅ WINNING RULE (first match):")
        print(f"   Config line ~{rule['line']}: '{rule['rule']}' → '{rule['category']}'")
        print(f"   Match type: {rule['match_type']}")
        print(f"   Matched in: {rule['matched_in']}")
    
    if len(result["all_matches"]) > 1:
        print(f"\n⚠️  OTHER RULES THAT ALSO MATCHED ({len(result['all_matches'])-1} more):")
        for match in result["all_matches"][1:]:
            print(f"   Line ~{match['line']}: '{match['rule']}' → '{match['category']}' ({match['match_type']} in {match['matched_in']})")
    
    # Provide suggestions if there's a mismatch
    if len(result["all_matches"]) > 1:
        other_categories = set(m["category"] for m in result["all_matches"][1:])
        if other_categories != {result["assigned_category"]}:
            print(f"\n💡 SUGGESTIONS:")
            print(f"   The URL/title matched multiple categories. If '{result['assigned_category']}' is wrong:")
            print(f"   1. Move the correct rule EARLIER in config.dat (rules are checked in order)")
            print(f"   2. Or make the wrong rule more specific (use regex for exact matching)")
            
            # Check if the problem is "- work -" in browser title
            if result["input"]["window_title"] and "- work -" in result["input"]["window_title"].lower():
                print(f"\n   ⚠️  DETECTED: Your browser tab group name '- work -' is in the title!")
                print(f"   This often causes false 'work' categorization.")
                print(f"   Consider renaming your Edge profile/group or adding a more specific rule.")
    
    print("\n" + "="*70)


def main():
    parser = argparse.ArgumentParser(
        description="Debug tool to check URL/window title categorization",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python check_category.py "how i used ai | linkedin - work - edge"
  python check_category.py --url "www.linkedin.com/pulse/article"
  python check_category.py --title "feed | linkedin" --url "linkedin.com/feed"
        """
    )
    parser.add_argument("text", nargs="?", help="Window title or URL to check")
    parser.add_argument("--title", "-t", help="Window title to check")
    parser.add_argument("--url", "-u", help="URL to check")
    
    args = parser.parse_args()
    
    # Determine what to check
    window_title = args.title or args.text
    url = args.url
    
    if not window_title and not url:
        # Interactive mode
        print("Category Check Tool - Debug URL/Title Categorization")
        print("-" * 50)
        window_title = input("Enter window title (or press Enter to skip): ").strip() or None
        url = input("Enter URL (or press Enter to skip): ").strip() or None
        
        if not window_title and not url:
            print("Error: Please provide at least a title or URL")
            sys.exit(1)
    
    check_categorization(window_title, url)


if __name__ == "__main__":
    main()
