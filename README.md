# Azure-based Compliance AI System

An AI-powered compliance validation system built on **Azure AI services** that automatically analyzes documents and media content against regulatory or policy rules.

The system uses **FastAPI, Azure AI Search, Azure OpenAI, and LangGraph-based orchestration** to create an automated compliance pipeline capable of indexing documents, retrieving relevant policies, and generating explainable answers.

This project demonstrates how modern **Retrieval Augmented Generation (RAG)** systems can be implemented using Azure-native services for enterprise compliance monitoring.

---

# Architecture Overview

The system follows a typical **RAG (Retrieval Augmented Generation)** architecture.

1. Documents are ingested and indexed.
2. Metadata and text are stored in Azure AI Search.
3. User queries are processed via FastAPI.
4. Relevant documents are retrieved.
5. Azure OpenAI generates grounded responses.

Azure AI Search acts as the retrieval layer that supplies contextual information to the LLM, helping reduce hallucinations and produce reliable answers. :contentReference[oaicite:0]{index=0}

---

# System Components

## 1. Document Indexing Pipeline
Located in:
