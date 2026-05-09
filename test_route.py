import asyncio
from api.routes import upload_invoice
from fastapi import UploadFile
import io
from core.logger import logger

async def test_route():
    # Create dummy upload file
    # We will fake the OCR engine by mocking cache or something, but actually we can just use the OCR engine if we have a real image.
    with open("test_images/sample_invoice_1.jpg", "rb") as f:
        file_bytes = f.read()
        
    class DummyUploadFile:
        def __init__(self, content):
            self.content = content
            self.filename = "test.jpg"
            self.content_type = "image/jpeg"
        async def read(self):
            return self.content
            
    dummy_file = DummyUploadFile(file_bytes)
    
    logger.info("Calling upload_invoice...")
    response = await upload_invoice(file=dummy_file, reconstruct=True, reconstruct_mode="heuristic")
    
    print("\n--- RESPONSE KEYS ---")
    print(f"Response cached: {response.cached}")
    print(f"Metadata keys: {response.metadata.keys()}")
    
    if "reconstructed_rows" in response.metadata:
        print(f"Found reconstructed_rows! Length: {len(response.metadata['reconstructed_rows'])}")
    else:
        print("MISSING reconstructed_rows")

asyncio.run(test_route())
