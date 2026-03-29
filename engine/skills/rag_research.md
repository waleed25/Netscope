---
name: rag-research
description: >
  Search the knowledge base for documentation, technical specifications, manuals,
  RFCs, security advisories, and reference material. Use when user asks about
  documentation, asks you to look something up, references a protocol spec,
  mentions "the manual", "the datasheet", "RFC", or when the knowledge base
  should have the answer.
license: Proprietary
metadata:
  category: knowledge
  triggers:
    - knowledge base
    - documentation
    - manual
    - datasheet
    - spec
    - rfc
    - look up
    - reference
    - according to
    - what does the doc say
    - rag
    - kb
    - search docs
  tool_sequence:
    - rag_status
    - rag_search
  examples:
    - "What does the tshark manual say about display filters?"
    - "Look up the Modbus function codes in the documentation"
    - "Search the knowledge base for DNP3 object groups"
    - "Is there anything in the docs about IEC 62443?"
    - "How many documents are in the knowledge base?"
---

## Knowledge Base Research Workflow

### Check before searching
1. `rag_status` — verify KB has documents and check chunk count. If empty, advise user to upload documentation.
2. `rag_search <specific query>` — search with precise technical terms, not vague phrases

### Effective search queries
- Use specific technical terms: `rag_search modbus function code 16 write multiple registers`
- Include protocol names: `rag_search DNP3 application layer function codes`
- Cite standards: `rag_search IEC 62443 zone conduit model`

### When KB is empty
Tell the user: "The knowledge base is empty. Upload documentation via the RAG panel (PDF, text, or web URL). Recommended sources:
- Wireshark/tshark manual
- Protocol specifications (Modbus, DNP3, IEC standards)
- Security advisories (CISA ICS-CERT)
- Device datasheets"

### Interpreting results
- `best_score >= 0.6`: high confidence match — use freely
- `best_score 0.4–0.6`: relevant but verify — cite with [?]
- `best_score < 0.4`: weak match — state uncertainty
- Empty results: KB doesn't have this topic

Always cite sources from rag_search results using [N] notation.
