"""
Common prompt templates shared across all agent personas.

This module contains reusable prompt snippets to ensure consistency
across different agent personas and avoid code duplication.
"""

# ask_user() 工具使用规范
ASK_USER_GUIDELINES = """
### CRITICAL: ask_user() Usage Guidelines:
The `ask_user()` tool should be used as a **LAST RESORT ONLY**, not as a first choice:

❌ DO NOT use ask_user() when:
- Current page might be part of a multi-step form/wizard (look for "Next", "Confirm", "Continue" buttons)
- Required fields are not visible yet (try scrolling, swiping, or clicking navigation buttons first)
- You haven't explored all available UI elements (check for tabs, expandable sections, etc.)
- There's a clear path forward through UI interaction (clicking buttons, navigating pages)

✅ ONLY use ask_user() when:
- You've exhausted all UI exploration options (scrolled, checked all pages, clicked all relevant buttons)
- There's genuinely ambiguous information that only the user can clarify
- The app requires external information not available in the UI
- You've confirmed there's no programmatic way to proceed

**Example - WRONG approach:**
```python
# ❌ BAD: Immediately asking user without exploring
# Current page shows "Start Date" field but not "Reason" field
response = ask_user("Current page doesn't show 'Reason' field, should I continue?")
```

**Example - CORRECT approach:**
```python
# ✅ GOOD: Try clicking "Confirm" button to see if it leads to next page
tap_by_index(34)  # Click "Confirm" button
# Wait for next step, observe if "Reason" field appears on next page
```
"""
