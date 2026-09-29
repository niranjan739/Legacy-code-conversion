from langchain_text_splitters import RecursiveCharacterTextSplitter, Language

class ASTSplitter:
    def __init__(self, language="java"):
        # We fall back to RecursiveCharacterTextSplitter since tree-sitter-languages fails on py3.13
        lang_enum = Language.JAVA if language.lower() == "java" else Language.PYTHON
        self.splitter = RecursiveCharacterTextSplitter.from_language(
            language=lang_enum,
            chunk_size=10000,
            chunk_overlap=1000
        )
        self.language = language

    def split_text(self, code: str) -> list[str]:
        """
        Splits Java code into logical chunks.
        """
        return self.splitter.split_text(code)

    def create_documents(self, texts: list[str], metadatas: list[dict] = None) -> list:
        from langchain_core.documents import Document
                
        docs = []
        for i, text in enumerate(texts):
            chunks = self.split_text(text)
            meta = metadatas[i] if metadatas else {}
            for chunk in chunks:
                docs.append(Document(page_content=chunk, metadata=meta))
        return docs

