#!/usr/bin/env python3
import sys
import re
import xml.etree.ElementTree as ET
from pathlib import Path

def merge_xml_files(input_file, output_file):
    """Merge multiple XML documents while preserving original namespaces and structure"""
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Split into individual XML documents while preserving declarations
        xml_docs = []
        current_doc = []
        in_declaration = False
        
        for line in content.splitlines():
            if '<?xml version="1.0" encoding="UTF-8"?>' in line:
                if current_doc:
                    xml_docs.append('\n'.join(current_doc))
                    current_doc = []
                in_declaration = True
                continue
            current_doc.append(line)
        
        if current_doc:
            xml_docs.append('\n'.join(current_doc))

        if not xml_docs:
            print("No valid XML documents found", file=sys.stderr)
            return False

        # Create a wrapper element that won't interfere with namespaces
        merged_root = ET.Element("merged_documents")

        # Process each document while preserving original structure
        for doc in xml_docs:
            try:
                # Parse document while preserving original declarations
                doc = '<?xml version="1.0" encoding="UTF-8"?>\n' + doc
                root = ET.fromstring(doc)
                
                # Create a container that won't interfere with namespaces
                container = ET.SubElement(merged_root, "document")
                container.append(root)
                
            except ET.ParseError as e:
                print(f"Error parsing document: {e}", file=sys.stderr)
                continue

        # Write output while preserving original formatting
        with open(output_file, 'wb') as f:
            # Write XML declaration
            f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
            
            # Manually write the root element start tag
            f.write(b'<merged_documents>\n')
            
            # Write each document with original formatting
            for doc in xml_docs:
                # Skip the XML declaration if present
                doc_lines = doc.splitlines()
                if '<?xml' in doc_lines[0]:
                    doc_lines = doc_lines[1:]
                # Indent and write the document content
                for line in doc_lines:
                    f.write(f'  {line}\n'.encode('utf-8'))
            
            # Close root element
            f.write(b'</merged_documents>')

        print(f"Successfully merged {len(xml_docs)} documents to {output_file}")
        return True

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return False

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python merge_xml.py <input_file.xml> <output_file.xml>", file=sys.stderr)
        sys.exit(1)
    
    input_file = Path(sys.argv[1])
    output_file = Path(sys.argv[2])
    
    if not input_file.exists():
        print(f"Input file {input_file} does not exist", file=sys.stderr)
        sys.exit(1)
    
    success = merge_xml_files(input_file, output_file)
    sys.exit(0 if success else 1)