import sys
import json
import xml.etree.ElementTree as ET
import xml.dom.minidom
import argparse

def json_to_xml(json_obj, root_tag="root"):
    """Convert JSON object to an XML string."""
    root = ET.Element(root_tag)

    def build_tree(parent, obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                child = ET.SubElement(parent, key)
                build_tree(child, value)
        elif isinstance(obj, list):
            for item in obj:
                child = ET.SubElement(parent, "item")
                build_tree(child, item)
        else:
            parent.text = str(obj)

    build_tree(root, json_obj)

    # Convert XML tree to string
    rough_string = ET.tostring(root, encoding="utf-8")
    
    # Pretty-print XML
    parsed = xml.dom.minidom.parseString(rough_string)
    return parsed.toprettyxml(indent="  ")

def read_json_source(source):
    """Read JSON data from a file or stdin."""
    if source:  # Read from file
        with open(source, "r", encoding="utf-8") as file:
            return json.load(file)
    else:  # Read from stdin
        return json.load(sys.stdin)

def main():
    parser = argparse.ArgumentParser(
        description="Convert JSON input (file or stdin) to pretty-printed XML format."
    )
    parser.add_argument(
        "--input",
        type=str,
        help="Path to the JSON file. If not provided, reads from stdin."
    )
    args = parser.parse_args()

    # Load JSON from file or stdin
    json_data = read_json_source(args.input)

    # Convert JSON to pretty-printed XML
    xml_output = json_to_xml(json_data)
    print(xml_output)

if __name__ == "__main__":
    main()