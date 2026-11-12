"""Search URL builders for the boards that have no public API.

These produce a URL you (or the browser agent) open in a real browser. Nothing
here fetches anything; it only saves you assembling query strings by hand.

LinkedIn's filter parameters are documented below because they are not obvious,
and because LinkedIn treats them as hints rather than hard filters — results
still need the seniority re-check in filters.py.
"""
from __future__ import annotations

import urllib.parse

# LinkedIn f_E (experience level)
LI_EXPERIENCE = {"internship": 1, "entry": 2, "associate": 3, "mid-senior": 4,
                 "director": 5, "executive": 6}
# LinkedIn f_JT (job type)
LI_JOB_TYPE = {"full-time": "F", "part-time": "P", "contract": "C",
               "temporary": "T", "internship": "I", "volunteer": "V"}
# LinkedIn f_WT (workplace type)
LI_WORKPLACE = {"on-site": 1, "remote": 2, "hybrid": 3}
# LinkedIn f_TPR (posted within, in seconds)
LI_POSTED_WITHIN = {"hour": "r3600", "day": "r86400", "week": "r604800",
                    "month": "r2592000"}


def _q(params: dict) -> str:
    clean = {k: v for k, v in params.items() if v not in (None, "", [])}
    return urllib.parse.urlencode(clean, quote_via=urllib.parse.quote, safe=",")


def linkedin(
    keywords: str,
    location: str = "Singapore",
    experience: list[str] | None = None,
    job_type: list[str] | None = None,
    workplace: list[str] | None = None,
    posted_within: str = "week",
    newest_first: bool = True,
) -> str:
    params: dict[str, object] = {"keywords": keywords, "location": location}
    if experience:
        codes = [str(LI_EXPERIENCE[e]) for e in experience if e in LI_EXPERIENCE]
        if codes:
            params["f_E"] = ",".join(codes)
    if job_type:
        codes = [LI_JOB_TYPE[t] for t in job_type if t in LI_JOB_TYPE]
        if codes:
            params["f_JT"] = ",".join(codes)
    if workplace:
        codes = [str(LI_WORKPLACE[w]) for w in workplace if w in LI_WORKPLACE]
        if codes:
            params["f_WT"] = ",".join(codes)
    if posted_within in LI_POSTED_WITHIN:
        params["f_TPR"] = LI_POSTED_WITHIN[posted_within]
    if newest_first:
        params["sortBy"] = "DD"
    return "https://www.linkedin.com/jobs/search/?" + _q(params)


def jobstreet(keywords: str, location: str = "Singapore", newest_first: bool = True) -> str:
    params: dict[str, object] = {"keywords": keywords, "where": location}
    if newest_first:
        params["sortmode"] = "ListedDate"
    return "https://sg.jobstreet.com/jobs?" + _q(params)


def indeed(keywords: str, location: str = "Singapore", days: int = 7,
           newest_first: bool = True) -> str:
    params: dict[str, object] = {"q": keywords, "l": location}
    if days:
        params["fromage"] = days
    if newest_first:
        params["sort"] = "date"
    return "https://sg.indeed.com/jobs?" + _q(params)


def glassdoor(keywords: str, location: str = "Singapore") -> str:
    # locT=N with locId=217 is Singapore as a nation.
    params = {"sc.keyword": keywords, "locT": "N", "locId": 217, "fromAge": 7}
    return "https://www.glassdoor.sg/Job/jobs.htm?" + _q(params)


def mycareersfuture_web(keywords: str, newest_first: bool = True) -> str:
    params: dict[str, object] = {"search": keywords, "page": 0}
    if newest_first:
        params["sortBy"] = "new_posting_date"
    return "https://www.mycareersfuture.gov.sg/search?" + _q(params)


BUILDERS = {
    "linkedin": linkedin,
    "jobstreet": jobstreet,
    "indeed": indeed,
    "glassdoor": glassdoor,
    "mycareersfuture_web": mycareersfuture_web,
}


def build(board: str, keywords: str, **kw) -> str:
    board = board.lower().replace("-", "_")
    if board not in BUILDERS:
        raise ValueError(
            f"No URL builder for {board!r}. Known: {', '.join(sorted(BUILDERS))}"
        )
    fn = BUILDERS[board]
    allowed = fn.__code__.co_varnames[: fn.__code__.co_argcount]
    return fn(keywords, **{k: v for k, v in kw.items() if k in allowed})
