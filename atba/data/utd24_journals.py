"""The UTD24 journal list — the 24 top management journals ranked by UT Dallas, used to scope D.4's
retrieval service to a journal range.

Source/credit: the journal list and the Scopus exact-name mapping are drawn from the same
already-validated data in an earlier project that also used the Scopus API for management-literature
retrieval (reusing its mapping from journal name to a Scopus `EXACTSRCTITLE`-matchable string, rather
than re-discovering the same pitfalls).

Why this mapping (`UTD24_SCOPUS_NAMES`) is needed instead of searching directly with the journal's full
name: Scopus's `EXACTSRCTITLE()` requires an exact match against the journal-name string registered in
its database, which doesn't always match a journal's official full name/common abbreviation exactly
(e.g. the "&" in "Manufacturing & Service Operations Management" is registered as "and" in Scopus) —
this mapping handles that kind of discrepancy; a blank/identical entry means the official full name
already matches exactly.
"""

UTD24_JOURNALS = [
    # Accounting (3)
    "The Accounting Review",
    "Journal of Accounting and Economics",
    "Journal of Accounting Research",
    # Finance (3)
    "Journal of Finance",
    "Journal of Financial Economics",
    "Review of Financial Studies",
    # Information Systems (3)
    "MIS Quarterly",
    "Information Systems Research",
    "Journal of Management Information Systems",
    # Management (6)
    "Academy of Management Journal",
    "Academy of Management Review",
    "Administrative Science Quarterly",
    "Organization Science",
    "Strategic Management Journal",
    "Journal of International Business Studies",
    # Marketing (3)
    "Journal of Marketing",
    "Journal of Marketing Research",
    "Journal of Consumer Research",
    # Operations Management (3)
    "Manufacturing & Service Operations Management",
    "Management Science",
    "Operations Research",
    # General Management / Organizational Behavior (3)
    "Journal of Applied Psychology",
    "Personnel Psychology",
    "Organizational Behavior and Human Decision Processes",
]

# 期刊全称 → Scopus EXACTSRCTITLE()能精确匹配的刊名字符串（处理缩写/符号差异）
UTD24_SCOPUS_NAMES = {
    "The Accounting Review": "Accounting Review",
    "Journal of Accounting and Economics": "Journal of Accounting and Economics",
    "Journal of Accounting Research": "Journal of Accounting Research",
    "Journal of Finance": "Journal of Finance",
    "Journal of Financial Economics": "Journal of Financial Economics",
    "Review of Financial Studies": "Review of Financial Studies",
    "MIS Quarterly": "MIS Quarterly",
    "Information Systems Research": "Information Systems Research",
    "Journal of Management Information Systems": "Journal of Management Information Systems",
    "Academy of Management Journal": "Academy of Management Journal",
    "Academy of Management Review": "Academy of Management Review",
    "Administrative Science Quarterly": "Administrative Science Quarterly",
    "Organization Science": "Organization Science",
    "Strategic Management Journal": "Strategic Management Journal",
    "Journal of International Business Studies": "Journal of International Business Studies",
    "Journal of Marketing": "Journal of Marketing",
    "Journal of Marketing Research": "Journal of Marketing Research",
    "Journal of Consumer Research": "Journal of Consumer Research",
    "Manufacturing & Service Operations Management": "Manufacturing and Service Operations Management",
    "Management Science": "Management Science",
    "Operations Research": "Operations Research",
    "Journal of Applied Psychology": "Journal of Applied Psychology",
    "Personnel Psychology": "Personnel Psychology",
    "Organizational Behavior and Human Decision Processes": "Organizational Behavior and Human Decision Processes",
}
