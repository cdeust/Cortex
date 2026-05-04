# Appendix A — Answer-Generation Prompt (verbatim, SHA-256 anchored at protocol freeze)

You are answering a question about a long conversation. Use ONLY the provided context. Do NOT use outside knowledge. Do NOT speculate.

# Context

{CONTEXT}

# Question

{QUESTION}

# Instructions

1. If the context contains a clear answer, give the shortest answer that is factually correct. Prefer one sentence.
2. If the context does NOT contain enough information to answer, reply exactly: `I don't know — the provided context does not contain the answer.`
3. Do NOT mention the context format. Do NOT cite turn numbers. Do NOT say "based on the context".
4. Do NOT guess between multiple plausible answers; abstain instead.
5. Output the answer text only. No preamble, no explanation, no closing remark.
