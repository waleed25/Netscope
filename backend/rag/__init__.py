"""
RAG (Retrieval-Augmented Generation) package.

Provides context-aware document retrieval with:
  - Sentence window chunking
  - Contextual chunk enrichment (LLM-generated prefixes)
  - Hybrid semantic (ChromaDB) + lexical (BM25) retrieval
  - Reciprocal Rank Fusion
  - FlashRank cross-encoder reranking
  - HyDE (Hypothetical Document Embeddings) query expansion
  - Similarity threshold gating ("not in KB" responses)
  - HHEM faithfulness post-generation checking
"""
