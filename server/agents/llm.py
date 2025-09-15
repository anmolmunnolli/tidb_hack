import os
from langchain_huggingface import ChatHuggingFace, HuggingFaceEndpoint

def get_chat():
    token = os.getenv("HUGGINGFACEHUB_API_TOKEN")
    if not token:
        raise RuntimeError("HUGGINGFACEHUB_API_TOKEN is not set. Did you forget your .env?")
    
    repo_id = os.getenv("HF_MODEL", "mistralai/Mixtral-8x7B-Instruct-v0.1")
    
    llm = HuggingFaceEndpoint(
        repo_id=repo_id,
        huggingfacehub_api_token=token,
        temperature=0.1,
    )
    
    return ChatHuggingFace(llm=llm)
