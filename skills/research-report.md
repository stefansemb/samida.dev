# Objective
Research a question using real web search and produce a short, well-cited report.

# Steps
1. Use web_search to find relevant, authoritative sources for the question.
2. Use fetch_page on at least 2 of the most relevant results and actually read the content - do not rely only on search result snippets.
3. Cross-check the information between the sources you opened. Note if sources disagree.
4. Write a short report answering the question, citing the specific URLs you actually opened with fetch_page.
5. If a working directory is available, save the report to a file with write_file (this requires the user's approval). Otherwise, give the report directly in your reply.

# Rules
- Do not answer from memory/training knowledge alone. You must call web_search and fetch_page and base the report on what they actually return.
- Every factual claim in the report must be traceable to one of the URLs you cite.
- If your sources disagree or you are not sure, say so honestly instead of guessing.
- Keep the report under 300 words, plus a "Sources" section listing the URLs.
