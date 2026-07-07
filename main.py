import os
import fitz
import streamlit as st
from dotenv import load_dotenv
from openai import AzureOpenAI
from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
)

# ==========================================
# Load Environment Variables
# ==========================================

load_dotenv()

search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
search_key = os.getenv("AZURE_SEARCH_KEY")
index_name = os.getenv("AZURE_SEARCH_INDEX")

openai_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
)

# ==========================================
# Create Search Index
# ==========================================

def create_index():
    index_client = SearchIndexClient(
        endpoint=search_endpoint,
        credential=AzureKeyCredential(search_key)
    )

    fields = [
        SimpleField(name="id", type="Edm.String", key=True),
        SearchableField(name="content", type="Edm.String"),
        SearchableField(name="source", type="Edm.String")
    ]

    index = SearchIndex(
        name=index_name,
        fields=fields
    )

    try:
        index_client.create_or_update_index(index)
    except Exception:
        pass


create_index()

# ==========================================
# Streamlit UI
# ==========================================

st.set_page_config(page_title="TwoDocsChallenge", page_icon="📄")

st.title("📄 Ask My Docs")
st.caption("Upload two PDFs and ask questions from the most relevant one.")

# ==========================================
# Upload PDFs
# ==========================================

st.subheader("Step 1 - Upload Two PDFs")

uploaded_files = st.file_uploader(
    "Choose exactly two PDF files",
    type="pdf",
    accept_multiple_files=True
)

if uploaded_files is not None:

    if len(uploaded_files) != 2:
        st.info("Please upload exactly TWO PDF files.")
        st.stop()

    search_client = SearchClient(
        endpoint=search_endpoint,
        index_name=index_name,
        credential=AzureKeyCredential(search_key)
    )

    # ------------------------------------------
    # Delete old documents from index
    # ------------------------------------------

    try:
        old_docs = list(search_client.search(search_text="*", top=1000))

        if old_docs:
            search_client.delete_documents(
                [{"id": doc["id"]} for doc in old_docs]
            )
    except Exception:
        pass

    all_documents = []
    doc_id = 1

    with st.spinner("Reading and indexing PDFs..."):

        for uploaded_file in uploaded_files:

            pdf = fitz.open(
                stream=uploaded_file.read(),
                filetype="pdf"
            )

            text = ""

            for page in pdf:
                text += page.get_text()

            pdf.close()

            chunks = [
                text[i:i + 1000]
                for i in range(0, len(text), 1000)
            ]

            for chunk in chunks:

                all_documents.append({
                    "id": str(doc_id),
                    "content": chunk,
                    "source": uploaded_file.name
                })

                doc_id += 1

            st.success(f"✅ Indexed {uploaded_file.name}")

    search_client.upload_documents(all_documents)

    st.success("🎉 Both PDFs indexed successfully!")

    # ==========================================
    # Ask Question
    # ==========================================

    st.subheader("Step 2 - Ask a Question")

    question = st.text_input("Enter your question")

    if st.button("Ask"):

        with st.spinner("Searching..."):

            # ONLY ONE MOST RELEVANT RESULT
            results = list(
                search_client.search(
                    search_text=question,
                    top=1
                )
            )

        if not results:
            st.warning("No relevant information found.")
            st.stop()

        best_result = results[0]

        context = best_result["content"]
        source = best_result.get("source", "Unknown")

        with st.spinner("Generating answer..."):

            response = openai_client.chat.completions.create(
                model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
                messages=[
                    {
                        "role": "system",
                        "content": f"""
You are a helpful assistant.

Answer ONLY using the information below.

If the answer is not available, reply exactly:

I could not find that information in the uploaded PDFs.

Context:

{context}
"""
                    },
                    {
                        "role": "user",
                        "content": question
                    }
                ],
                temperature=0,
                max_tokens=300
            )

        st.subheader("Answer")
        st.success(response.choices[0].message.content)

        st.subheader("Most Relevant Source Document")
        st.write(f"📄 {source}")