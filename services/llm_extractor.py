import os
import json
import urllib.request
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ValidationError
from core.logger import logger

# 1. Define Strict Output Schema
class MedicineItem(BaseModel):
    product_name: str = Field(description="Exact medicine name")
    batch: Optional[str] = Field(None, description="Batch number")
    expiry: Optional[str] = Field(None, description="Expiry date")
    qty: Optional[float] = Field(None, description="Quantity")
    rate: Optional[float] = Field(None, description="Unit rate/price")
    amount: Optional[float] = Field(None, description="Total value/amount for this row")
    discount: Optional[float] = Field(None, description="Item-level discount value")
    hsn_code: Optional[str] = Field(None, description="HSN code if visible")

class TaxSummary(BaseModel):
    cgst: float = 0.0
    sgst: float = 0.0
    igst: float = 0.0
    total_tax: float = 0.0

class InvoiceMetadata(BaseModel):
    invoice_number: Optional[str] = Field(None, description="Found invoice reference number")
    invoice_date: Optional[str] = Field(None, description="Found date")
    supplier_name: Optional[str] = None
    buyer_name: Optional[str] = None
    gstin: Optional[str] = Field(None, description="Supplier GST number")

class InvoiceSchema(BaseModel):
    metadata: InvoiceMetadata
    items: List[MedicineItem] = Field(default_factory=list, description="Standard product items with amounts > 0")
    scheme_items: List[MedicineItem] = Field(default_factory=list, description="Free goods or items explicitly listed as schemes with amount 0")
    credit_notes: List[Dict[str, Any]] = Field(default_factory=list, description="Any embedded credit note items appearing in separate table grid")
    subtotal: float = 0.0
    tax: TaxSummary
    grand_total: float = 0.0
    extra_data: Dict[str, Any] = Field(default_factory=dict, description="Any other useful properties found")

# 2. LLM Extraction Implementation
class LLMExtractor:
    def __init__(self, endpoint: str = None, model_name: str = "llama3"):
        # Read from env if not supplied, fallback to standard local Ollama
        self.endpoint = endpoint or os.getenv("LOCAL_LLM_API_URL", "http://localhost:11434/v1/chat/completions")
        self.model = model_name or os.getenv("LOCAL_LLM_MODEL", "llama3")
        
    def _construct_system_prompt(self) -> str:
        schema_json = json.dumps(InvoiceSchema.model_json_schema(), indent=2)
        return f"""You are an expert pharmacy document intelligence assistant. 
Analyze the provided OCR Markdown text and extract exact invoice details into strict JSON.
Return ONLY valid JSON matching this JSON Schema:
{schema_json}

GUIDELINES:
- Return RAW pure JSON only. No commentary, no triple backticks.
- If a value is missing, use null or 0.0 as per schema.
- Ensure mathematical consistency: Sum of items should equal subtotal.
- Separate scheme items (with zero amount or 'FREE' label) into the 'scheme_items' array.
- Separate credit note references into the 'credit_notes' array.
- Ignore raw OCR noise/skew fragments.
"""

    def extract(self, markdown_content: str) -> Dict[str, Any]:
        """
        Dispatches markdown contents to local LLM and enforces validation.
        """
        if not markdown_content.strip():
            logger.warning("Empty markdown supplied to LLM Extractor.")
            return InvoiceSchema(metadata=InvoiceMetadata()).model_dump()
            
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": self._construct_system_prompt()},
                {"role": "user", "content": f"Extract structured data from this invoice markdown:\n\n{markdown_content}"}
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"}
        }
        
        logger.info(f"Sending extraction request to local LLM at {self.endpoint} using model={self.model}...")
        
        try:
            req = urllib.request.Request(
                self.endpoint,
                data=json.dumps(payload).encode("utf-8"),
                headers={'Content-Type': 'application/json'},
                method="POST"
            )
            
            with urllib.request.urlopen(req, timeout=60) as response:
                resp_data = response.read().decode('utf-8')
                api_json = json.loads(resp_data)
                
                # Unpack OpenAI-compatible payload structure
                message = api_json.get("choices", [{}])[0].get("message", {}).get("content", "{}")
                
                # Parse actual logic payload
                parsed_content = json.loads(message)
                
                # Validate via Pydantic
                validated = InvoiceSchema(**parsed_content)
                logger.info("Successfully completed LLM extraction & Pydantic validation.")
                return validated.model_dump()
                
        except urllib.error.URLError as e:
            logger.error(f"Network connection to local LLM failed: {e}. Ensure server is running at {self.endpoint}.")
            return {"error": "LLM service unreachable"}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from LLM response: {e}")
            return {"error": "Invalid JSON syntax from model"}
        except ValidationError as e:
            logger.error(f"LLM response did not conform to Invoice schema: {e}")
            return {"error": "Schema validation failed"}
        except Exception as e:
            logger.error(f"Unexpected extraction failure: {e}")
            return {"error": str(e)}
