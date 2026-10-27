# UKB-KG

UKB-KG is a research platform for exploring knowledge extracted from UK Biobank-related literature. It connects biomedical entities, relationships, and publication evidence to support discovery and research questions.

## Main Features

- View graph statistics and biomedical entity categories.
- Search entities and inspect their relationships.
- Explore subgraphs and paths between concepts.
- Review source publications and study context.
- Ask questions with optional knowledge graph evidence.

## Technical Architecture

- **Streamlit Community Cloud** hosts the web interface.
- **Modal and FastAPI** provide the backend, with SciBERT and BioBERT supporting entity extraction and retrieval.
- **Neo4j Aura** stores the knowledge graph; Modal Volumes store data and models.
- **LLM APIs** generate answers using optional retrieved graph context.

## License

Source code is released under the MIT License. Data, publications, model weights, and third-party dependencies retain their respective licenses and terms.
