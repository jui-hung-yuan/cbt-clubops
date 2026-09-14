"""The membership email template.

A faithful port of the "Render Email From Template" n8n Code node. Pure string
substitution — no LLM. The wording is fixed; only the guest name, month count,
period label and calculated total change between guests.

Output is HTML and must be sent as such, or the recipient sees raw tags.

``tests/test_email_template.py`` diffs this against the deployed n8n output
character for character, so an accidental rewording fails the build.
"""

from __future__ import annotations

from clubops.domain.fee import format_euro
from clubops.domain.models import (
    DEFAULT_CLUB_DETAILS,
    ClubDetails,
    Quote,
    RenderedEmail,
)

FAQ_URL = "https://centerberlin-toastmasters.de/faq/"

SUBJECT = "Your interest in joining Center Berlin Toastmasters"

# Part of the letter's wording rather than a deployment setting: it tells the
# guest what to type in the transfer reference, and does not change with the
# treasurer. The account details and the signature do, and are ClubDetails.
BANK_REFERENCE = "CBT fees + Your Name"


def esc(value: object) -> str:
    """Escape untrusted text going into markup.

    The guest name comes from a public Google Form. A guest called
    "Anne <Annie> Meyer" would otherwise silently break the email body.
    """
    return (
        str("" if value is None else value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_membership_email(
    guest_name: str, quote: Quote, club: ClubDetails = DEFAULT_CLUB_DETAILS
) -> RenderedEmail:
    """Render the membership email for one guest.

    ``club`` defaults to placeholders so the fidelity tests — and anyone who has
    just cloned this — render a complete, correct letter without configuration.
    A deployment passes the real values; nothing here reads the environment.
    """
    body = f"""
<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.5;color:#222;">

<p>Dear {esc(guest_name)},</p>

<p>Thank you for your interest in joining us and your patience!</p>

<p><strong>Below you will find an overview of our membership process.</strong></p>

<p>1. Transfer the fees (see exact details below). Please consider the fee for the
next {quote.months} months ({esc(quote.period)}) because we work with terms of 6 months
and an additional one-time fee of {format_euro(quote.application_fee)} euros.<br>
Therefore, <strong>{esc(quote.calculation_line)}</strong>. (If you are already a member
of another Toastmasters club, you are exempt from the one-time fee. If you are a
student, please get in touch with us before transferring.)<br>
Once you have made the transfer, please <strong>send us a screenshot or
confirmation of it</strong> so we can match your payment.</p>

<p>2. Once we receive the money transfer, you will need to provide your personal
data and sign a privacy notice.<br>
Thereafter, we shall initiate your on-boarding.</p>

<p>3. A little about Toastmasters again,</p>

<p><strong>What are the benefits of membership?</strong></p>

<ul>
  <li><strong>Practice:</strong> Get stage time to deliver speeches or take on roles as a functionary (e.g., timer or grammarian) in a friendly and supportive atmosphere.</li>
  <li><strong>Support:</strong> Benefit from mentorship for your first few speeches, and receive feedback on your speeches from all members and guests.</li>
  <li><strong>Materials:</strong> Access online educational materials to progress toward your chosen goals.</li>
  <li><strong>Events:</strong> Take advantage of opportunities to participate in speech contests, workshops, and other fun activities.</li>
  <li><strong>Community:</strong> Lastly, meet and network with a diverse and international group of cool people!</li>
</ul>

<p><strong>How much does it cost?</strong></p>

<ul>
  <li><strong>Membership fee (&euro;{format_euro(quote.standard_monthly_fee)} per month)</strong></li>
  <li>You pay from the month you join until the end of a term (March or September, depending on which is closer)</li>
  <li>If you have been a Toastmaster before, you are exempt from the application fee but must provide your Toastmaster&rsquo;s ID when applying.</li>
</ul>

<p><strong>What is the obligation of membership</strong></p>

<ul>
  <li>To <strong>actively participate</strong> in club activities. You can attend meetings, take on roles, and deliver speeches.</li>
</ul>

<p>You can find more details on membership and our meetings on our
<a href="{FAQ_URL}">FAQ page</a>. Should you have any further questions, do not
hesitate to contact me.</p>

<p>Following are the bank details:</p>

<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;margin:12px 0;">
  <tr><td style="padding:2px 12px 2px 0;"><strong>IBAN</strong></td><td style="padding:2px 0;">{club.bank_iban}</td></tr>
  <tr><td style="padding:2px 12px 2px 0;"><strong>BIC</strong></td><td style="padding:2px 0;">{club.bank_bic}</td></tr>
  <tr><td style="padding:2px 12px 2px 0;"><strong>Bank</strong></td><td style="padding:2px 0;">{club.bank_name}</td></tr>
  <tr><td style="padding:2px 12px 2px 0;"><strong>Owner</strong></td><td style="padding:2px 0;">{club.bank_owner}</td></tr>
  <tr><td style="padding:2px 12px 2px 0;"><strong>Reference</strong></td><td style="padding:2px 0;">{BANK_REFERENCE}</td></tr>
</table>

<p>Our best wishes,<br>
{club.signature_name}<br>
on behalf of the board of Center Berlin Toastmasters</p>

</div>
""".strip()

    return RenderedEmail(subject=SUBJECT, body_html=body)
