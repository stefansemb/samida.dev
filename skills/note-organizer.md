# Objective
Write a short, well-structured note on a topic and save it as a file, using only local file tools (no web search).

# Steps
1. Use list_directory to see what already exists in the working directory.
2. Draft a short outline for the note (plain text, headings only).
3. Write the note to a markdown file with write_file, following the outline.
4. Use read_file to read the file back and confirm it was saved correctly.
5. Give a one-paragraph summary of what you wrote.

# Rules
- Only use list_directory, read_file, and write_file. Do not attempt web_search or fetch_page.
- Keep the note under 250 words.
- Always verify the file was written correctly by reading it back before finishing - never claim it's done without checking.
