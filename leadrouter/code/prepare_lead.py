# LeadRouter step 3: Code by Zapier (Python). Paste this whole file into the step's Code box.
# Input Data to map in the Zap: name, email, company, website, budget, service, timeline, message
# Runs before OpsCore enrichment: cheap checks, a dedupe key for idempotency, and a rule-based base score.
import hashlib
import re

FREE_MAIL = {
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "hotmail.com", "outlook.com", "live.com",
    "msn.com", "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com", "gmx.com", "mail.com", "zoho.com",
}
DISPOSABLE = {"mailinator.com", "guerrillamail.com", "10minutemail.com", "yopmail.com", "tempmail.com", "trashmail.com", "sharklasers.com"}
# Keys are the form's choice labels with everything but letters and digits removed.
BUDGET_POINTS = {"under1k": 5, "1k2k": 15, "2k5k": 30, "5k10k": 40, "10k": 50}
TIMELINE_POINTS = {"asap": 50, "within1month": 40, "13months": 25, "3months": 10, "justexploring": 0}
SPAM_PHRASES = ("backlink", "guest post", "seo package", "first page of google", "crypto", "bitcoin", "casino", "loan offer", "cheap traffic")


def squash(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").lower())


def looks_like_gibberish(name):
    words = re.findall(r"[a-zA-Z0-9]+", name or "")
    if not words or any(ch.isdigit() for ch in name):
        return True
    return any(len(w) >= 5 and not re.search(r"[aeiouy]", w.lower()) for w in words)


email = (input_data.get("email") or "").strip().lower()
email_valid = bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", email))
domain = email.rsplit("@", 1)[-1] if "@" in email else ""
message = input_data.get("message") or ""
name = (input_data.get("name") or "").strip()

website = (input_data.get("website") or "").strip()
if website and "://" not in website:
    website = "https://" + website
if not website and domain and domain not in FREE_MAIL:
    website = "https://" + domain

budget_points = BUDGET_POINTS.get(squash(input_data.get("budget")), 0)
timeline_points = TIMELINE_POINTS.get(squash(input_data.get("timeline")), 0)

spam_reasons = []
if len(re.findall(r"https?://|www\.", message.lower())) >= 2:
    spam_reasons.append("multiple links in message")
if any(p in message.lower() for p in SPAM_PHRASES):
    spam_reasons.append("spam phrase in message")
if domain in DISPOSABLE:
    spam_reasons.append("disposable email domain")
if looks_like_gibberish(name):
    spam_reasons.append("name looks generated")

output = {
    "email": email,
    "email_valid": email_valid,
    "domain": domain,
    "website": website,
    "is_free_mail": domain in FREE_MAIL,
    "dedupe_key": hashlib.sha256(email.encode()).hexdigest(),
    "budget_points": budget_points,
    "timeline_points": timeline_points,
    "base_score": budget_points + timeline_points,
    "is_spam": bool(spam_reasons),
    "spam_reasons": ", ".join(spam_reasons),
}
