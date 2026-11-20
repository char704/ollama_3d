import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from adapters.jhv_vbom import render_vbom


def sheet():
    return [
        ["", "", "", "", "", "AB1234", "CD2345"],
        ["Variation", "Part ID", "Part Name", "Supplier Material ID", "Supplier Material Name", "Color", "Color"],
        ["x", "1200-01", "Outsole", "MAT_A", "Rubber", "RED Red", "BLU Blue"],
        ["x", "8910", "Ignore", "MAT_B", "Rubber", "RED Red", "BLU Blue"],
        ["x", "1002", "Upper", "MAT_U", "Textile", "NA", "BLK Black"],
        ["x", "1003", "Heel", "MAT_H", "Textile", "", ""],
    ]


class JHVBomTests(unittest.TestCase):
    def test_v26_shape_and_filtering(self):
        xml, stats = render_vbom(sheet(), "Shoe")
        root=ET.fromstring(xml)
        self.assertEqual(root.tag, "VBOM")
        self.assertEqual(root.attrib["scene"], "Shoe")
        self.assertEqual([a.get("id") for a in root.findall("ReferenceParts")], ["AB1234", "CD2345"])
        parts=root.findall(".//Part")
        self.assertEqual(len(parts),3)
        self.assertEqual(parts[0].get("name"),"1200-01_Outsole_L|AB1234")
        self.assertEqual(parts[0].find("VPart").get("color_code"),"RED")
        self.assertEqual(parts[0].find("VPart").get("mat_id"),"MAT_A")
        self.assertEqual(stats["parts"],3)

    def test_invalid_bom(self):
        with self.assertRaisesRegex(ValueError,"Variation"):
            render_vbom([["Wrong"]],"BOM")
        data=sheet()
        data[1][3]="No Material"
        with self.assertRaisesRegex(ValueError,"Supplier Material ID"):
            render_vbom(data,"BOM")

    def test_duplicate_or_unknown_article_fails_safely(self):
        data=sheet()
        data[0][6]="AB1234"
        with self.assertRaisesRegex(ValueError,"DUPLICATE_ARTICLE"):
            render_vbom(data,"BOM")
        data[0][6]="NOT AN ID"
        with self.assertRaisesRegex(ValueError,"INVALID_ARTICLE"):
            render_vbom(data,"BOM")

    def test_escapes_xml_and_cleans_values(self):
        data=sheet()
        data[2][2]="Upper & Lower"
        xml, _=render_vbom(data,"Shoe & Co")
        root=ET.fromstring(xml)
        self.assertEqual(root.get("scene"),"Shoe & Co")
        self.assertIn("Upper  Lower",root.findall(".//Part")[0].get("name"))


if __name__ == "__main__": unittest.main()
