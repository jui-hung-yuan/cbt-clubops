"""Center Berlin Toastmasters membership draft workflow.

Reads guest registrations from a Google Sheet, calculates the membership fee,
drafts the welcome email in Gmail for a human to review, marks the row, and
posts to Slack. It never sends email.
"""
