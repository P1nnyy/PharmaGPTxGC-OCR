import os
import sys
import json
import datetime
from typing import Any
from pathlib import Path
from dotenv import load_dotenv
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential


def get_field_value(fields: dict, field_name: str) -> Any:
    """
    Safely retrieves the value from a DocumentField dictionary.
    Handles potential variance in Azure Document Intelligence JSON representations.
    """
    field = fields.get(field_name)
    if not field:
        return None
    if isinstance(field, dict):
        for k in ["value", "value_string", "value_date", "value_float", "value_number", "content"]:
            if k in field and field[k] is not None:
                return field[k]
    return getattr(field, "value", getattr(field, "content", None))

def main():
    # 1. Load environment variables
    load_dotenv()
    
    # 2. Read configuration
    endpoint = os.environ.get("DOCUMENTINTELLIGENCE_ENDPOINT")
    api_key = os.environ.get("DOCUMENTINTELLIGENCE_API_KEY")
    model_id = os.environ.get("AZURE_DI_MODEL_ID", "prebuilt-invoice")
    
    if not endpoint:
        print("Error: DOCUMENTINTELLIGENCE_ENDPOINT not found in environment.", file=sys.stderr)
        sys.exit(1)
    if not api_key:
        print("Error: DOCUMENTINTELLIGENCE_API_KEY not found in environment.", file=sys.stderr)
        sys.exit(1)
        
    # 3. Parse command line arguments
    if len(sys.argv) < 2:
        print("Usage: python scripts/smoke_azure_di.py <path_to_invoice_image>", file=sys.stderr)
        sys.exit(1)
        
    document_path = Path(sys.argv[1])
    if not document_path.exists():
        print(f"Error: Document path '{document_path}' does not exist.", file=sys.stderr)
        sys.exit(1)
        
    print(f"Starting Azure Document Intelligence smoke test...")
    print(f"Document: {document_path}")
    print(f"Model ID: {model_id}")
    # Do not print api_key for security/no-secrets rule
    
    # 4. Instantiate DocumentIntelligenceClient
    try:
        client = DocumentIntelligenceClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(api_key)
        )
    except Exception as e:
        print(f"Error instantiating client: {e}", file=sys.stderr)
        sys.exit(1)
        
    # 5. Call Azure Document Intelligence with the local file stream
    try:
        with open(document_path, "rb") as f:
            poller = client.begin_analyze_document(
                model_id=model_id,
                body=f
            )
            result = poller.result()
    except Exception as e:
        print(f"Error calling Azure Document Intelligence: {e}", file=sys.stderr)
        sys.exit(1)
        
    # 6. Convert response to dict
    result_dict = result.as_dict()
    
    # 7. Save raw result JSON to local_runs/azure_smoke/<timestamp>_azure_raw.json
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = Path("local_runs/azure_smoke")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{timestamp}_azure_raw.json"
    
    try:
        with open(output_path, "w", encoding="utf-8") as out_f:
            json.dump(result_dict, out_f, indent=2, default=str)
        print(f"Saved raw JSON response to {output_path}")
    except Exception as e:
        print(f"Warning: Failed to save raw JSON response: {e}", file=sys.stderr)
        
    # 8. Extract and print summary fields
    invoice_number = None
    invoice_date = None
    vendor_name = None
    customer_name = None
    item_count = 0
    subtotal = None
    tax = None
    grand_total = None
    
    if result_dict.get("documents"):
        for doc in result_dict["documents"]:
            fields = doc.get("fields", {})
            
            invoice_number = get_field_value(fields, "InvoiceId")
            invoice_date = get_field_value(fields, "InvoiceDate")
            vendor_name = get_field_value(fields, "VendorName")
            customer_name = get_field_value(fields, "CustomerName")
            
            subtotal = get_field_value(fields, "SubTotal")
            tax = get_field_value(fields, "TotalTax")
            if tax is None:
                tax = get_field_value(fields, "Tax")
            grand_total = get_field_value(fields, "InvoiceTotal")
            
            items_field = fields.get("Items", {})
            if items_field and isinstance(items_field, dict):
                items_list = items_field.get("value", [])
                if isinstance(items_list, list):
                    item_count = len(items_list)
                    
    print("\n--- Extraction Summary ---")
    print(f"Model ID:      {model_id}")
    print(f"Invoice No:    {invoice_number}")
    print(f"Invoice Date:  {invoice_date}")
    print(f"Vendor Name:   {vendor_name}")
    print(f"Customer Name: {customer_name}")
    print(f"Item Count:    {item_count}")
    print(f"Subtotal:      {subtotal}")
    print(f"Tax:           {tax}")
    print(f"Grand Total:   {grand_total}")
    print("--------------------------")

if __name__ == "__main__":
    main()
