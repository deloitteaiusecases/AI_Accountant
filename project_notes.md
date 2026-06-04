# AI Accountant App - Project Notes and Architecture

## 1. Project Overview
- **Goal**: Generate monthly Financial Statements (FS) from transactional-level raw data (CSV/Excel) rather than traditional quarterly statements.
- **Core Intelligence**: Utilize OpenAI's latest models to act as the "brain." The app must intelligently ingest 15-20+ files and automatically determine which files and data points are relevant to specific sections of the Financial Statement.
- **Current Focus**: Note 5 (Investments, Net) based on the Bank AlJazira Q1 2025 FS structure.
- **Future Scope**: Expand note-by-note until the entire Financial Statement is fully automated.

## 2. Technology Stack (Proof of Concept)
- **Backend / Logic**: Python
- **Frontend**: Streamlit (with potential to migrate to a different frontend later)
- **AI / LLM**: OpenAI's latest models (e.g., GPT-4o)

## 3. Workflow Architecture (Draft)
1. **File Upload**: User uploads an arbitrary number of CSV/Excel files (15-20+).
2. **Intelligent Routing / Contextualization**: 
   - The system analyzes the uploaded files (e.g., by reading headers, file names, or a few sample rows).
   - The OpenAI model determines which files contain data relevant to Note 5 (and future notes).
3. **Data Extraction & Processing**: 
   - Relevant transactional data is extracted and mapped to the required accounting categories (e.g., FVIS, FVOCI, Amortised Cost, Domestic vs. International).
4. **Aggregation**: The system calculates the net values, impairments, etc.
5. **Generation**: The application generates the output table/FS note in the UI.

## 4. Data Execution Strategy (Selected)
**Approach A Selected**: The AI will act as a code-generator. Once it identifies the relevant files and understands their structure (using headers/sample rows), it will generate Python (Pandas) scripts. These scripts will be executed locally by Streamlit.
- **Advantage**: Highly scalable for massive files (thousands/millions of rows). The LLM never processes the raw transaction rows, avoiding token limits and data privacy risks. The heavy lifting is done locally by the machine.

## 5. Accounting Policy & Mapping Strategy (Selected)
**Hybrid Approach Selected**: 
- **Optional Policy Upload**: The application will feature a dedicated section for users to upload their official Accounting Policies (e.g., PDFs). If uploaded, the AI will strictly adhere to these rules for data categorization (ensuring 100% auditability and compliance).
- **Intelligent Fallback**: If the user chooses *not* to upload policies, the AI will fall back on its pre-trained global accounting knowledge (e.g., IFRS 9) to infer the classifications automatically.

## 6. Data Hierarchy & Testing Strategy
- The application will process data through a 4-level hierarchy:
  - **L4 (Transactional Data)**: The raw input uploaded by the user (e.g., purchases, sales, coupons, Mark-to-Market, EIR, ECL).
  - **L3 (Sub-ledger)**: Aggregated holdings per individual security.
  - **L2 (Note Disclosures)**: The detailed tables for specific FS notes (e.g., Note 5 Investments).
  - **L1 (Financial Statement)**: The high-level face of the financial statements (P&L, Balance Sheet, OCI, and Equity lines).
- **Validation/Testing**: By retaining L1-L3 in our sample files, we possess a built-in "ground truth" test suite. The AI will generate Pandas scripts to process only the L4 data, and we can programmatically verify the script's accuracy by comparing its L1-L3 output against the expected results in the sample.

## 7. User Experience (UX) & Scope (Decided)
- **UX Flow**: Dashboard -> Upload Zone (Drop 15-20 CSVs) -> Optional: Drop Accounting Policy -> Click "Process" -> View Results interactively.
- **Scope of Generation**: The user can optionally select specific notes to generate. By default, the system will attempt to generate the whole FS. **For this POC, we will solely focus on generating Note 5**, leaving the rest empty.
- **Output Format**: The final aggregated tables will be viewable on the Streamlit web app, with dedicated options to export the results to both **Excel** and **PDF**.

---
*End of initial architecture discussion.*
