"""Hand-labelled vendor-name pairs for measuring entity-resolution accuracy (D3.4).

Each tuple is (name_a, name_b, same_entity). `same_entity=True` means a correct system
would MERGE them; `False` means it must keep them separate. The set deliberately includes
hard cases: legal-suffix/regional/case/FR-EN variants (true merges), and same-head-token but
genuinely different firms (true splits — the false-merge trap). False merges are the costly
error here (they corrupt both concentration and turnover), so the test targets precision."""

LABELLED_PAIRS = [
    # --- True merges (same entity, different surface form) ---
    ("Acme Inc.", "ACME INCORPORATED", True),
    ("Acme Inc.", "Acme Ltd.", True),
    ("Acme Inc.", "Acme Inc. (Ottawa)", True),
    ("Deloitte Inc.", "Deloitte LLP", True),
    ("Deloitte Toronto", "Deloitte Ottawa", True),
    ("Globex Corporation", "Globex Corp", True),
    ("CGI Information Systems", "CGI Information Systems Inc.", True),
    ("KPMG LLP", "KPMG s.r.l.", True),
    ("Pricewaterhouse Coopers LLP", "PricewaterhouseCoopers LLP", True),
    ("McKinsey & Company", "McKinsey and Company", True),
    ("IBM Canada Ltd.", "IBM Canada Limited", True),
    ("Accenture Inc", "Accenture Inc.", True),
    ("Lockheed Martin Canada", "Lockheed Martin Canada Inc.", True),
    ("Stantec Consulting Ltd.", "Stantec Consulting Ltée", True),
    ("Fujitsu Consulting (Canada) Inc.", "Fujitsu Consulting Canada Inc", True),

    # --- True splits (different entities — must NOT merge) ---
    ("Acme Inc.", "Acme Logistics Inc.", False),
    ("Wayne Systems Inc", "Stark Consulting Ltd", False),
    ("Northwind Solutions Inc", "Northstar Solutions Inc", False),
    ("CGI Group", "TCG Group", False),
    ("Deloitte LLP", "Deloitte Real Estate Advisors Inc.", False),
    ("Maple Consulting Inc.", "Maplewood Consulting Inc.", False),
    ("Pacific Marine Ltd.", "Pacific Aerospace Ltd.", False),
    ("Summit IT Services", "Summit Engineering Services", False),
    ("Riverbend Analytics Services", "Riverbend Analytics Solutions", False),
    ("Hooli Services Ltd", "Hooli Robotics Ltd", False),
    ("Initech LLC", "Initrode LLC", False),
    ("Blue Sky Consulting", "Clear Sky Consulting", False),
]
