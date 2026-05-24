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
            self.size = len(content)
        async def read(self):
            return self.content
            
    dummy_file = DummyUploadFile(file_bytes)
    
    logger.info("Calling upload_invoice...")
    response = await upload_invoice(file=dummy_file, reconstruct=True, reconstruct_mode="heuristic")
    
    print("\n--- RESPONSE DETAILS ---")
    print(f"Response cached: {response.cached}")
    if response.metadata.image_validation:
        print("Image Validation Report:")
        print(f"  Valid: {response.metadata.image_validation.is_valid}")
        print(f"  Quality Score: {response.metadata.image_validation.quality_score}")
        print(f"  Warnings: {response.metadata.image_validation.warnings}")
        print(f"  Properties: {response.metadata.image_validation.properties}")
    else:
        print("MISSING image_validation")
        
    if response.metadata.reconstructed_rows:
        print(f"Found reconstructed_rows! Length: {len(response.metadata.reconstructed_rows)}")
    else:
        print("reconstructed_rows is empty or None")

asyncio.run(test_route())
